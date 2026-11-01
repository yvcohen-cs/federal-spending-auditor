"""C11 deterministic offline controls; fixtures are not live federal API tests."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import json

import pytest

from src.acquisition_planning import (prepare, AcquisitionLimits, AcquisitionQueue, SourceRequestSpec, QuerySupport, case_report)
from src.evidence_acquisition import (PreservedReplay,SyntheticScenario,acquire,read_run,resolution_replay,
    write_report,verify_report,html,main)
from src.evidence_io import EvidenceError,canonical,digest
from src.award_validation import snapshot
from src.history_demo import fixture,collect_fixture
from src.history_qualification_reporting import write_report as write_c10
from src.scope_models import ScopeRequest
from src.sam_validation import demo as sam_demo, synthetic_row


def base(tmp_path,case='empty_feed',change=None):
    tmp_path.mkdir(parents=True,exist_ok=True)
    a,data=fixture(case)
    if change:change(data)
    root=tmp_path/'base';collect_fixture(root,a,data)
    scope=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    cases=({'collections':[str(root)],'scope':scope.to_dict()},)
    return root,cases


def job(queue,source='fpds',kind='award_history'):
    return next(s for s in queue.requests if s.source==source and s.target_kind==kind)


def scenario(spec,change=None):
    _,data=fixture('equal_control');data['responses']=[r for r in data['responses'] if r['source']==spec.source]
    if change:change(data)
    return SyntheticScenario(request_id=spec.request_id,scenario_json=canonical(data))


def inventory(root):return {n:s.byte_sha256 for n,s in snapshot(root).items()}


def resign_run(root,change):
    value=json.loads((root/'acquisition.json').read_bytes());change(value)
    (root/'acquisition.json').write_text(canonical(value)+'\n')
    files={n:s.byte_sha256 for n,s in snapshot(root).items() if n!='acquisition-commit.json'}
    (root/'acquisition-commit.json').write_text(canonical({'schema_version':1,'files':files,'run_sha256':digest(value)})+'\n')


def test_source_specific_queue_is_bounded_deterministic_and_coalesces_requirements(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases)
    assert q==prepare(cases) and AcquisitionQueue.from_dict(q.to_dict())==q
    assert len(q.requests)<=q.limits.max_jobs
    assert any(len(s.requirements)>1 for s in q.requests)
    assert all(not s.live_request_authorized for s in q.requests)
    assert all(s.historical_interval.start_date is None for s in q.requests)
    assert job(q,'usaspending').selection_json is not None
    assert 'award_id' in json.loads(job(q,'usaspending').request_json)['parameters']
    assert json.loads(job(q).native_context_json)['agency']=='0001'
    assert any(s.target_kind=='parent_idv' and s.request_json is None for s in q.requests)


def test_saved_C10_plans_are_primary_replayed_before_queueing(tmp_path):
    _,cases=base(tmp_path);report=case_report(cases[0]);out=tmp_path/'c10';write_c10(out,report)
    saved=({**cases[0],'report':str(out)},)
    assert prepare(saved)==prepare(cases)
    (out/'qualification.json').write_text('{}')
    with pytest.raises(ValueError):prepare(saved)


def test_award_amount_is_not_a_priority_signal(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases)
    # Queue query selection uses native identifiers and proof prerequisites only;
    # monetary raw observations never appear as priority/ordering fields.
    raw=q.to_dict()
    assert 'amount' not in raw and 'risk_score' not in raw
    assert all('federal_action_obligation' not in json.loads(s.native_context_json) for s in q.requests)
    limited=prepare(cases,limits=AcquisitionLimits(max_jobs=1))
    assert len(limited.requests)==1 and limited.deferred_plan_ids


@pytest.mark.parametrize('field,bad',[('max_jobs',0),('max_jobs',33),('max_requests',0),('max_requests',65),('max_pages',0),('max_pages',5),('page_size',0),('page_size',11),('retries',2),('retries',-1),('max_response_bytes',1023),('max_response_bytes',1048577),('max_jobs',True)])
def test_invalid_budgets_rejected(field,bad):
    with pytest.raises(ValueError):AcquisitionLimits(**{field:bad})


def test_unknown_parent_queries_are_explicit_non_executable_dependencies(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases)
    parent=next(s for s in q.requests if s.target_kind=='parent_idv')
    assert parent.request_json is None and parent.query_support is not QuerySupport.DOCUMENTED_SUBSET
    result=acquire(q,tmp_path/'run',synthetic=(scenario(parent),))
    assert result['receipts'][0]['status']=='query_requires_additional_validation'
    value=resolution_replay(cases,tmp_path/'run')
    assert value['acquisition_failure_blocks_incorporation'] and not value['resolved_plan_ids']


def test_synthetic_counterpart_resolves_one_narrow_requirement_not_financial_eligibility(tmp_path):
    root,cases=base(tmp_path);before=inventory(root);q=prepare(cases);s=job(q)
    result=acquire(q,tmp_path/'run',synthetic=(scenario(s),))
    assert result['new_live_requests']==0 and result['recorded_attempts']==1
    value=resolution_replay(cases,tmp_path/'run')
    assert len(value['resolved_plan_ids'])==1
    impact=next(e for e in value['observation_impacts'] if e['requirement_resolved'])
    assert impact['dimension_affected']=='counterpart_coverage'
    assert impact['source_native_identifiers'] is not None and impact['provenance_reference']
    assert impact['remaining_contract_blockers']
    assert all(not e['financial_comparison_authorized'] for e in value['observation_impacts'])
    assert value['financial_comparison_authorized'] is False and not value['production_readiness_changed']
    assert inventory(root)==before


@pytest.mark.parametrize('bad',[True,0,1,None,'true'])
def test_live_cannot_be_enabled_by_a_flag_or_local_declaration(tmp_path,bad):
    _,cases=base(tmp_path);q=prepare(cases)
    with pytest.raises(EvidenceError,match='live_access_and_authorization_not_verified'):
        acquire(q,tmp_path/'run',live=bad)
    assert not (tmp_path/'run').exists()


def test_no_implicit_HTTP_transport_or_credential_lookup(tmp_path,monkeypatch):
    import src.collection as c3
    import src.sam_validation_capture as c2
    def forbidden(*a,**kw):raise AssertionError('no network or credential access allowed')
    monkeypatch.setattr(c3,'HTTPTransport',forbidden);monkeypatch.setattr(c2,'credential',forbidden)
    _,cases=base(tmp_path);q=prepare(cases)
    acquire(q,tmp_path/'run',synthetic=(scenario(job(q)),))
    assert resolution_replay(cases,tmp_path/'run')['new_live_requests']==0


@pytest.mark.parametrize('kind',['timeout','connection_error','403','500','partial','empty','unsafe_next'])
def test_failed_empty_or_unsafe_acquisition_never_resolves_requirements(tmp_path,kind):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q)
    def change(data):
        r=data['responses'][0]
        if kind in ('timeout','connection_error'):r.update(status=None,error_code=kind,body_complete=False)
        elif kind in ('403','500'):r['status']=int(kind)
        elif kind=='partial':r['body_complete']=False
        elif kind=='empty':r['text']='<feed xmlns="http://www.w3.org/2005/Atom"/>'
        else:r['text']=r['text'].replace('</feed>','<link rel="next" href="https://evil.invalid/"/></feed>')
    acquire(q,tmp_path/'run',synthetic=(scenario(s,change),))
    value=resolution_replay(cases,tmp_path/'run')
    assert value['acquisition_failure_blocks_incorporation']
    assert not value['resolved_plan_ids'] and not value['observation_impacts']
    assert all(not c['qualification_recomputed'] for c in value['cases'])


def test_partial_pagination_does_not_invent_unseen_modifications(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases,limits=AcquisitionLimits(max_pages=1));s=job(q,'usaspending')
    def change(d):d['responses'][0]['json']['page_metadata']['hasNext']=True
    acquire(q,tmp_path/'run',synthetic=(scenario(s,change),))
    value=resolution_replay(cases,tmp_path/'run')
    assert value['acquisition_failure_blocks_incorporation'] and not value['resolved_plan_ids']


def test_retry_is_bounded_and_preserves_failed_attempts(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases,limits=AcquisitionLimits(retries=1,max_requests=2));s=job(q)
    def change(d):
        fail=deepcopy(d['responses'][0]);fail['status']=503;fail['retry_after']='0';d['responses'].insert(0,fail)
    result=acquire(q,tmp_path/'run',synthetic=(scenario(s,change),))
    assert result['recorded_attempts']==2
    assert result['receipts'][0]['capture_limitations']
    value=resolution_replay(cases,tmp_path/'run')
    assert len(value['resolved_plan_ids'])==1 and value['financial_comparison_authorized'] is False


def test_request_budget_prevents_retry_from_running_past_cap(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases,limits=AcquisitionLimits(retries=1,max_requests=1));s=job(q)
    def change(d):
        fail=deepcopy(d['responses'][0]);fail['status']=503;d['responses'].insert(0,fail)
    result=acquire(q,tmp_path/'run',synthetic=(scenario(s,change),))
    assert result['recorded_attempts']<=1
    assert not resolution_replay(cases,tmp_path/'run')['resolved_plan_ids']


def test_preserved_capture_replay_is_not_new_or_independent_evidence(tmp_path):
    root,cases=base(tmp_path,'equal_control');q=prepare(cases);s=job(q)
    before=inventory(root)
    acquire(q,tmp_path/'run',preserved=(PreservedReplay(request_id=s.request_id,path=str(root)),))
    value=resolution_replay(cases,tmp_path/'run')
    assert not value['resolved_plan_ids'] and not value['observation_impacts']
    supplied=value['cases'][0]['supplied_evidence']
    assert supplied[0]['duplicate_existing_input'] and not supplied[0]['incorporated']
    assert inventory(root)==before


def test_mutated_request_selection_rejected_not_crosswalked(tmp_path):
    root,cases=base(tmp_path);q=prepare(cases);s=job(q)
    other,_=base(tmp_path/'other',change=lambda d:d['responses'][-1].update(text=d['responses'][-1]['text'].replace('SYNTH-C7-AGREEMENT','DIFFERENT')))
    result=acquire(q,tmp_path/'run',preserved=(PreservedReplay(request_id=s.request_id,path=str(other)),))
    assert not resolution_replay(cases,tmp_path/'run')['resolved_plan_ids']
    assert result['new_live_requests']==0


@pytest.mark.parametrize('which',['body','metadata','symlink','hardlink'])
def test_primary_response_tampering_fails_closed(tmp_path,which):
    root,cases=base(tmp_path,'equal_control');q=prepare(cases);s=job(q)
    f=root/'c3_attempt_000000.body'
    if which=='body':f.write_bytes(f.read_bytes()+b' ')
    elif which=='metadata':
        p=root/'c3_attempt_000000.json';v=json.loads(p.read_bytes());v['body_sha256']='0'*64;p.write_text(canonical(v))
    elif which=='symlink':
        other=tmp_path/'other';other.write_bytes(f.read_bytes());f.unlink();f.symlink_to(other)
    else:
        import os
        os.link(f,tmp_path/'link')
    result=acquire(q,tmp_path/'run',preserved=(PreservedReplay(request_id=s.request_id,path=str(root)),))
    assert result['receipts'][0]['status']=='acquisition_failed_primary_evidence_retained'
    with pytest.raises((ValueError,OSError)):resolution_replay(cases,tmp_path/'run')


@pytest.mark.parametrize('mutation',['mode','authorize','version','path','duplicate','unknown_request'])
def test_forged_receipts_and_replayed_bindings_rejected(tmp_path,mutation):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q);out=tmp_path/'run';acquire(q,out,synthetic=(scenario(s),))
    def change(v):
        r=v['receipts'][0]
        if mutation=='mode':r['mode']='live_authenticated_request'
        elif mutation=='authorize':r['financial_comparison_authorized']=True
        elif mutation=='version':v['schema_version']=9
        elif mutation=='path':r['capture_dir']='../../private'
        elif mutation=='duplicate':v['receipts'].append(deepcopy(r))
        else:r['request_id']='unknown'
    resign_run(out,change)
    with pytest.raises(ValueError):read_run(out)


@pytest.mark.parametrize('name',['acquisition.json','acquisition-commit.json','capture-000/c3_attempt_000000.body'])
def test_manifest_or_response_corruption_rejected(tmp_path,name):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q);out=tmp_path/'run';acquire(q,out,synthetic=(scenario(s),))
    f=out/name;f.write_bytes(f.read_bytes()+b' ')
    with pytest.raises(ValueError):read_run(out)


@pytest.mark.parametrize('secret',[{'api_key':'not-a-real-secret'},{'password':'synthetic-password'}, {'text':'https://example.invalid/?api_key=synthetic'}])
def test_credential_material_rejected_before_output(tmp_path,secret):
    data={'schema_version':1,'responses':[secret]}
    with pytest.raises(ValueError):SyntheticScenario(request_id='id',scenario_json=canonical(data))


def test_duplicate_case_and_duplicate_binding_rejected(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q);binding=scenario(s)
    with pytest.raises(ValueError):prepare(cases+cases)
    with pytest.raises(ValueError):acquire(q,tmp_path/'run',synthetic=(binding,binding))
    assert not (tmp_path/'run').exists()


def test_unsupported_requested_fields_or_forged_namespace_never_execute(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q)
    for change in ({'requested_fields':('unsupported',)}, {'live_request_authorized':True}, {'request_json':canonical({'endpoint':'https://evil.invalid'})}):
        with pytest.raises(ValueError):replace(s,**change)


def test_reports_are_deterministic_escaped_and_primary_replayed(tmp_path):
    root,cases=base(tmp_path);q=prepare(cases);s=job(q);before=inventory(root)
    a=tmp_path/'a';b=tmp_path/'b'
    acquire(q,a,synthetic=(scenario(s),));acquire(q,b,synthetic=(scenario(s),))
    va=resolution_replay(cases,a);vb=resolution_replay(cases,b)
    assert va==vb
    assert write_report(tmp_path/'ra',va,protected=(root,a))==write_report(tmp_path/'rb',vb,protected=(root,b))
    assert inventory(tmp_path/'ra')==inventory(tmp_path/'rb')
    assert verify_report(tmp_path/'ra',cases,a)==va
    assert inventory(root)==before
    hostile=deepcopy(va);hostile['untrusted']='<script>alert(1)</script>```\x1b[31m\u202e'
    rendered=html(hostile)
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered and '\x1b' not in rendered and '\u202e' not in rendered
    with pytest.raises(OSError):acquire(q,a)
    with pytest.raises(ValueError):write_report(root/'inside',va,protected=(root,))


def test_prior_C10_report_remains_compatible_and_unchanged(tmp_path):
    _,cases=base(tmp_path);old=case_report(cases[0]);out=tmp_path/'c10';write_c10(out,old);before=inventory(out)
    q=prepare(({**cases[0],'report':str(out)},));s=job(q)
    acquire(q,tmp_path/'run',synthetic=(scenario(s),))
    resolution_replay(cases,tmp_path/'run')
    assert inventory(out)==before


def test_source_installation_bound_remains_bounded_and_hash_algorithm_compatible(tmp_path,monkeypatch):
    import src.research_models as m
    monkeypatch.setattr(m,'__file__',str(tmp_path/'module.py'))
    for i in range(3):(tmp_path/f'{i}.py').write_bytes(str(i).encode())
    expected=digest([(p.name,hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(tmp_path.glob('*.py'))])
    assert m.implementation_digest()==expected
    for i in range(3,m.MAX_IMPLEMENTATION_MODULES):(tmp_path/f'{i}.py').write_bytes(b'# synthetic source')
    assert m.implementation_digest()
    (tmp_path/'over.py').write_bytes(b'# too many')
    with pytest.raises(ValueError):m.implementation_digest()


def test_failed_unfinished_transcript_still_consumes_reserved_budget(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases,limits=AcquisitionLimits(max_requests=2,retries=1));s=job(q)
    def failed(d):d['responses'][0]['status']=503 # Retry transcript deliberately missing.
    result=acquire(q,tmp_path/'run',synthetic=(scenario(s,failed),))
    assert result['request_budget_charged']==2
    assert result['receipts'][0]['status']=='acquisition_failed_primary_evidence_retained'
    assert not resolution_replay(cases,tmp_path/'run')['resolved_plan_ids']


def test_sam_first_page_materialization_keeps_namespace_and_no_credentials(tmp_path,monkeypatch):
    import src.sam_validation_capture as c2
    monkeypatch.setattr(c2,'credential',lambda:pytest.fail('no credentials in synthetic mode'))
    root=tmp_path/'sam';sam_demo(root)
    cases=({'sam_captures':[str(root)]},);q=prepare(cases);s=job(q,'samgov')
    data={'schema_version':1,'responses':[{'source':'samgov','json':{'awardSummary':[synthetic_row()],'offset':0,'limit':2,'totalRecords':1},'retrieved_at_utc':'2025-02-01T00:00:00Z'}]}
    result=acquire(q,tmp_path/'run',synthetic=(SyntheticScenario(request_id=s.request_id,scenario_json=canonical(data)),))
    assert result['new_live_requests']==0 and result['recorded_attempts']<=1
    value=resolution_replay(cases,tmp_path/'run')
    assert not value['financial_comparison_authorized']
    assert all(e['source']=='samgov' and not e['requirement_resolved'] for e in value['observation_impacts'])


def test_stale_capture_cannot_resolve_freshness_or_choose_revision_winner(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q)
    def stale(data):data['responses'][0]['retrieved_at_utc']='2020-01-01T00:00:00Z'
    acquire(q,tmp_path/'run',synthetic=(scenario(s,stale),))
    value=resolution_replay(cases,tmp_path/'run')
    assert all(e['dimension_affected']!='freshness' or not e['requirement_resolved'] for e in value['observation_impacts'])
    assert any(r['requirement']['dimension']=='freshness' for c in value['cases'] for r in c['remaining_requirements'])


def test_new_incompatible_amounts_and_reused_identifiers_do_not_authorize_finance(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q)
    def variants(data):
        text=data['responses'][0]['text'];start=text.index('<entry>');end=text.index('</entry>')+8
        other=text[start:end].replace('100.00','101.00')
        data['responses'][0]['text']=text.replace('</feed>',other+'</feed>')
    acquire(q,tmp_path/'run',synthetic=(scenario(s,variants),))
    value=resolution_replay(cases,tmp_path/'run')
    assert not value['financial_comparison_authorized']
    assert any(r['requirement']['status']=='CONFLICTING_EVIDENCE' for c in value['cases'] for r in c['remaining_requirements'])


def test_new_modifications_are_preserved_without_filling_numbering_gaps(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q)
    def mods(data):
        text=data['responses'][0]['text'];first=text[text.index('<entry>'):text.index('</entry>')+8]
        other=first.replace('<f:modNumber>P00001','<f:modNumber>P00003')
        data['responses'][0]['text']=text.replace('</feed>',other+'</feed>')
    acquire(q,tmp_path/'run',synthetic=(scenario(s,mods),))
    value=resolution_replay(cases,tmp_path/'run')
    mods={e['native_action'][0] for e in value['observation_impacts'] if e['native_action']}
    assert 'P00003' in mods and 'P00002' not in mods
    assert any(r['requirement']['dimension']=='revision_completeness' for c in value['cases'] for r in c['remaining_requirements'])


def test_wrong_native_identity_returns_no_successful_resolution(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q)
    def wrong(data):data['responses'][0]['text']=data['responses'][0]['text'].replace('SYNTH-C7-AGREEMENT','SYNTH-UNRELATED')
    result=acquire(q,tmp_path/'run',synthetic=(scenario(s,wrong),))
    assert result['receipts'][0]['status']=='native_scope_unresolved'
    assert not resolution_replay(cases,tmp_path/'run')['resolved_plan_ids']


def test_mixed_synthetic_live_evidence_is_rejected_not_reclassified(tmp_path):
    root,cases=base(tmp_path);q=prepare(cases);s=job(q)
    # The queue cannot make fixture observations into preserved live evidence.
    fake=replace(s,evidence_profile='live');fakeq=replace(q,requests=tuple(fake if x==s else x for x in q.requests))
    result=acquire(fakeq,tmp_path/'run',synthetic=(scenario(fake),))
    assert result['receipts'][0]['status']=='acquisition_failed_primary_evidence_retained'


def test_report_tampering_and_partial_output_are_rejected(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q);run=tmp_path/'run';acquire(q,run,synthetic=(scenario(s),))
    report=resolution_replay(cases,run);out=tmp_path/'report';write_report(out,report)
    (out/'resolution.html').write_text('<script>forged</script>')
    with pytest.raises(ValueError):verify_report(out,cases,run)
    (out/'resolution-commit.json').unlink()
    with pytest.raises(ValueError):verify_report(out,cases,run)


def test_source_mutation_during_copy_cannot_produce_valid_positive_run(tmp_path,monkeypatch):
    import src.evidence_acquisition as module
    root,cases=base(tmp_path,'equal_control');q=prepare(cases);s=job(q)
    original=module.PilotStore.write_bytes;changed=False
    def mutate(self,name,raw):
        nonlocal changed
        original(self,name,raw)
        if name.startswith('capture-') and not changed:
            changed=True;f=root/'c3_attempt_000000.body';f.write_bytes(f.read_bytes()+b' ')
    monkeypatch.setattr(module.PilotStore,'write_bytes',mutate)
    acquire(q,tmp_path/'run',preserved=(PreservedReplay(request_id=s.request_id,path=str(root)),))
    with pytest.raises(ValueError):read_run(tmp_path/'run')


def test_cli_plan_only_verify_and_live_refusal_are_offline_and_sanitized(tmp_path,capsys):
    _,cases=base(tmp_path);recipe=tmp_path/'cases.json';recipe.write_text(canonical(list(cases)))
    args=['--cases',str(recipe),'--run-dir',str(tmp_path/'run')]
    assert main(args+['--report-dir',str(tmp_path/'report')])==0
    assert main(args+['--verify-report',str(tmp_path/'report')])==0
    assert main(['--live','--cases','/private/secret','--run-dir',str(tmp_path/'blocked'),'--report-dir',str(tmp_path/'blocked-report')])==2
    assert '/private/secret' not in capsys.readouterr().out
    assert not (tmp_path/'blocked').exists()


@pytest.mark.parametrize('raw',['{}','{"schema_version":true,"responses":[]}','{"schema_version":2,"responses":[]}','{"schema_version":1,"responses":{},"x":0}'])
def test_malformed_synthetic_schema_never_reaches_transport(raw):
    with pytest.raises(ValueError):SyntheticScenario(request_id='id',scenario_json=raw)


def test_unknown_parent_ids_do_not_coalesce_unrelated_contracts(tmp_path):
    _,a=base(tmp_path/'a','missing_parent')
    def later(data):
        for r in data['responses']:r['retrieved_at_utc']='2025-02-01T00:00:00Z'
    _,b=base(tmp_path/'b','missing_parent',later)
    q=prepare(a+b,limits=AcquisitionLimits(max_jobs=32))
    unknown=[s for s in q.requests if s.target_kind=='parent_idv' and json.loads(s.native_context_json)['piid'] is None]
    assert len(unknown)>=2
    assert all(len({t.contract_id for t in s.requirements})==1 for s in unknown)


def test_outside_requested_context_plans_are_excluded_not_scored(tmp_path):
    def change(data):data['responses'][-1]['text']=data['responses'][-1]['text'].replace('SYNTH-PARENT','OTHER-PARENT')
    _,cases=base(tmp_path,'equal_control',change);q=prepare(cases)
    assert q.excluded_plan_ids
    covered={t.plan_id for s in q.requests for t in s.requirements}
    assert not covered.intersection(q.excluded_plan_ids)


@pytest.mark.parametrize('mutation',['unsupported_schema','forged_scope','forged_query','false_API_certification'])
def test_unsupported_request_states_are_rejected(tmp_path,mutation):
    _,cases=base(tmp_path);s=job(prepare(cases));raw=s.to_dict()
    if mutation=='unsupported_schema':raw['schema_version']=2
    if mutation=='forged_scope':raw['native_context_json']=canonical({'piid':'OTHER','agency':'0001','parent_piid':None,'parent_agency':None})
    if mutation=='forged_query':raw['request_json']=canonical({'source':'fpds','endpoint':'https://evil.invalid','method':'GET','parameters':{}})
    if mutation=='false_API_certification':raw['verified_live_API_behavior']='externally_verified'
    with pytest.raises(ValueError):SourceRequestSpec.from_dict(raw)


def test_oversized_response_is_partial_not_success(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases,limits=AcquisitionLimits(max_response_bytes=1024));s=job(q)
    def huge(data):data['responses'][0]['text']+=' '*2000
    acquire(q,tmp_path/'run',synthetic=(scenario(s,huge),))
    assert not resolution_replay(cases,tmp_path/'run')['resolved_plan_ids']


def test_untrusted_saved_queue_cannot_replace_primary_requirements(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=next(s for s in q.requests if len(s.requirements)>1 and s.query_support is QuerySupport.DOCUMENTED_SUBSET)
    changed=replace(s,requirements=s.requirements[:1]);forged=replace(q,requests=tuple(changed if r==s else r for r in q.requests))
    acquire(forged,tmp_path/'run',synthetic=(scenario(changed),))
    with pytest.raises(EvidenceError,match='queue_must_replay_original_primary_requirements'):
        resolution_replay(cases,tmp_path/'run')


def test_long_retry_after_stops_instead_of_ignoring_server_bound(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases,limits=AcquisitionLimits(retries=1));s=job(q)
    def limited(data):
        failure=deepcopy(data['responses'][0]);failure.update(status=429,retry_after='120');data['responses'].insert(0,failure)
    result=acquire(q,tmp_path/'run',synthetic=(scenario(s,limited),))
    assert result['recorded_attempts']==1
    assert not resolution_replay(cases,tmp_path/'run')['resolved_plan_ids']


def test_source_installation_byte_and_symlink_guards_remain_active(tmp_path,monkeypatch):
    import src.research_models as m
    monkeypatch.setattr(m,'__file__',str(tmp_path/'module.py'))
    other=tmp_path/'original';other.write_bytes(b'# source');(tmp_path/'linked.py').symlink_to(other)
    with pytest.raises(ValueError):m.implementation_digest()
    (tmp_path/'linked.py').unlink();(tmp_path/'huge.py').write_bytes(b'x'*(8*1024*1024+1))
    with pytest.raises(ValueError):m.implementation_digest()


def test_all_previous_protocols_and_documentation_are_byte_identical():
    root=Path(__file__).resolve().parents[1];v=json.loads((root/'docs/evidence-acquisition-protocol-v1.json').read_bytes())
    assert v['starting_main']=='1f5d424bf6f6bb618b494b6d608d897534e01194' and len(v['frozen_files'])==50
    for name,sha in v['frozen_files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==sha


def test_incorporated_observations_preserve_native_money_and_time_fields(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q);acquire(q,tmp_path/'run',synthetic=(scenario(s),))
    value=resolution_replay(cases,tmp_path/'run')
    assert value['incorporated_observations']
    r=value['incorporated_observations'][0]
    assert r['observed_monetary_fields'] and r['observed_temporal_fields'] and r['retrieved_at_utc']
    assert not r['revision_winner_selected'] and not r['missing_modifications_inferred']


def test_partial_failure_cli_returns_nonzero_and_preserves_report(tmp_path):
    _,cases=base(tmp_path);q=prepare(cases);s=job(q)
    data=json.loads(scenario(s).scenario_json);data['responses'][0]['status']=503
    recipes=tmp_path/'cases.json';recipes.write_text(canonical(list(cases)))
    fixtures=tmp_path/'fixtures.json';fixtures.write_text(canonical([{'request_id':s.request_id,'scenario':data}]))
    run=tmp_path/'run';out=tmp_path/'report'
    assert main(['--cases',str(recipes),'--fixture-map',str(fixtures),'--run-dir',str(run),'--report-dir',str(out)])==1
    assert (out/'resolution.json').exists()
    assert verify_report(out,cases,run)['acquisition_failure_blocks_incorporation']


def test_fully_resigned_false_resolution_report_does_not_replace_primary_replay(tmp_path):
    from src.evidence_acquisition import markdown
    _,cases=base(tmp_path);q=prepare(cases);s=job(q);run=tmp_path/'run';acquire(q,run,synthetic=(scenario(s),))
    value=resolution_replay(cases,run);out=tmp_path/'report';write_report(out,value)
    value['resolved_plan_ids'].append('forged-plan')
    (out/'resolution.json').write_text(canonical(value)+'\n');(out/'resolution.md').write_text(markdown(value));(out/'resolution.html').write_text(html(value))
    files={n:s.byte_sha256 for n,s in snapshot(out).items() if n!='resolution-commit.json'}
    (out/'resolution-commit.json').write_text(canonical({'schema_version':1,'files':files,'report_sha256':digest(value)})+'\n')
    with pytest.raises(EvidenceError,match='resolution_primary_replay_conflict'):verify_report(out,cases,run)
