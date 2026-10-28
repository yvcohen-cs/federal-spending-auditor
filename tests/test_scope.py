from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests

from src.collection import CollectionLimits,collect_selected
from src.collection_sources import FixtureTransport
from src.evidence_io import EvidenceError,canonical,digest,strict_json
from src.financial_ingestion import reconcile_collection
from src.identity_matching import component
from src.matching_ingestion import match_collection
from src.scope_evidence import run_demo,evaluate,main
from src.scope_ingestion import assess_collection
from src.scope_models import ScopeRequest,ScopeRun,ScopeStatus,ObservedIdentity,conclusion
from src.scope_matrix import identity_matrix
from src.research_demo import demo_case


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(requests.Session,'request',Mock(side_effect=AssertionError('network forbidden')))


def request(**changes):
    return ScopeRequest(piid='0001.A',agency='0001',parent_piid='PARENT',parent_agency='0002',**changes)


def observed(**changes):
    fields={'piid':'0001.A','agency':'0001','parent_piid':'PARENT','parent_agency':'0002','modification':'P00001','transaction':'0'}
    fields.update(changes)
    return ObservedIdentity(**{k:component(v) for k,v in fields.items()})


@pytest.mark.parametrize('field,value,status',[('piid','0001.B','verified_out_of_scope'),('agency','9999','verified_out_of_scope'),
    ('parent_piid','OTHER','verified_out_of_scope'),('parent_agency','9999','verified_out_of_scope'),
    ('piid',None,'insufficient_identity'),('agency',None,'insufficient_identity'),('parent_piid','','insufficient_identity'),
    ('parent_agency',None,'insufficient_identity')])
def test_field_scope_exact_native_rules(field,value,status):
    result=conclusion(request(),observed(**{field:value}))
    assert result[0].value==status


def test_exact_context_parent_unknown_and_action_dimensions_separate():
    assert conclusion(request(),observed())[0] is ScopeStatus.IN_SCOPE
    unknown=ScopeRequest(piid='0001.A',agency='0001')
    assert conclusion(unknown,observed())[0] is ScopeStatus.AMBIGUOUS
    assert conclusion(request(modification='P00002'),observed())[0] is ScopeStatus.OUT_OF_SCOPE
    assert conclusion(request(transaction='1'),observed())[0] is ScopeStatus.OUT_OF_SCOPE
    assert conclusion(request(),observed(parent_piid=None))[4]=='unknown_omitted'


@pytest.mark.parametrize('bad',[{'piid':1,'agency':'0001'},{'piid':'','agency':'0001'},{'piid':'0001','agency':'1'},
    {'piid':'0001','agency':'0001','parent_piid':'PARENT'},{'piid':'A\n','agency':'0001'},{'piid':'X','agency':'0001','namespace':'names'}])
def test_invalid_identifiers_no_coercion_or_crosswalk(bad):
    with pytest.raises((ValueError,TypeError)): ScopeRequest(**bad)


def test_native_absence_representations_preserved_not_no_parent():
    assert component(None).original_json!=component('').original_json
    from src.identity_matching import decode_usa_id
    fields,_=decode_usa_id('CONT_TX_0001_-NONE-_0001.A_P00001_-NONE-_0')
    assert fields['parent_piid'].value is None and fields['parent_piid'].original_json=='"-NONE-"'
    assert 'authoritatively_not_applicable' not in conclusion(ScopeRequest(piid='0001.A',agency='0001'),observed(parent_piid=None))


@pytest.fixture(scope='module')
def demos(tmp_path_factory):
    p=tmp_path_factory.mktemp('scope')
    return p,run_demo(p/'a'),run_demo(p/'b')


def test_synthetic_demo_stable_and_out_scope_withheld(demos):
    p,a,b=demos
    assert digest(a)==digest(b)
    data={r['case']:r for r in a['results']}
    assert data['agreement']['metrics']['scoped_numeric_comparisons']==1
    assert data['modifications']['metrics']['scoped_numeric_comparisons']==3
    assert data['ambiguous_parent']['metrics']['counts']['ambiguous_scope']>0
    assert data['ambiguous_parent']['metrics']['scoped_numeric_comparisons']==0
    assert data['out_of_scope']['metrics']['counts']['verified_out_of_scope']==1
    assert data['out_of_scope']['metrics']['scoped_numeric_comparisons']==0
    assert data['unsupported_record']['metrics']['counts']['unsupported_schema']==1
    assert data['duplicates']['metrics']['returned_record_occurrences']>data['duplicates']['metrics']['distinct_record_contents']
    assert data['scope_mismatch']['metrics']['scoped_numeric_comparisons']==0


def test_serialized_scope_cannot_upgrade_status_or_hide_conflicts(demos):
    _,a,_=demos
    data=next(r for r in a['results'] if r['case']=='out_of_scope')['scope']
    scope=ScopeRun.from_dict(data)
    assert scope.to_dict()==data
    value=strict_json(canonical(data).encode())
    for row in value['assessments']:
        if row['status']=='verified_out_of_scope': row['status']='verified_in_scope'
    with pytest.raises(ValueError): ScopeRun.from_dict(value)


def collect(tmp_path,transform=None):
    a,fixture=demo_case('agreement')
    if transform: transform(fixture)
    path=tmp_path/'evidence'
    collect_selected(path,(a,),limits=CollectionLimits(max_awards=1,max_requests=2,retries=0,pace_seconds=0.0),
        profile='fixture:'+digest(fixture),transport=FixtureTransport(fixture),sleep=lambda _:None)
    requested=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    return path,requested


def test_duplicate_contradictory_versions_cannot_be_filtered_into_agreement(tmp_path):
    def conflict(fixture):
        row=fixture['responses'][0]['json']['results'][0]
        fixture['responses'][0]['json']['results'].append({**row,'federal_action_obligation':101})
    path,req=collect(tmp_path,conflict)
    scope=assess_collection(path,req)
    assert sum(a.status is ScopeStatus.AMBIGUOUS for a in scope.assessments)==2
    assert reconcile_collection(path,scope_request=req).results==()


def test_excluded_conflicting_native_context_still_blocks_clean_version(tmp_path):
    def conflict(fixture):
        row=fixture['responses'][0]['json']['results'][0]
        fixture['responses'][0]['json']['results'].append({**row,'modification_number':'P00002'})
    path,req=collect(tmp_path,conflict)
    scope=assess_collection(path,req)
    assert any(a.conflicting_versions for a in scope.assessments)
    assert reconcile_collection(path,scope_request=req).results==()


def test_legacy_default_matches_unchanged_and_scoped_reports_cannot_bypass_revalidation(tmp_path):
    path,req=collect(tmp_path)
    before=match_collection(path)
    scoped=match_collection(path,scope_request=req)
    assert before.decisions==scoped.decisions and before.records!=() and scoped.records!=()
    assert before.substantive_sha256!=scoped.substantive_sha256
    prior=tmp_path/'scoped.json';prior.write_text(scoped.to_json())
    with pytest.raises(EvidenceError,match='stale_or_conflicting_identity_report'):
        reconcile_collection(path,identity_report_path=prior)
    assert len(reconcile_collection(path,identity_report_path=prior,scope_request=req).results)==1


def test_unparseable_payload_does_not_fabricate_record_count(tmp_path):
    path,req=collect(tmp_path,lambda f:f['responses'][-1].update(text='<broken>'))
    scope=assess_collection(path,req)
    assert scope.artifact_issues and not scope.metrics['returned_occurrence_count_complete']
    assert len(scope.assessments)==1


def test_missing_provenance_and_tampered_bytes_never_verify(tmp_path):
    path,req=collect(tmp_path)
    (path/'c3_attempt_000001.body').write_bytes(b'changed')
    with pytest.raises(EvidenceError): assess_collection(path,req)


def test_scope_file_limits_and_unsafe_paths(tmp_path):
    path,req=collect(tmp_path)
    with pytest.raises(EvidenceError,match='scope_record_limit'):
        assess_collection(path,req,max_records=1)
    link=tmp_path/'link';link.symlink_to(path,target_is_directory=True)
    with pytest.raises((ValueError,OSError)): assess_collection(link,req)


def test_matrix_never_claims_shared_records_are_independent():
    matrix=identity_matrix()
    assert not matrix['independent_corroboration']
    assert 'unsupported' in matrix['pairs'][1]['automatic_matching']


def test_cli_requires_explicit_context_and_returns_safe_errors(tmp_path,capsys):
    assert main(['--root',str(tmp_path/'missing'),'--run-dir',str(tmp_path/'out')])==2
    assert not (tmp_path/'out').exists()
    with pytest.raises(SystemExit): main(['--run-dir',str(tmp_path/'out')])


def test_requested_context_cannot_relabel_a_different_collectors_selection(tmp_path):
    path,req=collect(tmp_path)
    with pytest.raises(EvidenceError,match='scope_request_conflicts'):
        assess_collection(path,replace(req,agency='9999'))
    with pytest.raises(EvidenceError,match='scope_request_conflicts'):
        assess_collection(path,replace(req,parent_piid='OTHER'))


def test_conflict_flags_cannot_be_removed_in_serialized_scope(tmp_path):
    def conflict(f):
        r=f['responses'][0]['json']['results'][0]
        f['responses'][0]['json']['results'].append({**r,'federal_action_obligation':101})
    path,req=collect(tmp_path,conflict)
    run=assess_collection(path,req)
    data=run.to_dict()
    from src.scope_models import assessment
    data['assessments']=[assessment(a.requested,a.observed,a.evidence,a.content_sha256,record=a.record,supported=a.supported,
        conflicting=False,original_identity_json=a.original_identity_json).to_dict() for a in run.assessments]
    with pytest.raises(ValueError,match='conflict flags'): ScopeRun.from_dict(data)


def test_scope_withheld_contexts_are_separate_from_financial_date_limits(demos):
    _,data,_=demos
    rows={r['case']:r for r in data['results']}
    assert rows['scope_mismatch']['metrics']['financial_action_contexts_withheld']==0
    assert rows['scope_mismatch']['metrics']['scoped_numeric_comparisons']==0
    assert rows['ambiguous_parent']['metrics']['financial_action_contexts_withheld']==1


def test_parent_state_is_independent_of_primary_and_action_conflicts():
    assert conclusion(request(),observed(piid='OTHER'))[4]=='present_compatible'
    assert conclusion(request(),observed(),conflicting=True)[4]=='present_compatible'
    assert conclusion(request(),observed(parent_piid='OTHER'))[4]=='present_conflicting'


def test_unavailable_response_body_has_unknown_record_count(tmp_path):
    path,req=collect(tmp_path,lambda f:f['responses'][-1].update(status=None,body_complete=False,error_code='request_error'))
    scope=assess_collection(path,req)
    assert len(scope.assessments)==1  # Only the observed USA record is enumerable.
    assert any('response_body_unavailable_record_count_unknown' in issue for issue in scope.artifact_issues)
    assert scope.metrics['returned_occurrence_count_complete'] is False
    assert scope.metrics['unparsed_or_unusable_artifacts']==1
