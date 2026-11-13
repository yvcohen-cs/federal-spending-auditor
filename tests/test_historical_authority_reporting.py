"""C19 source/package boundaries with an explicitly stubbed C18 verifier.

Existing C14-C18 primary-package tests remain unchanged. The preserved real C19
completion evaluation separately exercises the entire chain without this stub.
"""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import hashlib,json,shutil
import pytest
from src.evidence_io import canonical,digest
from src.correction_reporting import report as c14_report
from src.parent_authority_acquisition import collect
from src.historical_authority_reporting import report,write_report,verify_report,projections,fallback,main
from src.evidence_package import build_package,verify_package
from tests.test_historical_source_authority import original_case,historical_case,documents
from tests.test_parent_coverage import rewrite_zip
from tests.test_evidence_acquisition import inventory


def transcript(a,data):
    tx=deepcopy(data);tx['responses']=[r for r in tx['responses'] if r['source']=='usaspending']
    tx['responses'][0]['json']['page_metadata'].update(previous=None,next=None,hasPrevious=False)
    pid='SYNTH-PARENT-OPAQUE-'+a.piid
    child={'generated_unique_award_id':a.generated_id,'piid':a.piid,'category':'contract','type':'C',
        'parent_award':{'generated_unique_award_id':pid,'piid':a.parent_piid,'sub_agency_id':a.parent_agency_id}}
    parent={'generated_unique_award_id':pid,'piid':a.parent_piid,'category':'idv','type':'IDV_B','parent_award':None}
    row={'id':f'CONT_TX_{a.parent_agency_id}_-NONE-_{a.parent_piid}_0_-NONE-_-NONE-',
         'type':'IDV_B','action_date':'2020-01-01','modification_number':'0','federal_action_obligation':0,'description':'Authored synthetic parent'}
    return {'child':{'details':[{'source':'usaspending','json':child},{'source':'usaspending','json':parent}],
                     'transactions':tx},'parent':{'schema_version':1,'responses':[{'source':'usaspending',
        'json':{'results':[row],'page_metadata':{'page':1,'previous':None,'next':None,'hasPrevious':False,'hasNext':False}}}]}}


@pytest.fixture
def context(tmp_path,monkeypatch):
    base,h=historical_case(tmp_path/'base-original');old=c14_report([base]);original=old['cases'][0]
    ids=[p['original_plan_id'] for p in original['original_requirement_impacts']]
    prior=next(p['original_plan_id'] for p in original['original_requirement_impacts']
               if p['dimension']=='parent_identity' and p['native_context']['namespace']=='usaspending')
    model={'baseline_original_plan_ids':ids,'previously_resolved_real_source_requirements':[],
        'newly_resolved_real_source_requirements':[],'previously_resolved_synthetic_requirements':[prior],
        'newly_resolved_synthetic_requirements':[],'baseline':{'historical_parent_assessment':h}}
    stub=tmp_path/'C18-verifier-stub';(stub/'report').mkdir(parents=True)
    shutil.copytree(base['collections'][0],stub/'original')
    (stub/'cases.json').write_text(canonical({'schema_version':1,'cases':[{**base,'collections':['original']}],
        'baseline_package':'unused-prior.zip','selected_action':{},'sam_action_captures':[]}))
    (stub/'report/action-authority.json').write_text(canonical(model))
    receipt={'profile':'synthetic','archive_sha256':digest('authored C18 boundary'),
             'report_sha256':digest(model),'verified_case_bindings':[
                 {'original_case_sha256':original['original_case_sha256'],'parent_inventory_sha256':None}]}
    archive=tmp_path/'baseline-package.zip';archive.write_bytes(b'EXPLICIT SYNTHETIC VERIFIER STUB')
    @contextmanager
    def verified(path,*,expected_phase):
        assert expected_phase=='C18'
        if Path(path).read_bytes()!=archive.read_bytes():raise ValueError('baseline stub bytes changed')
        yield stub,deepcopy(receipt)
    monkeypatch.setattr('src.historical_authority_reporting.verified_directory',verified)
    cases=[base];transcripts=[]
    for i in (1,2):
        case,a,data=original_case(tmp_path/('original-'+str(i)),suffix=str(i))
        case.update(c19_parent_capture=str(tmp_path/('child-'+str(i))),c19_parent_history=str(tmp_path/('parent-'+str(i))))
        cases.append(case);transcripts.append(transcript(a,data))
    docs=documents(tmp_path/'documents')
    return {'root':tmp_path,'cases':cases,'transcripts':transcripts,'baseline':archive,'documents':docs,'receipt':receipt}


def captured(ctx,*,count=1,change=None):
    for i in range(count):
        t=deepcopy(ctx['transcripts'][i])
        if change:change(t)
        collect(ctx['root']/('journal-'+str(i)),fallback(ctx['cases'][i+1]),synthetic=t)
    return ctx['cases'][:count+1]


def kwargs(ctx):return {'baseline_package':ctx['baseline'],'source_documents':ctx['documents']}


def test_two_original_resolutions_conserve_ids_and_preserve_dimensions(context):
    cases=captured(context,count=2);r=report(cases,**kwargs(context))
    assert len(r['previously_resolved_synthetic_requirements'])==1 and len(r['newly_resolved_synthetic_requirements'])==2
    assert not r['newly_resolved_real_source_requirements'] and r['qualification_scope']=='included_cases_only'
    assert set(r['baseline_original_plan_ids'])==set(r['remaining_original_plan_ids']+r['previously_resolved_synthetic_requirements']+r['newly_resolved_synthetic_requirements'])
    assert not r['historical_parent_applicability_intervals_established'] and not r['financial_comparison_authorized']
    assert all(not c['financial_preflight']['totals_or_deltas_computed'] for c in r['cases'] if c['financial_preflight'])
    assert r['source_documentation_evidence_class']=='SYNTHETIC_DOCUMENT_FIXTURE'


@pytest.mark.parametrize('stage,status',[('child',401),('child',403),('child',429),('child',500),('parent',403),('parent',503)])
def test_partial_or_credential_failures_do_not_become_absence(context,stage,status):
    def change(t):
        if stage=='child':t['child']['details'][0]['status']=status
        else:t['parent']['responses'][0]['status']=status
    r=report(captured(context,change=change),**kwargs(context))
    assert not r['newly_resolved_synthetic_requirements'] and not r['financial_comparison_authorized']


def test_incomplete_child_pagination_stops_parent_access(context):
    cases=captured(context,change=lambda t:t['child']['transactions']['responses'][0]['json']['page_metadata'].update(hasNext=True,next=2))
    assert not Path(cases[-1]['c19_parent_history']).exists()
    assert not report(cases,**kwargs(context))['newly_resolved_synthetic_requirements']


@pytest.mark.parametrize('field,bad',[('piid','WRONG'),('sub_agency_id','0000'),('generated_unique_award_id','../parent')])
def test_wrong_native_parent_references_cannot_resolve(context,field,bad):
    cases=captured(context,change=lambda t:t['child']['details'][0]['json']['parent_award'].__setitem__(field,bad))
    assert not report(cases,**kwargs(context))['newly_resolved_synthetic_requirements']


def test_duplicate_cases_and_rebinding_prior_sources_reject(context):
    cases=captured(context)
    with pytest.raises(ValueError):report([*cases,cases[-1]],**kwargs(context))
    with pytest.raises(ValueError):fallback({**cases[-1],'action_parent_capture':'preserved'})


def test_changed_baseline_profile_rejects(context):
    cases=captured(context);context['receipt']['profile']='live'
    with pytest.raises(ValueError):report(cases,**kwargs(context))


def test_preserved_parent_inventory_binding_cannot_change(context):
    cases=captured(context);context['receipt']['verified_case_bindings'][0]['parent_inventory_sha256']='a'*64
    with pytest.raises(ValueError):report(cases,**kwargs(context))


def test_unreplayed_extra_baseline_capture_cannot_be_smuggled(context):
    cases=captured(context);cases[0]['action_parent_capture']=str(context['root']/'unrelated-capture')
    with pytest.raises(ValueError):report(cases,**kwargs(context))


@pytest.mark.parametrize('member',['detail-000.json','detail-001.body','experiment-commit.json'])
def test_missing_capture_history_is_rejected_not_repaired(context,member):
    cases=captured(context);root=Path(cases[-1]['c19_parent_capture']);(root/member).unlink()
    before=inventory(root)
    with pytest.raises(ValueError):report(cases,**kwargs(context))
    assert inventory(root)==before


def test_stable_compact_reports_html_and_resigned_summary_reject(context):
    cases=captured(context);a,b=context['root']/'a',context['root']/'b'
    assert write_report(a,cases,**kwargs(context))==write_report(b,cases,**kwargs(context))
    assert {p.name:p.read_bytes() for p in a.iterdir()}=={p.name:p.read_bytes() for p in b.iterdir()}
    r=verify_report(a,cases,**kwargs(context));assert 'baseline' not in r
    r['untrusted']='<script>alert(1)</script>```';raw=projections(r)
    assert b'<script>' not in raw['historical-authority.html'] and b'&lt;script&gt;' in raw['historical-authority.html']
    r['financial_comparison_authorized']=True
    for n,data in projections(r).items():(a/n).write_bytes(data)
    commit=json.loads((a/'historical-authority-commit.json').read_text());commit['report_sha256']=digest(r)
    commit['files']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in a.iterdir() if p.name!='historical-authority-commit.json'}
    (a/'historical-authority-commit.json').write_text(canonical(commit)+'\n')
    with pytest.raises(ValueError):verify_report(a,cases,**kwargs(context))


def test_C19_outer_package_replays_primaries_and_rejects_resigned_authority(context):
    cases=captured(context,count=2);stage=context['root']/'stage';stage.mkdir();relative=[];absolute=[]
    for i,c in enumerate(cases):
        rel,ab=deepcopy(c),deepcopy(c)
        for key in ('collections','c19_parent_capture','c19_parent_history'):
            if not c.get(key):continue
            many=key=='collections';values=c[key] if many else [c[key]];names=[f'case-{i}-{key}-{j}' for j in range(len(values))]
            for value,name in zip(values,names):shutil.copytree(value,stage/name)
            rel[key]=names if many else names[0];pp=[str(stage/n) for n in names];ab[key]=pp if many else pp[0]
        relative.append(rel);absolute.append(ab)
    shutil.copyfile(context['baseline'],stage/'baseline-package.zip');shutil.copytree(context['documents'],stage/'official-documents')
    (stage/'cases.json').write_text(canonical({'schema_version':1,'cases':relative,'baseline_package':'baseline-package.zip'}))
    write_report(stage/'report',absolute,baseline_package=stage/'baseline-package.zip',source_documents=stage/'official-documents')
    archive=context['root']/'c19.zip';receipt=build_package(stage,archive,phase='C19');assert receipt==verify_package(archive,expected_phase='C19')
    assert not receipt['resolved_real_source_plan_ids']
    for phase in ('C14','C15','C16','C17','C18'):
        with pytest.raises(ValueError):verify_package(archive,expected_phase=phase)
    def forge(files):
        value=json.loads(files['report/historical-authority.json']);value['financial_comparison_authorized']=True
        for n,raw in projections(value).items():files['report/'+n]=raw
        commit=json.loads(files['report/historical-authority-commit.json']);commit['report_sha256']=digest(value)
        commit['files']={n[7:]:hashlib.sha256(raw).hexdigest() for n,raw in files.items() if n.startswith('report/') and n!='report/historical-authority-commit.json'}
        files['report/historical-authority-commit.json']=(canonical(commit)+'\n').encode()
        index=json.loads(files['evidence-index.json']);index['report_sha256']=digest(value);files['evidence-index.json']=(canonical(index)+'\n').encode()
    bad=context['root']/'forged.zip';rewrite_zip(archive,bad,forge,resign=True)
    with pytest.raises(ValueError):verify_package(bad)


@pytest.mark.parametrize('raw',['[null]','[1]','{}','[','[]'])
def test_malformed_cli_inputs_reject_before_source_access(tmp_path,raw,capsys):
    path=tmp_path/'cases.json';path.write_text(raw)
    assert main(['--cases',str(path),'--baseline-package','missing.zip','--source-documents','missing-docs','--plan-fallback'])==2
    assert json.loads(capsys.readouterr().out)['error_code']=='historical_authority_failed_preserve_evidence'


def test_frozen_protocols_and_inventories_remain_unchanged():
    p=json.loads(Path('docs/historical-source-authority-protocol-v1.json').read_text());assert len(p['frozen_files'])==72
    for n,h in p['frozen_files'].items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==h
