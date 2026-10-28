from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import pytest

from src.collection import collect_selected, CollectionLimits
from src.collection_sources import FixtureTransport
from src.evidence_io import EvidenceError,digest,canonical
from src.history_demo import fixture,collect_fixture,run_demo
from src.history_evidence import write_history,read_history,main,bounded_live
from src.history_ingestion import reconstruct
from src.history_models import HistoricalStatus as S
from src.history_reporting import render_html,research_report,bounded_json
from src.scope_models import ScopeRequest


def make(tmp_path,change=None,*,profile=None):
    a,data=fixture('equal_control')
    if change: change(data)
    source=tmp_path/'source'
    if profile is None: collect_fixture(source,a,data)
    else: collect_selected(source,(a,),limits=CollectionLimits(max_awards=1,max_requests=2,retries=0,pace_seconds=0.0),
        transport=FixtureTransport(data),profile=profile,sleep=lambda _:None)
    req=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    return source,req


def inventory(path):
    return {str(f.relative_to(path)):f.read_bytes() for f in path.rglob('*') if f.is_file()}


def test_readonly_reports_roundtrip_and_safe_exclusive_outputs(tmp_path):
    source,req=make(tmp_path);before=inventory(source)
    run=reconstruct((source,),req);output=tmp_path/'output'
    write_history(output,run,protected=(source,))
    assert read_history(output)==run and inventory(source)==before
    assert set(f.name for f in output.iterdir())=={'history.json','history.txt','history.html','history-commit.json','pilot-plan.json'}
    saved=inventory(output)
    with pytest.raises(OSError): write_history(output,run,protected=(source,))
    assert saved==inventory(output)
    with pytest.raises(EvidenceError): write_history(source/'inside',run,protected=(source,))


@pytest.mark.parametrize('name',['history.json','history.html','history.txt','pilot-plan.json','history-commit.json'])
def test_tampered_or_partial_outputs_never_trusted(tmp_path,name):
    source,req=make(tmp_path);out=tmp_path/'out'
    write_history(out,reconstruct((source,),req))
    (out/name).unlink()
    with pytest.raises(EvidenceError): read_history(out)


def test_raw_evidence_tamper_and_symlink_refused(tmp_path):
    source,req=make(tmp_path)
    body=source/'c3_attempt_000000.body';body.write_bytes(body.read_bytes()+b' ')
    with pytest.raises(EvidenceError): reconstruct((source,),req)
    link=tmp_path/'link';link.symlink_to(source,target_is_directory=True)
    with pytest.raises((ValueError,OSError)): reconstruct((link,),req)


@pytest.mark.parametrize('node,extra',[('signedDate','2024-10-02'),('obligatedAmount','101.00')])
def test_compound_temporal_and_monetary_fields_are_explicitly_unsupported(tmp_path,node,extra):
    def change(data):
        data['responses'][-1]['text']=data['responses'][-1]['text'].replace('</f:'+node+'>','</f:'+node+'><f:'+node+'>'+extra+'</f:'+node+'>',1)
    source,req=make(tmp_path,change);run=reconstruct((source,),req)
    assert any(o.issues for o in run.observations)
    assert all(c.status is S.UNSUPPORTED for c in run.comparisons)


def test_unsupported_numeric_temporal_tokens_preserved_not_coerced(tmp_path):
    source,req=make(tmp_path,lambda d:d['responses'][0]['json']['results'][0].update(action_date=20241001))
    run=reconstruct((source,),req)
    usa=next(o for o in run.observations if o.scope_assessment.evidence.reference.source=='usaspending')
    assert not usa.money and usa.issues
    assert json.loads(usa.freshness.temporal_fields[0].original_json)=={'unsupported_json_number_token':'20241001'}


def test_synthetic_revision_never_promoted_into_live_profile(tmp_path):
    # Deliberately adversarial fixture with a false provenance-profile declaration;
    # no real network is involved and the control still must not authorize money.
    source,req=make(tmp_path,profile='live')
    run=reconstruct((source,),req)
    assert all(o.revision.synthetic_control_revision is None for o in run.observations)
    assert all(c.difference_left_minus_right is None for c in run.comparisons)


def test_schema_change_and_unsafe_continuation_preserve_without_following(tmp_path):
    def change(d):
        d['responses'][-1]['text']=d['responses'][-1]['text'].replace('</feed>','<link rel="next" href="https://evil.invalid/steal"/></feed>')
    source,req=make(tmp_path,change);before=inventory(source)
    run=reconstruct((source,),req)
    assert any(not o.scope_assessment.supported for o in run.observations)
    assert all(c.difference_left_minus_right is None for c in run.comparisons)
    assert inventory(source)==before


def test_unavailable_response_is_not_zero_complete_history(tmp_path):
    source,req=make(tmp_path,lambda d:d['responses'][-1].update(status=None,body_complete=False,error_code='timeout'))
    run=reconstruct((source,),req)
    assert len(run.observations)==1 and run.inputs[0].artifact_issues
    assert all(c.difference_left_minus_right is None for c in run.comparisons)
    assert any(c.pagination.value=='unknown' for c in run.coverage)
    from src.history_reporting import metrics
    assert metrics(run)['enumerated_occurrence_count_complete'] is False
    assert metrics(run)['unusable_source_artifacts']==1


def test_interrupted_capture_is_not_reissued_by_offline_reconstruction(tmp_path):
    a,data=fixture('equal_control');transport=FixtureTransport(data)
    def interrupted(request,sequence):
        if sequence==1: raise KeyboardInterrupt
        return transport(request,sequence)
    p=tmp_path/'source'
    with pytest.raises(KeyboardInterrupt):
        collect_selected(p,(a,),limits=CollectionLimits(max_awards=1,max_requests=2,retries=0,pace_seconds=0.0),
            transport=interrupted,profile='fixture:'+digest(data),sleep=lambda _:None)
    req=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    before=inventory(p)
    with pytest.raises(EvidenceError,match='scope_requires_valid_c3_controls'):
        reconstruct((p,),req)
    assert inventory(p)==before  # An uncertain pending journal needs C3 recovery first.


def test_output_interruption_preserves_partial_bundle_without_overwrite(tmp_path,monkeypatch):
    import src.pilot_store as module
    source,req=make(tmp_path);run=reconstruct((source,),req);out=tmp_path/'out'
    original=module.atomic_create
    def interrupt(fd,name,raw):
        if name=='history.html': raise KeyboardInterrupt
        return original(fd,name,raw)
    monkeypatch.setattr(module,'atomic_create',interrupt)
    with pytest.raises(KeyboardInterrupt): write_history(out,run)
    before=inventory(out)
    with pytest.raises(EvidenceError): read_history(out)
    with pytest.raises(OSError): write_history(out,run)
    assert inventory(out)==before


def test_html_escapes_untrusted_identifiers_and_output_is_bounded(tmp_path):
    source,req=make(tmp_path);report=research_report(reconstruct((source,),req))
    report['run']['scope']['requested']['piid']='<script>alert(1)</script>'
    assert '<script>' not in render_html(report) and '&lt;script&gt;' in render_html(report)
    with pytest.raises(EvidenceError): bounded_json({'large':'x'*100},max_bytes=20)


@pytest.mark.parametrize('args',[[],['--live'],['--demo','--live'],['--root','missing']])
def test_cli_invalid_modes_fail_without_output(tmp_path,args):
    assert main(args+['--run-dir',str(tmp_path/'out')])==2
    assert not (tmp_path/'out').exists()


def test_cli_offline_and_execution_metadata(tmp_path,capsys):
    source,req=make(tmp_path);request=tmp_path/'request.json';request.write_text(req.to_json())
    out=tmp_path/'out'
    assert main(['--root',str(source),'--request',str(request),'--run-dir',str(out),'--execution-time'])==1
    assert read_history(out).executed_at_utc is not None


def test_bounded_live_control_stops_after_unavailable_source(tmp_path):
    source,req=make(tmp_path);calls=[]
    def unavailable(request,sequence):
        calls.append(request)
        return {'status':403,'retrieved_at_utc':'2025-01-01T00:00:00Z','body_complete':True,'error_code':None,'retry_after':None,'source_update_raw':None},b'forbidden'
    run=bounded_live(tmp_path/'live-control',source,req,transport=unavailable)
    assert len(calls)==1 and not run.observations
    assert json.loads((tmp_path/'live-control/live-result.json').read_text())['stopped_on_unsupported_or_scope_change']


def test_bounded_live_control_reuses_exact_selection_and_never_retries(tmp_path):
    source,req=make(tmp_path);_,data=fixture('equal_revision_unknown');calls=[]
    def transport(request,sequence):
        calls.append(request)
        item=deepcopy(next(r for r in data['responses'] if r['source']==request['source']))
        return FixtureTransport({'schema_version':1,'responses':[item]})(request,0)
    before=inventory(source)
    run=bounded_live(tmp_path/'live-control',source,req,transport=transport)
    assert len(calls)==2 and len(run.observations)==2 and inventory(source)==before
    assert not any(c.difference_left_minus_right is not None for c in run.comparisons)


def test_history_demo_twice_has_stable_digest(tmp_path):
    a=run_demo(tmp_path/'a');b=run_demo(tmp_path/'b')
    assert digest(a)==digest(b) and len(a['results'])==18


def test_frozen_synthetic_pilot_is_readonly_and_keeps_denominators(tmp_path):
    from src.pilot_pipeline import run_pilot
    from src.pilot_sampling import PilotConfig
    from src.research_models import implementation_digest
    from src.history_pilot import evaluate_pilot
    p=tmp_path/'pilot';run_pilot(p,PilotConfig(mode='synthetic',target=2,implementation_sha256=implementation_digest()))
    before=inventory(p)
    report=evaluate_pilot(p,tmp_path/'history')
    assert report['metrics']['slot_denominator']==2 and report['http_requests']==0
    assert report['baseline_metrics']=='unchanged_separate_reports' and inventory(p)==before


@pytest.mark.parametrize('amount',['0.001','9007199254740993.01'])
def test_raw_numeric_precision_never_comes_from_c4_floats(tmp_path,amount):
    def change(data):
        usa=data['responses'][0]
        raw=canonical(usa.pop('json')).replace('"federal_action_obligation":100','"federal_action_obligation":'+amount)
        usa['text']=raw
        data['responses'][-1]['text']=data['responses'][-1]['text'].replace('<f:obligatedAmount>100.00','<f:obligatedAmount>'+amount,1)
    source,req=make(tmp_path,change);run=reconstruct((source,),req)
    usa=next(o for o in run.observations if o.scope_assessment.evidence.reference.source=='usaspending')
    assert usa.money[0].observation.value.raw_text==amount
    c=run.comparisons[0]
    assert c.difference_left_minus_right==('0' if amount.endswith('.01') else None)


def test_new_fpds_namespace_is_preserved_but_not_interpreted(tmp_path):
    source,req=make(tmp_path,lambda d:d['responses'][-1].update(text=d['responses'][-1]['text'].replace('https://www.fpds.gov/FPDS','https://www.fpds.gov/UNSUPPORTED-V2')))
    run=reconstruct((source,),req)
    assert any('unsupported_temporal_award_container' in o.issues for o in run.observations)
    assert not any(c.difference_left_minus_right is not None for c in run.comparisons)


def test_raw_amount_collisions_cannot_manufacture_an_agreement(tmp_path):
    def change(data):
        row=deepcopy(data['responses'][0]['json']['results'][0])
        data['responses'][0]['json']['results'].append(row)
        raw=canonical(data['responses'][0].pop('json'))
        raw=raw.replace('"federal_action_obligation":100','"federal_action_obligation":9007199254740993.01',1)
        raw=raw.replace('"federal_action_obligation":100','"federal_action_obligation":9007199254740993.02',1)
        data['responses'][0]['text']=raw
        data['responses'][-1]['text']=data['responses'][-1]['text'].replace('<f:obligatedAmount>100.00','<f:obligatedAmount>9007199254740993.01',1)
    source,req=make(tmp_path,change);run=reconstruct((source,),req)
    assert any(c.context_conflict for c in run.comparisons)
    assert not any(c.difference_left_minus_right is not None for c in run.comparisons)
