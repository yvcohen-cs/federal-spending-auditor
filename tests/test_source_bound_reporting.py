"""C20 outer primary replay; only the C19 verifier boundary is stubbed here.

The real completion evaluation independently exercises C14-C20 without stubs.
All source rows and source-document pins in this file are authored fixtures.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import hashlib,json,shutil
import pytest
from src.evidence_io import canonical,digest
from src.correction_reporting import report as c14_report
from src.historical_source_authority import assess
from src.source_bound_reporting import report,write_report,verify_report,projections,fallback,main
from src.parent_authority_acquisition import collect
from src.evidence_package import build_package,verify_package,_recipe
from tests.test_historical_source_authority import original_case,historical_case
from tests.test_historical_authority_reporting import transcript
from tests.test_source_reference_semantics import documents
from tests.test_evidence_acquisition import inventory
from tests.test_parent_coverage import rewrite_zip


@pytest.fixture
def context(tmp_path,monkeypatch):
    base,h=historical_case(tmp_path/'base-original');old=c14_report([base])['cases'][0]
    ids=[p['original_plan_id'] for p in old['original_requirement_impacts']]
    prior=next(p['original_plan_id'] for p in old['original_requirement_impacts']
               if p['dimension']=='parent_identity' and p['native_context']['namespace']=='usaspending')
    model={'baseline_original_plan_ids':ids,'previously_resolved_real_source_requirements':[],
        'newly_resolved_real_source_requirements':[],'previously_resolved_synthetic_requirements':[prior],
        'newly_resolved_synthetic_requirements':[],'historical_authority_assessment':assess(h,profile='synthetic')}
    root=tmp_path/'C19-verifier-stub';(root/'report').mkdir(parents=True)
    shutil.copytree(base['collections'][0],root/'original')
    (root/'cases.json').write_text(canonical({'schema_version':1,'cases':[{**base,'collections':['original']}],
                                           'baseline_package':'unused-prior.zip'}))
    (root/'report/historical-authority.json').write_text(canonical(model))
    receipt={'profile':'synthetic','archive_sha256':digest('authored C19 boundary'),'report_sha256':digest(model),
        'verified_case_bindings':[{'original_case_sha256':old['original_case_sha256'],'parent_inventory_sha256':None}]}
    archive=tmp_path/'baseline-package.zip';archive.write_bytes(b'EXPLICIT_SYNTHETIC_C19_VERIFIER_STUB')
    @contextmanager
    def verified(path,*,expected_phase):
        assert expected_phase=='C19'
        if Path(path).read_bytes()!=b'EXPLICIT_SYNTHETIC_C19_VERIFIER_STUB':raise ValueError('baseline stub bytes changed')
        yield root,deepcopy(receipt)
    monkeypatch.setattr('src.source_bound_reporting.verified_directory',verified)
    cases=[base];transcripts=[]
    for i in (1,2):
        case,a,data=original_case(tmp_path/('original-'+str(i)),suffix='C20-'+str(i))
        case.update(c20_parent_capture=str(tmp_path/('child-'+str(i))),c20_parent_history=str(tmp_path/('parent-'+str(i))))
        cases.append(case);transcripts.append(transcript(a,data))
    return {'root':tmp_path,'baseline_root':root,'cases':cases,'transcripts':transcripts,'baseline':archive,
            'documents':documents(tmp_path/'documents',monkeypatch),'receipt':receipt}


def captured(ctx,*,count=1,change=None):
    for i in range(count):
        t=deepcopy(ctx['transcripts'][i])
        if change:change(t)
        collect(ctx['root']/('journal-'+str(i)),fallback(ctx['cases'][i+1]),synthetic=t)
    return ctx['cases'][:count+1]


def kwargs(ctx):return {'baseline_package':ctx['baseline'],'source_documents':ctx['documents']}


def test_original_resolutions_partition_backlog_without_history_or_financial_promotion(context):
    r=report(captured(context,count=2),**kwargs(context));t=r['baseline_dependency_assessment']
    assert len(r['previously_resolved_synthetic_requirements'])==1 and len(r['newly_resolved_synthetic_requirements'])==2
    assert not r['newly_resolved_real_source_requirements'] and r['qualification_scope']=='included_cases_only'
    assert t['baseline_unresolved_count']-t['current_remaining_count']==2
    assert sum(t['exclusive_group_counts'].values())==t['baseline_unresolved_count']
    assert set(r['baseline_original_plan_ids'])==set(r['remaining_original_plan_ids']+r['previously_resolved_synthetic_requirements']+r['newly_resolved_synthetic_requirements'])
    assert not r['historical_parent_applicability_intervals_established'] and not r['financial_comparison_authorized']
    assert all(c['financial_preflight']['totals_or_deltas_computed']==0 for c in r['cases'] if c['financial_preflight'])
    assert r['source_documentation_evidence_class']=='SYNTHETIC_DOCUMENT_FIXTURE'
    assert all(not c['source_current_access_verified'] for c in t['candidate_plans'])


@pytest.mark.parametrize('stage,status',[('child',401),('child',403),('child',429),('child',500),('parent',403),('parent',503)])
def test_partial_source_or_authorization_failure_never_means_absence(context,stage,status):
    def change(t):
        if stage=='child':t['child']['details'][0]['status']=status
        else:t['parent']['responses'][0]['status']=status
    r=report(captured(context,change=change),**kwargs(context))
    assert not r['newly_resolved_synthetic_requirements'] and not r['financial_comparison_authorized']
    assert r['current_phase_access_observations'][0]['state']=='FAILED_OR_INCONCLUSIVE_NO_ABSENCE_CLAIM'


def test_incomplete_child_chain_stops_parent_requests(context):
    cases=captured(context,change=lambda t:t['child']['transactions']['responses'][0]['json']['page_metadata'].update(hasNext=True,next=2))
    assert not Path(cases[-1]['c20_parent_history']).exists()
    r=report(cases,**kwargs(context));assert not r['newly_resolved_synthetic_requirements']


def test_nonterminal_parent_proves_only_existence_not_history(context):
    def change(t):
        response=t['parent']['responses'][0];response['json']['page_metadata'].update(hasNext=True,next=2)
        second=deepcopy(response);second['json']['page_metadata'].update(page=2,previous=1,hasPrevious=True,next=3)
        row=second['json']['results'][0];row['id']=row['id'].replace('_0_-NONE-_-NONE-','_1_-NONE-_-NONE-');row['modification_number']='1'
        t['parent']['responses'].append(second)
    r=report(captured(context,change=change),**kwargs(context));parent=r['cases'][-1]['parent_probe']
    assert parent['pagination']['transaction_history_complete']=='unknown'
    assert 'nonterminal_observed_chain' in parent['pagination']['issues']
    assert not r['financial_comparison_authorized'] and not r['historical_parent_applicability_intervals_established']
    assert all(p['resolved_claim_scope']=='source_local_parent_award_identity_and_primary_record_existence_only'
               for p in r['cases'][-1]['resolved_original_impacts'])


@pytest.mark.parametrize('field,bad',[('piid','WRONG'),('sub_agency_id','0000'),('generated_unique_award_id','../parent')])
def test_wrong_native_parent_cannot_resolve_requirement(context,field,bad):
    cases=captured(context,change=lambda t:t['child']['details'][0]['json']['parent_award'].__setitem__(field,bad))
    assert not report(cases,**kwargs(context))['newly_resolved_synthetic_requirements']


def test_duplicate_cases_and_prior_capture_rebinding_reject(context):
    cases=captured(context)
    with pytest.raises(ValueError):report([*cases,cases[-1]],**kwargs(context))
    for key in ('c19_parent_capture','new_parent_capture','action_parent_capture'):
        with pytest.raises(ValueError):fallback({**cases[-1],key:'preserved-capture'})


def test_changed_baseline_profile_or_inventory_binding_rejects(context):
    cases=captured(context);context['receipt']['profile']='live'
    with pytest.raises(ValueError):report(cases,**kwargs(context))
    context['receipt']['profile']='synthetic';context['receipt']['verified_case_bindings'][0]['parent_inventory_sha256']='a'*64
    with pytest.raises(ValueError):report(cases,**kwargs(context))


def test_extra_preserved_capture_cannot_be_smuggled(context):
    cases=captured(context);cases[0]['c19_parent_capture']=str(context['root']/'unrelated')
    with pytest.raises(ValueError):report(cases,**kwargs(context))


def test_changed_frozen_baseline_copy_rejects_even_if_unused_for_field_parsing(context):
    cases=captured(context)
    (context['baseline_root']/'original/c3_summary.json').write_text('{}')
    with pytest.raises(ValueError,match='inventory_changed'):report(cases,**kwargs(context))


def test_offline_reporting_does_not_initialize_network_transport(context,monkeypatch):
    cases=captured(context)
    monkeypatch.setattr('src.collection_sources.HTTPTransport',lambda *_:pytest.fail('network initialized'))
    monkeypatch.setattr('requests.sessions.Session.request',lambda *_a,**_k:pytest.fail('HTTP request attempted'))
    assert report(cases,**kwargs(context))['financial_comparison_authorized'] is False


@pytest.mark.parametrize('member',['detail-000.json','detail-001.body','experiment-commit.json'])
def test_missing_capture_history_rejects_without_repair(context,member):
    cases=captured(context);root=Path(cases[-1]['c20_parent_capture']);(root/member).unlink();before=inventory(root)
    with pytest.raises(ValueError):report(cases,**kwargs(context))
    assert inventory(root)==before


def test_deterministic_reports_escape_HTML_and_reject_forged_triage(context):
    cases=captured(context);a,b=context['root']/'a',context['root']/'b'
    assert write_report(a,cases,**kwargs(context))==write_report(b,cases,**kwargs(context))
    assert inventory(a)==inventory(b)
    r=verify_report(a,cases,**kwargs(context));r['untrusted']='<script>alert(1)</script>```'
    assert b'<script>' not in projections(r)['source-bound.html'] and b'&lt;script&gt;' in projections(r)['source-bound.html']
    r['baseline_dependency_assessment']['requirements'][0]['group']='financial_semantics'
    r['financial_comparison_authorized']=True
    for n,raw in projections(r).items():(a/n).write_bytes(raw)
    commit=json.loads((a/'source-bound-commit.json').read_text());commit['report_sha256']=digest(r)
    commit['files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir() if p.name!='source-bound-commit.json'}
    (a/'source-bound-commit.json').write_text(canonical(commit)+'\n')
    with pytest.raises(ValueError):verify_report(a,cases,**kwargs(context))


def test_C20_outer_package_primary_replay_rejects_resigned_false_authority(context):
    cases=captured(context,count=2);stage=context['root']/'stage';stage.mkdir();rel=[];absolute=[]
    for i,c in enumerate(cases):
        rr,aa=deepcopy(c),deepcopy(c)
        for key in ('collections','c20_parent_capture','c20_parent_history'):
            if not c.get(key):continue
            many=key=='collections';values=c[key] if many else [c[key]];names=[f'case-{i}-{key}-{j}' for j in range(len(values))]
            for value,name in zip(values,names):shutil.copytree(value,stage/name)
            rr[key]=names if many else names[0];pp=[str(stage/n) for n in names];aa[key]=pp if many else pp[0]
        rel.append(rr);absolute.append(aa)
    shutil.copyfile(context['baseline'],stage/'baseline-package.zip');shutil.copytree(context['documents'],stage/'official-documents')
    (stage/'cases.json').write_text(canonical({'schema_version':1,'cases':rel,'baseline_package':'baseline-package.zip'}))
    write_report(stage/'report',absolute,baseline_package=stage/'baseline-package.zip',source_documents=stage/'official-documents')
    archive=context['root']/'c20.zip';receipt=build_package(stage,archive,phase='C20')
    assert receipt==verify_package(archive,expected_phase='C20') and not receipt['resolved_real_source_plan_ids']
    for phase in ('C14','C15','C16','C17','C18','C19'):
        with pytest.raises(ValueError):verify_package(archive,expected_phase=phase)
    def forge(files):
        r=json.loads(files['report/source-bound.json']);r['historical_parent_applicability_intervals_established']=1;r['financial_comparison_authorized']=True
        for n,raw in projections(r).items():files['report/'+n]=raw
        commit=json.loads(files['report/source-bound-commit.json']);commit['report_sha256']=digest(r)
        commit['files']={n[7:]:hashlib.sha256(raw).hexdigest() for n,raw in files.items() if n.startswith('report/') and n!='report/source-bound-commit.json'}
        files['report/source-bound-commit.json']=(canonical(commit)+'\n').encode()
        index=json.loads(files['evidence-index.json']);index['report_sha256']=digest(r);files['evidence-index.json']=(canonical(index)+'\n').encode()
    bad=context['root']/'forged.zip';rewrite_zip(archive,bad,forge,resign=True)
    with pytest.raises(ValueError):verify_package(bad)


@pytest.mark.parametrize('phase',['C14','C15','C16','C17','C18','C19'])
def test_new_capture_fields_require_C20_phase(tmp_path,phase):
    cases=[{'collections':[],'c20_parent_capture':'unreplayed-capture'}]
    recipe={'schema_version':1,'cases':cases,'baseline_package':'prior.zip'}
    if phase in ('C17','C18'):recipe['selected_action']={}
    if phase=='C18':recipe['sam_action_captures']=[]
    (tmp_path/'cases.json').write_text(canonical(cases if phase=='C14' else recipe))
    with pytest.raises(ValueError,match='explicit_C20_phase'):_recipe(tmp_path,phase)


@pytest.mark.parametrize('raw',['[null]','[1]','{}','[','[]'])
def test_malformed_cli_input_rejects_before_source_access(tmp_path,raw,capsys):
    path=tmp_path/'cases.json';path.write_text(raw)
    assert main(['--cases',str(path),'--baseline-package','missing.zip','--source-documents','missing-docs','--output',str(tmp_path/'out')])==2
    assert json.loads(capsys.readouterr().out)['error_code']=='source_bound_evidence_failed_preserve_inputs'


def test_frozen_protocol_and_source_inventory_hashes_remain_identical():
    p=json.loads(Path('docs/source-bound-evidence-protocol-v1.json').read_text());assert len(p['frozen_files'])==75
    for n,h in p['frozen_files'].items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==h
