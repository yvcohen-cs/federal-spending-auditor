"""C12 deterministic contracts. Synthetic controls are never federal observations."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import os

import pytest

from src.acquisition_planning import prepare, AcquisitionLimits
from src.collection import SelectedAward
from src.collection_sources import request_for
from src.evidence_io import EvidenceError, canonical, digest
from src.history_demo import fixture,collect_fixture
from src.source_contracts import (identifier,detail_request,award_detail,parent_lookup,
    usa_transaction_contract,collection_contract)
from src.source_verification import (VerificationExperiment,experiment,inspect_experiment,
    integrate,assessment,write_report,verify_report,main)
from tests.test_evidence_acquisition import base,job,inventory


def setup(tmp_path):
    root,cases=base(tmp_path/'input');q=prepare(cases);s=job(q,'usaspending')
    a=SelectedAward.from_dict(json.loads(s.selection_json))
    child={'generated_unique_award_id':a.generated_id,'piid':a.piid,'category':'contract','type':'C',
        'parent_award':{'generated_unique_award_id':'SOURCE-NATIVE-PARENT-001','piid':a.parent_piid,'sub_agency_id':a.parent_agency_id}}
    parent={'generated_unique_award_id':'SOURCE-NATIVE-PARENT-001','piid':a.parent_piid,'category':'idv','type':'IDV_B','parent_award':None}
    _,transcript=fixture('equal_control');transcript['responses']=[r for r in transcript['responses'] if r['source']=='usaspending']
    transcript['responses'][0]['json']['page_metadata'].update(previous=None,next=None,hasPrevious=False)
    scenario={'details':[{'source':'usaspending','json':child},{'source':'usaspending','json':parent}],'transactions':transcript}
    return root,cases,VerificationExperiment(queue=q,request_id=s.request_id,mode='synthetic_only'),scenario


def capture(tmp_path,change=None):
    root,cases,plan,scenario=setup(tmp_path)
    if change:change(scenario)
    out=tmp_path/'capture';value=experiment(out,plan,synthetic=scenario)
    return root,cases,plan,out,value


def resign(root,change):
    change(root)
    from src.award_validation import snapshot
    names={n:s.byte_sha256 for n,s in snapshot(root).items() if n!='experiment-commit.json'}
    (root/'experiment-commit.json').write_text(canonical({'schema_version':1,'files':names})+'\n')


@pytest.mark.parametrize('bad',[None,1,True,'',' ','../x','foo/bar','foo\\bar','x%2fy','x?y','x#z','a\nb','a\x7fb','x'*257])
def test_unsafe_or_untyped_identifiers_fail_closed(bad):
    with pytest.raises(ValueError):identifier(bad)


@pytest.mark.parametrize('native',['00001','ABC-00_01','A.B:0002','SOURCE-NATIVE-PARENT-001'])
def test_literal_source_identifiers_roundtrip_without_key_construction(native):
    assert identifier(native)==native
    assert detail_request(native)['endpoint'].endswith('/'+native.replace(':','%3A')+'/')


def test_complete_current_parent_link_does_not_promote_history_or_money(tmp_path):
    root,cases,p,out,v=capture(tmp_path);assert v==inspect_experiment(out)
    assert v['current_source_parent_link']=='verified_source_local_summary_link'
    assert v['historical_parent_link']==v['freshness']==v['revision_complete']=='unknown'
    report=assessment(cases,out)
    assert report['new_current_parent_subproofs']>=1
    assert not report['resolved_real_source_plan_ids'] and not report['resolved_synthetic_plan_ids']
    assert not report['financial_comparison_authorized'] and not report['production_readiness_changed']
    assert all(not p['original_historical_requirement_resolved'] for p in report['parent_proof_impacts'])
    assert v['request_attempts']<=4 and v['knowledge_basis']=='SYNTHETIC_ONLY'
    assert v['transaction_contract']['histories'][0]['source_contract_satisfied']


def test_original_evidence_is_read_only_and_C11_integration_is_primary_replayed(tmp_path):
    root,cases,p,scenario=setup(tmp_path);before=inventory(root)
    out=tmp_path/'exp';experiment(out,p,synthetic=scenario)
    r=integrate(cases,out,tmp_path/'acquisition')
    assert r['acquisition_resolution']['run']['new_live_requests']==0
    assert not r['resolved_real_source_plan_ids'] and inventory(root)==before
    assert assessment(cases,out,tmp_path/'acquisition')==r


@pytest.mark.parametrize('field,value',[('piid','OTHER'),('generated_unique_award_id','WRONG'),('category','idv'),('type','UNSUPPORTED')])
def test_detail_native_selection_and_instrument_conflicts_stop_queries(tmp_path,field,value):
    root,cases,p,out,v=capture(tmp_path,lambda s:s['details'][0]['json'].__setitem__(field,value))
    assert v['issues'] and v['request_attempts']==1
    assert not (out/'transactions').exists()
    with pytest.raises(EvidenceError):integrate(cases,out,tmp_path/'acquisition')


@pytest.mark.parametrize('field,value',[('piid','WRONG'),('sub_agency_id','0000'),('generated_unique_award_id','bad/path')])
def test_parent_lookup_uses_documented_child_fields_not_inferred_key(tmp_path,field,value):
    _,_,_,out,v=capture(tmp_path,lambda s:s['details'][0]['json']['parent_award'].__setitem__(field,value))
    assert v['issues'] and v['request_attempts']==1
    assert not (out/'detail-001.json').exists()


@pytest.mark.parametrize('change',[lambda d:d.pop('parent_award'),lambda d:d.__setitem__('parent_award',None)])
def test_missing_or_null_parent_never_infers_historical_absence(tmp_path,change):
    _,_,_,out,v=capture(tmp_path,lambda s:change(s['details'][0]['json']))
    assert v['parent'] is None and v['current_source_parent_link']=='insufficient_evidence'
    assert v['historical_parent_link']=='unknown'
    assert not (out/'detail-001.json').exists()


@pytest.mark.parametrize('field,value',[('category','contract'),('type','C'),('piid','OTHER'),('generated_unique_award_id','OTHER')])
def test_separate_parent_primary_must_match_returned_native_key(tmp_path,field,value):
    _,_,_,out,v=capture(tmp_path,lambda s:s['details'][1]['json'].__setitem__(field,value))
    assert v['issues'] and v['current_source_parent_link']=='insufficient_evidence'
    assert v['request_attempts']==2


@pytest.mark.parametrize('status',[301,302,401,403,429,500,503])
def test_failed_public_source_stops_without_retry_or_fallback(tmp_path,status):
    def change(s):s['details'][0]['status']=status
    _,_,_,out,v=capture(tmp_path,change)
    assert v['issues'] and v['request_attempts']==1 and not (out/'transactions').exists()


@pytest.mark.parametrize('kwargs',[{}, {'live':True},{'live':'yes'}])
def test_offline_default_and_unsupported_live_mode_fail_before_output(tmp_path,kwargs):
    _,_,p,s=setup(tmp_path)
    with pytest.raises(ValueError):experiment(tmp_path/'no',p,**kwargs)
    assert not (tmp_path/'no').exists()


def test_live_mode_cannot_accept_synthetic_transport_or_cohort(tmp_path,monkeypatch):
    _,cases,p,s=setup(tmp_path)
    monkeypatch.setattr('src.source_verification.HTTPTransport',lambda *a,**kw:pytest.fail('network transport initialized'))
    with pytest.raises(ValueError):experiment(tmp_path/'no',p,live=True,synthetic=s)
    with pytest.raises(ValueError):replace(p,mode='explicit_public_USA_validation')


def test_synthetic_capture_never_instantiates_network_or_reads_credentials(tmp_path,monkeypatch):
    monkeypatch.setattr('src.source_verification.HTTPTransport',lambda *a,**kw:pytest.fail('network initialized'))
    monkeypatch.setattr('src.sam_validation_capture.credential',lambda:pytest.fail('credential access'))
    _,_,_,_,v=capture(tmp_path)
    assert v['knowledge_basis']=='SYNTHETIC_ONLY'
    assert all(c['representation']=='synthetic_transcript_bytes' for c in v['citations'])


def transaction():
    a,f=fixture('equal_control');r=next(x for x in f['responses'] if x['source']=='usaspending')['json']
    r['page_metadata'].update(previous=None,next=None,hasPrevious=False)
    return a,r,request_for('usaspending',a.to_dict(),1,2)


@pytest.mark.parametrize('field,value',[('next',2),('next',False),('previous',0),('hasPrevious',True),('hasPrevious',0),('hasNext',1),('page',True)])
def test_contradictory_USA_pagination_pointer_tuple_rejected(field,value):
    a,r,req=transaction();r['page_metadata'][field]=value
    with pytest.raises(ValueError):usa_transaction_contract(canonical(r).encode(),req,a.to_dict())


@pytest.mark.parametrize('field',['previous','next','hasPrevious','hasNext','page'])
def test_missing_pagination_is_unknown_not_complete(field):
    a,r,req=transaction();r['page_metadata'].pop(field)
    with pytest.raises(ValueError):usa_transaction_contract(canonical(r).encode(),req,a.to_dict())


@pytest.mark.parametrize('date',['2025-02-30','20250101','2025-01-01T12:00:00Z',None])
def test_unsupported_action_dates_do_not_establish_order(date):
    a,r,req=transaction();r['results'][0]['action_date']=date
    with pytest.raises(ValueError):usa_transaction_contract(canonical(r).encode(),req,a.to_dict())


def test_modification_gaps_and_stale_observations_never_become_history_completeness(tmp_path):
    def change(s):
        r=s['transactions']['responses'][0]['json']['results'][0]
        r['modification_number']='P00009'
        r['id']=r['id'].replace('_P00001_SYNTH-PARENT_','_P00009_SYNTH-PARENT_')
    _,_,_,_,v=capture(tmp_path,change)
    h=v['transaction_contract']['histories'][0]
    assert h['source_contract_satisfied']
    assert h['history_complete']==h['freshness']=='unknown' and not h['missing_modifications_inferred']
    assert not h['correction_winner_selected'] and not h['financial_comparison_authorized']


@pytest.mark.parametrize('kind',['duplicate','variant','reversed','nonterminal','missing_pointer'])
def test_adversarial_history_contracts_do_not_silently_qualify(tmp_path,kind):
    def change(s):
        body=s['transactions']['responses'][0]['json'];row=body['results'][0]
        if kind in ('duplicate','variant','reversed'):
            body['results'].append(deepcopy(row))
            if kind=='variant':body['results'][-1]['federal_action_obligation']=999
            if kind=='reversed':
                body['results'][0]['action_date']='2026-01-01';body['results'][-1]['action_date']='2025-01-01'
        if kind=='nonterminal':body['page_metadata'].update(hasNext=True,next=2)
        if kind=='missing_pointer':body['page_metadata'].pop('previous')
    if kind=='nonterminal':
        # The collector must stop after its bounded transcript is exhausted;
        # original reservation remains for inspection, never silently repaired.
        _,_,p,s=setup(tmp_path);change(s)
        with pytest.raises(ValueError):experiment(tmp_path/'out',p,synthetic=s)
        assert (tmp_path/'out'/'transactions'/'c3_checkpoint.json').exists()
        with pytest.raises(ValueError):inspect_experiment(tmp_path/'out')
    else:
        _,cases,_,out,v=capture(tmp_path,change)
        assert v['transaction_contract']['failures'] or not all(h['source_contract_satisfied'] for h in v['transaction_contract']['histories'])
        with pytest.raises(ValueError):integrate(cases,out,tmp_path/'acq')


@pytest.mark.parametrize('name',['detail-000.body','detail-000.json','experiment.json','detail-000-reservation.json','experiment-commit.json'])
def test_mutated_capture_or_history_is_rejected(tmp_path,name):
    _,_,_,out,_=capture(tmp_path);(out/name).write_text('{}')
    with pytest.raises(ValueError):inspect_experiment(out)


def test_even_resigned_summary_cannot_forge_parent_verification(tmp_path):
    _,_,_,out,_=capture(tmp_path)
    def change(p):
        body=json.loads((p/'detail-001.body').read_text());body['piid']='WRONG';(p/'detail-001.body').write_text(canonical(body))
    resign(out,change)
    with pytest.raises(ValueError):inspect_experiment(out)


@pytest.mark.parametrize('kind',['symlink','hardlink'])
def test_unsafe_source_files_fail_closed(tmp_path,kind):
    _,_,_,out,_=capture(tmp_path);p=out/'detail-000.body';other=tmp_path/'outside';p.rename(other)
    if kind=='symlink':p.symlink_to(other)
    else:os.link(other,p)
    with pytest.raises((ValueError,OSError)):inspect_experiment(out)


def test_extra_attempts_and_incomplete_manifests_preserve_but_reject(tmp_path):
    _,_,_,out,_=capture(tmp_path)
    resign(out,lambda p:(p/'detail-002.json').write_text('{}'))
    with pytest.raises(ValueError):inspect_experiment(out)
    (out/'experiment-commit.json').unlink()
    with pytest.raises(ValueError):inspect_experiment(out)
    assert (out/'detail-000.body').exists()


def test_reports_repeat_and_require_primary_evidence_not_resigned_summaries(tmp_path):
    _,cases,_,out,_=capture(tmp_path)
    a=tmp_path/'a';b=tmp_path/'b'
    assert write_report(a,cases,out)==write_report(b,cases,out)
    assert inventory(a)==inventory(b)
    assert verify_report(a,cases,out)==assessment(cases,out)
    value=json.loads((a/'verification.json').read_text());value['financial_comparison_authorized']=True
    (a/'verification.json').write_text(canonical(value)+'\n')
    with pytest.raises(ValueError):verify_report(a,cases,out)
    (out/'detail-000.body').write_text('{}')
    with pytest.raises(ValueError):verify_report(b,cases,out)


def test_escaped_static_HTML_and_no_secret_or_capability_fields(tmp_path):
    _,cases,_,out,_=capture(tmp_path)
    from src.source_verification import html
    value=assessment(cases,out);value['interpretation']='<script>alert(1)</script>'
    text=html(value)
    assert '<script>' not in text and '&lt;script&gt;' in text and "default-src 'none'" in text
    assert 'api_key' not in canonical(value) and 'session_capability' not in canonical(value)


def test_wrong_original_cases_and_schema_versions_rejected(tmp_path):
    _,cases,p,out,_=capture(tmp_path)
    with pytest.raises(ValueError):VerificationExperiment.from_dict({**p.to_dict(),'schema_version':2})
    with pytest.raises(ValueError):assessment([],out)
    with pytest.raises(ValueError):VerificationExperiment.from_dict({**p.to_dict(),'unexpected':True})


def test_existing_preserved_fixture_contracts_are_replayable_without_new_access(tmp_path):
    a,f=fixture('equal_control');root=tmp_path/'legacy';collect_fixture(root,a,f)
    before=inventory(root);v=collection_contract(root)
    assert {h['source'] for h in v['histories']}=={'fpds'}
    assert any(f['issue']=='USA_pagination_metadata_missing' for f in v['failures'])
    assert inventory(root)==before
    assert all(h['history_complete']=='unknown' for h in v['histories'])


def test_cli_offline_replay_and_live_without_capture_rejection(tmp_path,capsys):
    _,cases,_,out,_=capture(tmp_path);p=tmp_path/'cases.json';p.write_text(canonical(cases))
    assert main(['--cases',str(p),'--run-dir',str(out)])==0
    assert main(['--cases',str(p),'--run-dir',str(tmp_path/'no'),'--live'])==2
    assert not (tmp_path/'no').exists()


@pytest.mark.parametrize('bad',[{},[],None,'text',{'piid':3}])
def test_malformed_details_remain_unqualified(tmp_path,bad):
    def change(s):
        # Fixture transport accepts text for otherwise unsupported top-level JSON.
        s['details'][0].pop('json');s['details'][0]['text']=canonical(bad)
    _,_,_,out,v=capture(tmp_path,change)
    assert v['issues'] and not v['financial_comparison_authorized']
    assert (out/'detail-000.body').exists()


@pytest.mark.parametrize('field,value',[('body_complete',False),('status',None),('error_code','timeout')])
def test_partial_detail_capture_keeps_failure_without_qualification(tmp_path,field,value):
    _,_,_,out,v=capture(tmp_path,lambda s:s['details'][0].__setitem__(field,value))
    assert v['issues'] and v['request_attempts']==1
    assert (out/'detail-000-reservation.json').exists()
    assert v['current_source_parent_link']=='insufficient_evidence'


@pytest.mark.parametrize('field,value',[('body_complete',False),('status',500),('error_code','timeout')])
def test_partial_transaction_failure_cannot_gain_parent_history_qualification(tmp_path,field,value):
    _,cases,_,out,v=capture(tmp_path,lambda s:s['transactions']['responses'][0].__setitem__(field,value))
    assert v['current_source_parent_link']=='verified_source_local_summary_link'
    assert v['transaction_contract']['failures']
    assert not assessment(cases,out)['resolved_synthetic_plan_ids']
    with pytest.raises(ValueError):integrate(cases,out,tmp_path/'acq')


def test_missing_context_agency_does_not_borrow_awarding_or_funding_agency(tmp_path):
    def change(s):
        child=s['details'][0]['json'];child['parent_award'].pop('sub_agency_id')
        child['awarding_agency']={'subtier_agency':{'code':'0002'}}
        child['funding_agency']={'subtier_agency':{'code':'0002'}}
    _,_,_,_,v=capture(tmp_path,change)
    assert v['issues'] and v['request_attempts']==1


def test_self_parent_and_parent_of_parent_are_not_recursively_traversed(tmp_path):
    def change(s):s['details'][1]['json']['parent_award']={'generated_unique_award_id':'THIRD-KEY','piid':'THIRD','sub_agency_id':'0003'}
    _,_,_,out,v=capture(tmp_path,change)
    assert v['request_attempts']==3 and not (out/'detail-002.json').exists()
    assert v['parent']['parent']['generated_unique_award_id']=='THIRD-KEY'


def test_source_wide_completeness_never_inferred_from_empty_terminal_page(tmp_path):
    def change(s):s['transactions']['responses'][0]['json']['results']=[]
    _,cases,_,out,v=capture(tmp_path,change)
    assert not v['transaction_contract']['histories'][0]['source_contract_satisfied']
    assert v['history_complete']==v['source_wide_complete']=='unknown'
    with pytest.raises(ValueError):integrate(cases,out,tmp_path/'acq')


def test_replay_reports_reobservation_not_independent_new_action(tmp_path):
    _,cases,_,out,v=capture(tmp_path)
    r=assessment(cases,out)
    assert v['replay_creates_new_observations'] is False
    assert all(not s['historical_completeness_improved'] for s in r['source_coverage'])


def test_incompatible_money_does_not_grant_arithmetic(tmp_path):
    def change(s):s['transactions']['responses'][0]['json']['results'][0]['federal_action_obligation']=123456789
    _,cases,_,out,v=capture(tmp_path,change)
    r=integrate(cases,out,tmp_path/'acq')
    assert not r['financial_comparison_authorized']
    assert not r['acquisition_resolution']['financial_comparison_authorized']
    assert not r['resolved_real_source_plan_ids']


@pytest.mark.parametrize('name',['verification.json','verification.md','verification.html','verification-commit.json'])
def test_truncated_projections_and_manifests_fail_primary_replay(tmp_path,name):
    _,cases,_,out,_=capture(tmp_path);report=tmp_path/'report';write_report(report,cases,out)
    p=report/name;p.write_bytes(p.read_bytes()[:15])
    with pytest.raises(ValueError):verify_report(report,cases,out)


def test_all_frozen_C11_and_previous_protocol_documents_unchanged():
    import hashlib
    root=Path(__file__).resolve().parents[1]
    v=json.loads((root/'docs/source-verification-protocol-v1.json').read_bytes())
    assert len(v['frozen_files'])==52 and v['starting_main']=='42c0bb97e37609ee63f8e895f620bf0fb6c8cb1c'
    for name,h in v['frozen_files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==h


def test_query_response_cannot_bind_foreign_encoded_native_identity(tmp_path):
    def change(s):
        r=s['transactions']['responses'][0]['json']['results'][0]
        r['id']=r['id'].replace('SYNTH-C7-AGREEMENT','FOREIGN-PIID')
    _,cases,_,out,v=capture(tmp_path,change)
    assert any(f['issue']=='native_record_not_bound_to_requested_context' for f in v['transaction_contract']['failures'])
    with pytest.raises(ValueError):integrate(cases,out,tmp_path/'acq')


def test_child_self_reference_is_rejected_before_parent_access(tmp_path):
    def change(s):s['details'][0]['json']['parent_award']['generated_unique_award_id']=s['details'][0]['json']['generated_unique_award_id']
    _,_,_,out,v=capture(tmp_path,change)
    assert v['issues'] and v['request_attempts']==1 and not (out/'detail-001-reservation.json').exists()


@pytest.mark.parametrize('kind',['failed_request','malformed_page','empty_page'])
def test_CLI_partial_or_empty_transaction_evidence_exits_one_not_success(tmp_path,kind,capsys):
    def change(s):
        response=s['transactions']['responses'][0]
        if kind=='failed_request':response['status']=500
        elif kind=='malformed_page':response['json']['page_metadata'].pop('previous')
        else:response['json']['results']=[]
    _,cases,_,out,_=capture(tmp_path,change);p=tmp_path/'cases.json';p.write_text(canonical(cases))
    assert main(['--cases',str(p),'--run-dir',str(out)])==1
    assert 'source_verification_failed' not in capsys.readouterr().out


@pytest.mark.parametrize('kind',['modification_conflict','parent_conflict','parent_agency_conflict'])
def test_native_action_and_parent_component_conflicts_block_source_contract(tmp_path,kind):
    def change(s):
        row=s['transactions']['responses'][0]['json']['results'][0]
        if kind=='modification_conflict':row['modification_number']='P00009'
        elif kind=='parent_conflict':row['id']=row['id'].replace('SYNTH-PARENT','DIFFERENT-PARENT')
        else:row['id']=row['id'].replace('_0002_','_9999_')
    _,cases,_,out,v=capture(tmp_path,change)
    assert any(f['issue']=='native_record_not_bound_to_requested_context' for f in v['transaction_contract']['failures'])
    assert not any(h['source_contract_satisfied'] for h in v['transaction_contract']['histories'])
    with pytest.raises(ValueError):integrate(cases,out,tmp_path/'acq')
