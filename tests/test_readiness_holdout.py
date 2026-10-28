from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import shutil
from unittest.mock import Mock

import pytest

from src.collection import collect_selected,CollectionLimits
from src.collection_sources import FixtureTransport
from src.evidence_io import EvidenceError,canonical,digest
from src.readiness import assess
from src.readiness_audit import audit_collection,inventory,semantic_digest
from src.readiness_holdout import collect_holdout,audit_holdout,selection,frame_request
from src.readiness_models import Decision,Result
from src.history_ingestion import reconstruct
from src.history_pilot import native_request
from src.history_demo import fixture,collect_fixture
from src.scope_models import ScopeRequest
from readiness_fixtures import frozen,HoldoutTransport


@pytest.fixture(scope='module')
def control(tmp_path_factory):
    p=tmp_path_factory.mktemp('readiness-holdout')/'pilot'
    protocol,ids=frozen(p)
    return p,protocol,ids


def test_live_requires_opt_in_and_fixed_budgets(control,tmp_path):
    _,p,ids=control;t=HoldoutTransport(ids)
    with pytest.raises(EvidenceError): collect_holdout(tmp_path/'no',p,ids,transport=t)
    assert not t.calls and not (tmp_path/'no').exists()
    assert frame_request(p)['parameters']['limit']==6


def test_new_holdout_is_deterministic_distinct_and_never_replaces_failed_slots(control,tmp_path):
    root,p,ids=control;t=HoldoutTransport(ids)
    out=tmp_path/'holdout';collect_holdout(out,p,ids,live=True,transport=t)
    assert len(t.calls)==10
    selection_doc=json.loads((out/'holdout-selection.json').read_text())
    assert len(selection_doc['selected'])==3 and not set(selection_doc['selected'])&set(ids)
    assert selection_doc['overlap_exclusions']==ids[:1]
    cohort=audit_holdout(out,p,ids)
    assert cohort.selected_count==3 and all(s.processed for s in cohort.slots)
    combined=assess(root,holdout=out,protocol=p)
    assert combined.modes[1].result is Decision.CONDITIONAL_GO
    assert all(m.result is Decision.NO_GO for m in combined.modes[2:])
    assert not any(m.collection_permission for m in combined.modes)


@pytest.mark.parametrize('error',[401,403,429,500,503])
def test_source_errors_and_rate_limits_stop_globally_without_retry(control,tmp_path,error):
    _,p,ids=control;t=HoldoutTransport(ids,error=error)
    out=tmp_path/'holdout';collect_holdout(out,p,ids,live=True,transport=t)
    assert len(t.calls)==1
    result=json.loads((out/'holdout-result.json').read_text())
    assert result['stopped'] and result['stop_reason']=='frame_access_unavailable'
    assert not audit_holdout(out,p,ids).available


@pytest.mark.parametrize('option',['scope_conflict','unsafe'])
def test_scope_mismatch_or_unsafe_pagination_stops_with_all_selected_slots_retained(control,tmp_path,option):
    _,p,ids=control;t=HoldoutTransport(ids,**{option:True})
    out=tmp_path/'holdout';collect_holdout(out,p,ids,live=True,transport=t)
    assert len(t.calls)==4  # Frame + discovery + USA + first FPDS, then stop.
    result=json.loads((out/'holdout-result.json').read_text())
    assert result['stopped'] and len(result['slots'])==3
    cohort=audit_holdout(out,p,ids)
    assert cohort.selected_count==3
    assert sum(not s.processed for s in cohort.slots)==2


def test_existing_capture_is_not_overwritten_or_reissued(control,tmp_path):
    _,p,ids=control;t=HoldoutTransport(ids,error=403);out=tmp_path/'holdout'
    collect_holdout(out,p,ids,live=True,transport=t);before=inventory(out)
    with pytest.raises(OSError): collect_holdout(out,p,ids,live=True,transport=t)
    assert len(t.calls)==1 and inventory(out)==before


def test_interruption_retains_reservation_without_trusted_commit(control,tmp_path):
    _,p,ids=control;out=tmp_path/'holdout';t=Mock(side_effect=KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt): collect_holdout(out,p,ids,live=True,transport=t)
    assert (out/'frame-reserved.json').exists() and not (out/'holdout-commit.json').exists()
    with pytest.raises((ValueError,KeyError,OSError)): audit_holdout(out,p,ids)
    with pytest.raises(OSError): collect_holdout(out,p,ids,live=True,transport=t)
    assert t.call_count==1


def test_holdout_tampering_is_not_a_successful_replay(control,tmp_path):
    _,p,ids=control;out=tmp_path/'holdout'
    collect_holdout(out,p,ids,live=True,transport=HoldoutTransport(ids,error=403))
    (out/'frame.body').write_text('changed')
    with pytest.raises(EvidenceError): audit_holdout(out,p,ids)


def test_selection_order_invariant_conflicts_excluded_and_no_outcome_filtering(control):
    _,p,ids=control;t=HoldoutTransport(ids)
    rows=t.rows
    a=selection(canonical({'results':rows,'page_metadata':{'hasNext':True}}).encode(),set(ids),p)
    b=selection(canonical({'results':rows[::-1],'page_metadata':{'hasNext':True}}).encode(),set(ids),p)
    assert a['selected']==b['selected']
    assert a['frame_sha256']!=b['frame_sha256']  # Different raw representation is recorded.
    rows=rows[:3]+[{**rows[1],'changed':'contradictory duplicate'}]
    c=selection(canonical({'results':rows,'page_metadata':{'hasNext':False}}).encode(),set(ids),p)
    assert rows[1]['generated_internal_id'] not in c['selected']
    assert c['conflicting_frame_exclusions']


@pytest.mark.parametrize('raw',[b'not JSON',b'{}',b'{"results": [], "page_metadata": {"hasNext": 1}}',
    b'{"results":[{"generated_internal_id":123}],"page_metadata":{"hasNext":false}}'])
def test_malformed_or_unsupported_holdout_frames_never_select(raw,control):
    with pytest.raises((ValueError,KeyError,TypeError)): selection(raw,set(control[2]),control[1])


def test_reordered_response_rows_change_raw_digest_but_not_interpretation(control,tmp_path):
    a,data=fixture('initial_and_modifications');p=tmp_path/'a';q=tmp_path/'b'
    collect_fixture(p,a,data);other=deepcopy(data);other['responses'][0]['json']['results'].reverse();collect_fixture(q,a,other)
    req=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    first=reconstruct((p,),req);second=reconstruct((q,),req)
    assert first.substantive_sha256!=second.substantive_sha256
    assert semantic_digest(first)==semantic_digest(second)


@pytest.mark.parametrize('case',['missing_parent','scope_mismatch','equal_revision_unknown','partial_pagination','contradictory_observations','duplicate_observations','malformed_date'])
def test_adversarial_source_cases_remain_visible_in_readiness(case,tmp_path):
    a,data=fixture(case);root=tmp_path/'source';collect_fixture(root,a,data)
    before=inventory(root);audit=audit_collection(root,0,a.generated_id,'control/slot-0')
    assert audit.processed and audit.evidence and inventory(root)==before
    assert audit.causes
    assert all(m.numerator is None or m.denominator is None or m.numerator<=m.denominator for m in audit.measurements)
    if case=='equal_revision_unknown': assert any('revision_relationship_unknown' in c.codes for c in audit.causes)
    if case=='scope_mismatch': assert any('query_imprecision' in c.codes for c in audit.causes)


def test_partial_checkpoint_is_not_upgraded_by_readiness(tmp_path):
    a,data=fixture('equal_control');client=FixtureTransport(data);root=tmp_path/'source'
    def transport(request,sequence):
        if sequence==1: raise KeyboardInterrupt
        return client(request,sequence)
    with pytest.raises(KeyboardInterrupt): collect_selected(root,(a,),limits=CollectionLimits(max_awards=1,max_requests=2,retries=0,pace_seconds=0.0),profile='fixture:'+digest(data),transport=transport,sleep=lambda _:None)
    before=inventory(root);audit=audit_collection(root,0,a.generated_id,'control/slot-0')
    assert not audit.processed and audit.unknown_controls and inventory(root)==before


def test_off_host_or_credential_metadata_cannot_pass_safety_controls(tmp_path):
    a,data=fixture('equal_control');root=tmp_path/'source';collect_fixture(root,a,data)
    file=root/'c3_attempt_000000.json';doc=json.loads(file.read_text());doc['request']['endpoint']='https://evil.invalid/'
    doc['request']['parameters']['api_key']='SYNTHETIC_NOT_A_SECRET'
    file.write_text(canonical(doc)+'\n')
    audit=audit_collection(root,0,a.generated_id,'control/slot-0')
    assert 'approved_endpoints_only' in audit.violations and 'no_credential_disclosure' in audit.violations
    assert not audit.processed
