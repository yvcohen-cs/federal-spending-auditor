"""C10 authored synthetic controls; no live behavior or financial authorization."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.award_validation import validate as c9, read_report as read_c9, write_report as write_c9, snapshot
from src.evidence_io import EvidenceError, canonical, digest
from src.history_demo import CASES, fixture, collect_fixture
from src.history_qualification import (qualify, HistoricalInterval, QualificationStatus as Q,
    EvidenceKind as K, ProofRequirement, ContractQualification, EvidenceResolutionPlan, DIMENSIONS, aggregate)
from src.history_qualification_reporting import write_report, read_report, verify_report, html, check, main
from src.scope_models import ScopeRequest
from src.sam_validation import demo as sam_demo, synthetic_selection, synthetic_row
from src.sam_validation_capture import collect as sam_collect


def make(tmp_path, case='equal_control', change=None, *, standalone=False, kind=None, stamp=None):
    tmp_path.mkdir(parents=True,exist_ok=True)
    award,data=fixture(case)
    if standalone:
        award=replace(award,parent_piid=None,parent_agency_id=None)
        for row in data['responses'][0]['json']['results']:
            row['id']=row['id'].replace('0001_0002_','0001_-NONE-_').replace('_SYNTH-PARENT_','_-NONE-_')
        text=data['responses'][-1]['text'];start=text.index('<f:referencedIDVID>');end=text.index('</f:referencedIDVID>')+len('</f:referencedIDVID>')
        data['responses'][-1]['text']=text[:start]+text[end:]
    if kind:
        data['responses'][-1]['text']=data['responses'][-1]['text'].replace('<f:award>','<f:award version="1.5">').replace('</f:award>','<f:contractData><f:contractActionType>'+kind+'</f:contractActionType></f:contractData></f:award>')
    if stamp:
        for r in data['responses']: r['retrieved_at_utc']=stamp
    if change: change(data)
    root=tmp_path/'source';collect_fixture(root,award,data)
    scope=ScopeRequest(piid=award.piid,agency=award.agency_id,parent_piid=award.parent_piid,parent_agency=award.parent_agency_id)
    return root,scope


def inventory(path): return {n:s.byte_sha256 for n,s in snapshot(path).items()}


def contract(report,source='fpds'):
    return next(c for c in report['contracts'] if c['qualification']['source']==source)


def requirement(c,name): return next(r for r in c['qualification']['requirements'] if r['dimension']==name)


@pytest.mark.parametrize('case',CASES)
def test_all_existing_history_controls_keep_financial_boundaries_and_reproduce(tmp_path,case):
    root,scope=make(tmp_path,case);before=inventory(root)
    report=qualify((root,),scope)
    assert canonical(report)==canonical(qualify((root,),scope))
    assert inventory(root)==before
    assert not report['qualification_authorizes_arithmetic'] and not report['financial_eligibility_changed']
    assert not report['production_readiness_changed'] and not report['new_collection_enabled']
    assert all(c['qualification']['status']!=Q.QUALIFIED.value for c in report['contracts'])
    assert all(c['historical_order']['authoritative_revision_order'] is None and not c['historical_order']['missing_modifications_inferred'] for c in report['contracts'])
    check(report)
    if case=='contradictory_observations':
        assert requirement(contract(report,'usaspending'),'currency_amount')['status']==Q.CONFLICTING.value
    if case=='duplicate_observations':
        c=contract(report,'usaspending')
        assert c['actions'][0]['occurrence_count']==2
        assert len(c['actions'][0]['distinct_content_hashes'])==1
        assert requirement(c,'currency_amount')['status']==Q.QUALIFIED.value
    if case=='cumulative_only':
        assert requirement(contract(report),'monetary_semantics')['status']==Q.INSUFFICIENT.value
    if case=='partial_pagination':
        assert 'nonterminal_observed_chain' in requirement(contract(report,'usaspending'),'source_completeness')['reasons']
    if case=='empty_feed':
        req=requirement(contract(report,'usaspending'),'counterpart_coverage')
        assert req['status']==Q.INSUFFICIENT.value and req['evidence_kind']==K.MISSING.value
        plan=next(p for p in report['resolution_plans'] if p['requirement']['dimension']=='counterpart_coverage')
        assert plan['relevant_sources']==['fpds','usaspending']


def test_definitive_no_parent_is_narrow_and_not_a_financial_upgrade(tmp_path):
    root,scope=make(tmp_path,standalone=True,kind='D');report=qualify((root,),scope)
    fpds=contract(report);usa=contract(report,'usaspending')
    assert fpds['contract_kinds']==['definitive_contract']
    assert requirement(fpds,'parent_identity')['status']==Q.QUALIFIED.value
    assert fpds['parent_award_existence']=='not_applicable_under_source_specific_no_parent_rule'
    assert requirement(usa,'parent_identity')['status']==Q.INSUFFICIENT.value
    assert fpds['qualification']['status']==Q.INSUFFICIENT.value
    assert not fpds['qualification']['financial_comparison_authorized']


@pytest.mark.parametrize('kind',['C','A','B','Z','d',' D '])
def test_other_instruments_do_not_borrow_definitive_absence_rule(tmp_path,kind):
    root,scope=make(tmp_path,standalone=True,kind=kind)
    assert requirement(contract(qualify((root,),scope)),'parent_identity')['status']==Q.INSUFFICIENT.value


def test_order_reference_does_not_prove_parent_award_exists(tmp_path):
    root,scope=make(tmp_path,kind='C');c=contract(qualify((root,),scope))
    assert c['contract_kinds']==['delivery_order']
    assert requirement(c,'parent_identity')['status']==Q.INSUFFICIENT.value
    assert requirement(c,'parent_identity')['reasons']==['parent_award_primary_record_not_observed']
    assert c['parent_award_existence']=='not_established_by_child_reference'


def test_definitive_contract_with_parent_is_conflicting_not_missing(tmp_path):
    root,scope=make(tmp_path,kind='D');c=contract(qualify((root,),scope))
    assert requirement(c,'parent_identity')['status']==Q.CONFLICTING.value
    assert requirement(c,'parent_identity')['evidence_kind']==K.CONTRADICTORY.value


def test_reused_native_record_ids_keep_distinct_contexts_and_all_citations(tmp_path):
    def mutate(data):
        text=data['responses'][-1]['text'].replace('<entry>','<entry><id>urn:synthetic:reused</id>')
        first=text[text.index('<entry>'):text.index('</entry>')+8]
        other=first.replace('<f:PIID>SYNTH-PARENT</f:PIID>','<f:PIID>OTHER-PARENT</f:PIID>')
        data['responses'][-1]['text']=text.replace('</feed>',other+'</feed>')
    root,scope=make(tmp_path,change=mutate,kind='C');report=qualify((root,),scope)
    fpds=[c for c in report['contracts'] if c['qualification']['source']=='fpds']
    assert len(fpds)==2
    assert sorted(requirement(c,'native_identity')['status'] for c in fpds)==sorted([Q.INSUFFICIENT.value,Q.NOT_EVALUATED.value])
    assert all(len(requirement(c,'native_identity')['citation_ids'])==2 for c in fpds)
    assert not any(t['category']=='conflicting_source_records' for t in report['gap_triage'])
    check(report)


def test_revision_order_is_not_inferred_from_retrieval_or_labels(tmp_path):
    def update(data):
        data['responses'][-1]['text']=data['responses'][-1]['text'].replace('<entry>','<entry><updated>2024-12-31T00:00:00Z</updated>')
    a,scope=make(tmp_path/'a',change=update,stamp='2024-12-31T23:00:00Z')
    def older(data):
        data['responses'][-1]['text']=data['responses'][-1]['text'].replace('<entry>','<entry><updated>2024-01-01T00:00:00Z</updated>')
    b,_=make(tmp_path/'b',change=older,stamp='2025-01-01T00:00:00Z')
    report=qualify((b,a),scope);c=contract(report)
    ids=c['historical_order']['occurrence_ids'];lookup={r['id']:r for r in c['observed_occurrences']}
    assert lookup[ids[0]]['retrieved_at_utc']=='2024-12-31T23:00:00Z'
    assert c['actions'][0]['relationship']=='variant_content_revision_unknown'
    assert requirement(c,'revision_completeness')['status']==Q.INSUFFICIENT.value
    assert c['historical_order']['authoritative_revision_order'] is None


def test_unknown_parent_occurrences_are_not_unified_by_child_spelling(tmp_path):
    root,scope=make(tmp_path,'missing_parent');report=qualify((root,),scope)
    usa=[c for c in report['contracts'] if c['qualification']['source']=='usaspending']
    assert all('unresolved_occurrence' in json.loads(c['qualification']['native_context_json']) for c in usa)
    fpds=[c for c in report['contracts'] if c['qualification']['source']=='fpds']
    assert len(fpds)==2 # Distinct explicitly observed parent pairs remain separate.


@pytest.mark.parametrize('change',[
    lambda d:d['responses'][0]['json']['results'][0].update(federal_action_obligation='100'),
    lambda d:d['responses'][0]['json']['results'][0].update(federal_action_obligation=100.001),
    lambda d:d['responses'][0]['json']['results'][0].update(federal_action_obligation=None),
])
def test_unsupported_precision_types_or_missing_values_never_qualify_amounts(tmp_path,change):
    root,scope=make(tmp_path,change=change)
    assert requirement(contract(qualify((root,),scope),'usaspending'),'currency_amount')['status']==Q.INSUFFICIENT.value


def test_negative_and_zero_modifications_remain_supported_observations(tmp_path):
    root,scope=make(tmp_path,'initial_and_modifications');report=qualify((root,),scope)
    for c in report['contracts']:
        assert len(c['actions'])==4
        assert requirement(c,'currency_amount')['status']==Q.QUALIFIED.value
        assert requirement(c,'source_completeness')['status']==Q.INSUFFICIENT.value


@pytest.mark.parametrize('start,end,asof',[('2024-02-30','2024-03-01',None),('2025-01-01','2024-01-01',None),('2024-01-01',None,None),('2024-1-1','2024-12-31',None),(None,None,'today'),(None,None,True)])
def test_invalid_requested_intervals_fail_closed(start,end,asof):
    with pytest.raises(ValueError): HistoricalInterval(start_date=start,end_date=end,as_of_date=asof)


def test_declared_interval_is_not_observed_history_coverage(tmp_path):
    root,scope=make(tmp_path)
    interval=HistoricalInterval(start_date='2024-01-01',end_date='2024-12-31',as_of_date='2025-01-01')
    report=qualify((root,),scope,interval=interval)
    assert all(c['historical_interval']==interval.to_dict() for c in report['contracts'])
    assert all(requirement(c,'source_completeness')['status']==Q.INSUFFICIENT.value for c in report['contracts'])
    assert all(p['historical_interval']==interval.to_dict() for p in report['resolution_plans'])


@pytest.mark.parametrize('status,kind,citations',[(Q.QUALIFIED,K.MISSING,('a',)),(Q.CONFLICTING,K.MISSING,('a',)),(Q.INSUFFICIENT,K.OBSERVED,('a',)),(Q.NOT_EVALUATED,K.OBSERVED,()),(Q.QUALIFIED,K.OBSERVED,()),(Q.CONFLICTING,K.CONTRADICTORY,())])
def test_proof_statuses_require_matching_evidence_kind_and_citations(status,kind,citations):
    with pytest.raises(ValueError): ProofRequirement(dimension='native_identity',status=status,evidence_kind=kind,reasons=('test',),citation_ids=citations)


@pytest.mark.parametrize('mutation',['qualified','missing_dimension','duplicate_dimension','authorize','zero_flag','namespace'])
def test_contradictory_contract_qualification_is_rejected(tmp_path,mutation):
    root,scope=make(tmp_path);raw=deepcopy(contract(qualify((root,),scope))['qualification'])
    if mutation=='qualified':raw['status']=Q.QUALIFIED.value
    if mutation=='missing_dimension':raw['requirements'].pop()
    if mutation=='duplicate_dimension':raw['requirements'][-1]=raw['requirements'][0]
    if mutation=='authorize':raw['financial_comparison_authorized']=True
    if mutation=='zero_flag':raw['financial_comparison_authorized']=0
    if mutation=='namespace':raw['native_context_json']=canonical({'namespace':'samgov'})
    with pytest.raises(ValueError):ContractQualification.from_dict(raw)


@pytest.mark.parametrize('status',[Q.QUALIFIED,Q.INSUFFICIENT,Q.CONFLICTING,Q.NOT_EVALUATED])
def test_aggregate_is_not_an_arithmetic_permission(tmp_path,status):
    root,scope=make(tmp_path);base=ContractQualification.from_dict(contract(qualify((root,),scope))['qualification'])
    kind={Q.QUALIFIED:K.OBSERVED,Q.INSUFFICIENT:K.MISSING,Q.CONFLICTING:K.CONTRADICTORY,Q.NOT_EVALUATED:K.NOT_EVALUATED}[status]
    reqs=tuple(ProofRequirement(dimension=d,status=status,evidence_kind=kind,reasons=('synthetic_model_control_only',),citation_ids=('synthetic:citation',)) for d in DIMENSIONS)
    q=replace(base,requirements=reqs,status=aggregate(reqs))
    assert q.status is status and q.financial_comparison_authorized is False


def test_three_source_namespaces_remain_separate_and_sam_semantics_not_evaluated(tmp_path):
    root,scope=make(tmp_path);sam=tmp_path/'sam';sam_demo(sam)
    before=inventory(sam);report=qualify((root,),scope,sam_captures=(sam,));check(report)
    c=contract(report,'samgov')
    assert json.loads(c['qualification']['native_context_json'])['namespace']=='samgov'
    assert requirement(c,'monetary_semantics')['status']==Q.NOT_EVALUATED.value
    assert requirement(c,'counterpart_coverage')['status']==Q.NOT_EVALUATED.value
    assert all(r['source']=='samgov' for r in c['observed_occurrences'])
    assert inventory(sam)==before


def test_sam_modification_contexts_are_preserved_without_revision_inference(tmp_path):
    rows=[synthetic_row(),synthetic_row()]
    rows[1]['contractId']['modificationNumber']='P00002'
    def send(request,sequence):
        start=request['parameters']['offset']
        return {'status':200,'retrieved_at_utc':'2025-01-01T00:00:00Z','body_complete':True,'error_code':None,'headers':{}},canonical({'awardSummary':rows[start:start+2],'offset':start,'limit':2,'totalRecords':2}).encode()
    root=tmp_path/'sam';sam_collect(root,synthetic_selection('synthetic_row_offset'),live=True,fixture_transport=send,sleep=lambda _:None)
    report=qualify(sam_captures=(root,));check(report);c=contract(report,'samgov')
    assert len(c['actions'])==2
    assert all(a['native_action'] is not None for a in c['actions'])
    assert c['historical_order']['authoritative_revision_order'] is None
    assert c['qualification']['status']!=Q.QUALIFIED.value


def test_resolution_plans_are_typed_source_bound_and_do_not_fabricate_interval(tmp_path):
    root,scope=make(tmp_path,'empty_feed');report=qualify((root,),scope)
    for p in report['resolution_plans']:
        plan=EvidenceResolutionPlan.from_dict({k:v for k,v in p.items() if k!='plan_id'})
        assert plan.plan_id==p['plan_id']
        assert plan.historical_interval.start_date is None
        assert 'Stop without upgrading' in plan.stop_condition
        assert json.loads(plan.native_identifiers_json)['namespace']==plan.source
    altered=deepcopy(report['resolution_plans'][0]);altered['documentation_dependencies']=['https://evil.invalid/']
    with pytest.raises(ValueError):EvidenceResolutionPlan.from_dict({k:v for k,v in altered.items() if k!='plan_id'})


@pytest.mark.parametrize('name',['qualification.json','qualification.md','qualification.html','qualification-commit.json','pilot-plan.json'])
@pytest.mark.parametrize('mutation',['delete','alter'])
def test_tampered_or_truncated_reports_fail_closed(tmp_path,name,mutation):
    root,scope=make(tmp_path);out=tmp_path/'out';write_report(out,qualify((root,),scope))
    f=out/name
    if mutation=='delete':f.unlink()
    else:f.write_bytes(f.read_bytes()+b' ')
    with pytest.raises((ValueError,OSError)):read_report(out)


def resign_report(path,value):
    # Deliberately adversarial, locally forged manifest; never a trust anchor.
    from src.history_qualification_reporting import markdown
    (path/'qualification.json').write_text(canonical(value)+'\n')
    (path/'qualification.md').write_text(markdown(value))
    (path/'qualification.html').write_text(html(value))
    files={n:s.byte_sha256 for n,s in snapshot(path).items() if n!='qualification-commit.json'}
    (path/'qualification-commit.json').write_text(canonical({'schema_version':1,'files':files,'report_sha256':digest(value)})+'\n')


@pytest.mark.parametrize('mutation',['status','missing_plan','extra_plan','missing_citation','plan_procedure','unsupported_schema','authorize','numeric_flag'])
def test_forged_report_projection_or_authorization_is_rejected(tmp_path,mutation):
    root,scope=make(tmp_path);value=qualify((root,),scope);out=tmp_path/'out';write_report(out,value)
    if mutation=='status':value['contracts'][0]['qualification']['status']=Q.QUALIFIED.value
    if mutation=='missing_plan':value['resolution_plans'].pop()
    if mutation=='extra_plan':value['resolution_plans'].append(deepcopy(value['resolution_plans'][0]))
    if mutation=='missing_citation':value['contracts'][0]['observed_occurrences'][0]['id']='unknown-citation'
    if mutation=='plan_procedure':
        p=value['resolution_plans'][0];p['verification_procedure']='Perform unauthorized live collection'
        p['plan_id']=EvidenceResolutionPlan.from_dict({k:v for k,v in p.items() if k!='plan_id'}).plan_id
    if mutation=='unsupported_schema':value['schema_version']=99
    if mutation=='authorize':value['qualification_authorizes_arithmetic']=True
    if mutation=='numeric_flag':value['financial_eligibility_changed']=0
    resign_report(out,value)
    with pytest.raises((ValueError,KeyError)):read_report(out)


def test_modified_history_order_requires_primary_replay_not_local_checksum_trust(tmp_path):
    root,scope=make(tmp_path,'initial_and_modifications');value=qualify((root,),scope)
    out=tmp_path/'out';write_report(out,value)
    # Change an informational derived projection and resign. Local checksums
    # cannot establish authenticity; full primary replay must reject it.
    value['contracts'][0]['historical_order']['occurrence_ids'].reverse()
    resign_report(out,value)
    with pytest.raises(EvidenceError,match='qualification_history_projection_conflict'):
        verify_report(out,(root,),scope)


@pytest.mark.parametrize('which',['body','metadata','symlink','hardlink'])
def test_tampered_primary_capture_rejected_without_repair(tmp_path,which):
    root,scope=make(tmp_path);f=root/'c3_attempt_000000.body'
    if which=='body':f.write_bytes(f.read_bytes()+b' ')
    elif which=='metadata':
        m=root/'c3_attempt_000000.json';value=json.loads(m.read_bytes());value['body_sha256']='0'*64;m.write_text(canonical(value))
    elif which=='symlink':
        other=tmp_path/'other';other.write_bytes(f.read_bytes());f.unlink();f.symlink_to(other)
    else:
        import os
        os.link(f,tmp_path/'linked')
    before={str(p):p.read_bytes() for p in root.iterdir() if p.is_file()}
    with pytest.raises((ValueError,OSError)):qualify((root,),scope)
    assert before=={str(p):p.read_bytes() for p in root.iterdir() if p.is_file()}


def test_source_mutation_during_reconstruction_rejected(tmp_path,monkeypatch):
    import src.history_qualification as module
    root,scope=make(tmp_path);original=module.reconstruct
    def mutated(*a,**kw):
        run=original(*a,**kw);p=root/'c3_attempt_000000.body';p.write_bytes(p.read_bytes()+b' ');return run
    monkeypatch.setattr(module,'reconstruct',mutated)
    with pytest.raises(EvidenceError,match='qualification_source_changed'):
        qualify((root,),scope)


def test_reports_repeat_and_c9_legacy_reports_remain_compatible(tmp_path):
    root,scope=make(tmp_path);old=c9((root,),scope);oldpath=tmp_path/'old';write_c9(oldpath,old)
    oldfiles=inventory(oldpath);before=inventory(root);value=qualify((root,),scope)
    a=tmp_path/'a';b=tmp_path/'b'
    assert write_report(a,value,protected=(root,))==write_report(b,value,protected=(root,))
    assert inventory(a)==inventory(b)
    assert verify_report(a,(root,),scope)==read_report(a)==value
    assert read_c9(oldpath)==old and inventory(oldpath)==oldfiles and inventory(root)==before
    with pytest.raises(OSError):write_report(a,value)
    with pytest.raises(EvidenceError):write_report(root/'nested',value,protected=(root,))


def test_cli_create_verify_and_safe_error_recovery(tmp_path,capsys):
    root,scope=make(tmp_path);s=tmp_path/'scope.json';s.write_text(canonical(scope.to_dict()))
    args=['--collection',str(root),'--scope',str(s),'--history-start','2024-01-01','--history-end','2024-12-31','--as-of','2025-01-01']
    assert main(args+['--output',str(tmp_path/'out')])==0
    assert main(args+['--verify-report',str(tmp_path/'out')])==0
    assert main(args[:-2]+['--verify-report',str(tmp_path/'out')])==2 # Different requested as-of scope.
    assert main(['--collection','/private/secret','--output',str(tmp_path/'bad')])==2
    assert '/private/secret' not in capsys.readouterr().out
    assert not (tmp_path/'bad').exists()


def test_static_html_escapes_untrusted_native_text_and_controls(tmp_path):
    root,scope=make(tmp_path);value=qualify((root,),scope)
    value['untrusted']='<script>alert(1)</script>```\x1b[31m\u202e'
    output=html(value)
    assert '<script>' not in output and '&lt;script&gt;' in output
    assert '\x1b' not in output and '\u202e' not in output
    assert "default-src 'none'" in output


@pytest.mark.parametrize('raw',[b'{',b'{"schema_version":1,"schema_version":2}',b'{"x":NaN}'])
def test_malformed_json_is_rejected(tmp_path,raw):
    root,scope=make(tmp_path);out=tmp_path/'out';write_report(out,qualify((root,),scope))
    (out/'qualification.json').write_bytes(raw)
    with pytest.raises(ValueError):read_report(out)


@pytest.mark.parametrize('attribute,status',[(' currency="EUR"',Q.CONFLICTING),(' unknown="x"',Q.INSUFFICIENT)])
def test_explicit_currency_conflict_is_separate_from_unsupported_metadata(tmp_path,attribute,status):
    def change(data):data['responses'][-1]['text']=data['responses'][-1]['text'].replace('<f:obligatedAmount>100.00','<f:obligatedAmount'+attribute+'>100.00',1)
    root,scope=make(tmp_path,change=change)
    assert requirement(contract(qualify((root,),scope)),'currency_amount')['status']==status.value


def test_sam_counter_contradiction_is_not_mislabeled_merely_missing(tmp_path):
    rows=[]
    for mod in ('P00001','P00002','P00003'):
        row=synthetic_row();row['contractId']['modificationNumber']=mod;rows.append(row)
    def send(request,sequence):
        offset=request['parameters']['offset']
        return {'status':200,'retrieved_at_utc':'2025-01-01T00:00:00Z','body_complete':True,'error_code':None,'headers':{}},canonical({'awardSummary':rows[offset:offset+2],'offset':offset,'limit':2,'totalRecords':3 if offset==0 else 4}).encode()
    root=tmp_path/'sam';sam_collect(root,synthetic_selection('synthetic_row_offset'),live=True,fixture_transport=send,sleep=lambda _:None)
    report=qualify(sam_captures=(root,));check(report)
    req=requirement(contract(report,'samgov'),'source_completeness')
    assert req['status']==Q.CONFLICTING.value
    assert 'changing_totalRecords' in req['reasons']
    assert report['qualification_authorizes_arithmetic'] is False


@pytest.mark.parametrize('mutation',['triage','action_groups','history_order','limitation'])
def test_derived_summaries_are_recomputed_before_readback(tmp_path,mutation):
    root,scope=make(tmp_path,'initial_and_modifications');value=qualify((root,),scope);out=tmp_path/'out';write_report(out,value)
    if mutation=='triage':value['gap_triage']=[]
    if mutation=='action_groups':value['contracts'][0]['actions']=[]
    if mutation=='history_order':value['contracts'][0]['historical_order']['missing_modifications_inferred']=True
    if mutation=='limitation':value['contracts'][0]['limitations']=[]
    resign_report(out,value)
    with pytest.raises(EvidenceError):read_report(out)


@pytest.mark.parametrize('collections,sam',[((),()),(tuple(range(9)),()),((),tuple(range(4)))])
def test_bounded_nonempty_inputs(collections,sam):
    with pytest.raises(EvidenceError):qualify(collections,sam_captures=sam)


def test_unavailable_sam_capture_yields_no_positive_contracts(tmp_path):
    root=tmp_path/'unavailable';root.mkdir()
    value=qualify(sam_captures=(root,));check(value)
    assert not value['contracts'] and not value['resolution_plans']
    assert value['sam_capture_assessments'][0]['state']=='incomplete_or_interrupted_capture'
    assert value['sam_capture_assessments'][0]['blockers']


def test_resolution_plan_preserves_observed_action_ids_without_inventing_missing_modifications(tmp_path):
    root,scope=make(tmp_path,'missing_intermediate');report=qualify((root,),scope);check(report)
    for plan in report['resolution_plans']:
        actions=json.loads(plan['observed_action_identifiers_json'])
        mods={a['native_action'][0] for a in actions if a['native_action'] is not None}
        assert 'P00001' not in mods
        assert all(isinstance(a['native_action'][0],str) for a in actions if a['native_action'] is not None)
    assert all(not c['historical_order']['missing_modifications_inferred'] for c in report['contracts'])


def test_preexisting_protocols_and_documentation_are_byte_identical():
    import hashlib
    root=Path(__file__).resolve().parents[1]
    value=json.loads((root/'docs/history-qualification-protocol-v1.json').read_bytes())
    assert value['starting_main']=='226536e8f2fa4b8adf877c4e0bb43acde5330483'
    assert len(value['frozen_files'])==48
    for name,sha in value['frozen_files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==sha


@pytest.mark.parametrize('bad',[{},False,0,[]])
def test_falsey_untyped_intervals_are_not_silently_defaulted(tmp_path,bad):
    root,scope=make(tmp_path)
    with pytest.raises(EvidenceError,match='typed_historical_interval_required'):qualify((root,),scope,interval=bad)


def test_explicit_conflicting_award_id_cannot_qualify_as_counterpart(tmp_path):
    root,scope=make(tmp_path,change=lambda data:data['responses'][0]['json']['results'][0].update(award_id='CONT_AWD_WRONG_SELECTION'))
    value=qualify((root,),scope);check(value)
    assert requirement(contract(value,'usaspending'),'native_identity')['status']==Q.NOT_EVALUATED.value
    assert requirement(contract(value,'fpds'),'counterpart_coverage')['status']==Q.INSUFFICIENT.value


def test_same_action_signed_date_variants_are_conflicting_but_no_revision_winner(tmp_path):
    a,scope=make(tmp_path/'a',stamp='2025-01-01T00:00:00Z')
    def change(data):data['responses'][-1]['text']=data['responses'][-1]['text'].replace('2024-10-01','2024-10-02')
    b,_=make(tmp_path/'b',stamp='2025-01-02T00:00:00Z',change=change)
    report=qualify((a,b),scope);check(report);c=contract(report)
    assert requirement(c,'as_of_alignment')['status']==Q.CONFLICTING.value
    assert requirement(c,'currency_amount')['status']==Q.QUALIFIED.value
    assert c['historical_order']['authoritative_revision_order'] is None


def test_malformed_signed_date_is_missing_proof_not_a_conflicting_value(tmp_path):
    root,scope=make(tmp_path,'malformed_date');c=contract(qualify((root,),scope),'usaspending')
    req=requirement(c,'as_of_alignment')
    assert req['status']==Q.INSUFFICIENT.value
    assert 'signed_action_date_missing_or_unsupported_no_effective_date_substitution' in req['reasons']


def test_query_candidates_for_different_parent_are_not_source_contradictions(tmp_path):
    def different(data):data['responses'][-1]['text']=data['responses'][-1]['text'].replace('<f:PIID>SYNTH-PARENT</f:PIID>','<f:PIID>OTHER-PARENT</f:PIID>')
    root,scope=make(tmp_path,change=different,kind='C');value=qualify((root,),scope);check(value);c=contract(value)
    assert c['qualification']['status']==Q.NOT_EVALUATED.value
    assert c['selection_status']=='outside_requested_context_not_evaluated'
    assert not any(t['category']=='conflicting_source_records' for t in value['gap_triage'])


def test_amount_variants_do_not_manufacture_parent_conflicts(tmp_path):
    root,scope=make(tmp_path,'contradictory_observations',kind='C');value=qualify((root,),scope);check(value)
    c=contract(value,'usaspending')
    assert requirement(c,'currency_amount')['status']==Q.CONFLICTING.value
    assert requirement(c,'parent_identity')['status']==Q.INSUFFICIENT.value
    assert requirement(c,'parent_identity')['reasons']==['parent_award_primary_record_not_observed']


def test_internal_identifier_modification_contradiction_is_real_conflicting_evidence(tmp_path):
    root,scope=make(tmp_path,change=lambda data:data['responses'][0]['json']['results'][0].update(modification_number='P99999'))
    value=qualify((root,),scope);check(value)
    req=requirement(contract(value,'usaspending'),'native_identity')
    assert req['status']==Q.CONFLICTING.value
    assert req['evidence_kind']==K.CONTRADICTORY.value
