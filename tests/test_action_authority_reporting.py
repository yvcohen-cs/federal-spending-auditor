"""C18 offline integration and adversarial primary-package checks."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib,json,shutil
import pytest
from src.evidence_io import canonical,digest
from src.action_authority_reporting import report,write_report,verify_report,projections,main,fallback
from src.parent_authority_acquisition import collect,plan
from src.evidence_package import build_package,verify_package
from src.history_demo import fixture,collect_fixture
from src.scope_models import ScopeRequest
from tests.test_parent_modification_authority import context as prior_context,captured as prior_captured,staging as prior_staging
from tests.test_evidence_acquisition import inventory
from tests.test_parent_coverage import rewrite_zip


@pytest.fixture(scope='module')
def context(tmp_path_factory):
    tmp=tmp_path_factory.mktemp('action-authority')
    ctx=prior_context.__wrapped__(tmp_path_factory)
    cases=prior_captured(tmp/'prior-source',ctx)
    stage=tmp/'prior-stage';prior_staging(stage,cases,ctx[0],phase='C17',selection=ctx[4])
    archive=tmp/'c17.zip';build_package(stage,archive,phase='C17')
    a,t=fixture('equal_control');oldchild,oldparent=a.piid,a.parent_piid
    a=replace(a,piid='SYNTH-FOURTH-00001',generated_id='SYNTH-SOURCE-NATIVE-FOURTH',parent_piid='SYNTH-PARENT-FOURTH')
    for r in t['responses']:
        if r['source']=='usaspending':
            for row in r['json']['results']:row['id']=row['id'].replace(oldchild,a.piid).replace(oldparent,a.parent_piid)
        else:r['text']=r['text'].replace(oldchild,a.piid).replace(oldparent,a.parent_piid)
    root=tmp/'original';collect_fixture(root,a,t)
    scope=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    target={'collections':[str(root)],'scope':scope.to_dict()}
    scenario=deepcopy(ctx[3])
    child=scenario['child']['details'][0]['json'];parent=scenario['child']['details'][1]['json']
    child.update(generated_unique_award_id=a.generated_id,piid=a.piid)
    child['parent_award'].update(generated_unique_award_id='SYNTH-SOURCE-PARENT-FOURTH',piid=a.parent_piid,sub_agency_id=a.parent_agency_id)
    parent.update(generated_unique_award_id='SYNTH-SOURCE-PARENT-FOURTH',piid=a.parent_piid)
    tx=deepcopy(t);tx['responses']=[r for r in tx['responses'] if r['source']=='usaspending'];tx['responses'][0]['json']['page_metadata'].update(previous=None,next=None,hasPrevious=False)
    scenario['child']['transactions']=tx
    row=scenario['parent']['responses'][0]['json']['results'][0]
    row['id']=f'CONT_TX_{a.parent_agency_id}_-NONE-_{a.parent_piid}_0_-NONE-_-NONE-'
    return archive,cases,target,scenario,ctx[4]


def captured(tmp,ctx,change=None):
    tmp.mkdir(parents=True,exist_ok=True)
    t=deepcopy(ctx[3])
    if change:change(t)
    target={**ctx[2],'action_parent_capture':str(tmp/'child'),'action_parent_history':str(tmp/'parent')}
    collect(tmp/'journal',fallback(target),synthetic=t)
    return [*ctx[1],target]


def test_original_requirement_increment_is_separate_from_three_preserved_results(context,tmp_path):
    cases=captured(tmp_path,context);r=report(cases,baseline_package=context[0],selected_action=context[4])
    assert len(r['previously_resolved_synthetic_requirements'])==3
    assert len(r['newly_resolved_synthetic_requirements'])==1 and not r['newly_resolved_real_source_requirements']
    assert r['SAM_primary_observations_obtained']==0 and not r['financial_comparison_authorized']
    assert not r['historical_parent_applicability_intervals_established'] and not r['authoritative_real_source_correction_edges']
    assert set(r['newly_resolved_synthetic_requirements'])<=set(r['baseline']['remaining_original_plan_ids'])
    assert not r['cases'][-1]['financial_preflight']['totals_or_deltas_computed']


@pytest.mark.parametrize('stage,status',[('child',401),('child',403),('child',429),('child',500),('parent',403),('parent',503)])
def test_partial_source_failures_do_not_promote_absence_or_history(context,tmp_path,stage,status):
    def change(t):
        if stage=='child':t['child']['details'][0]['status']=status
        else:t['parent']['responses'][0]['status']=status
    cases=captured(tmp_path,context,change)
    r=report(cases,baseline_package=context[0],selected_action=context[4])
    assert not r['newly_resolved_synthetic_requirements'] and not r['financial_comparison_authorized']


def test_incomplete_child_pagination_stops_before_parent_access(context,tmp_path):
    cases=captured(tmp_path,context,lambda t:t['child']['transactions']['responses'][0]['json']['page_metadata'].update(hasNext=True,next=2))
    assert not Path(cases[-1]['action_parent_history']).exists()
    r=report(cases,baseline_package=context[0],selected_action=context[4]);assert not r['newly_resolved_synthetic_requirements']


@pytest.mark.parametrize('field,bad',[('piid','WRONG'),('sub_agency_id','0000'),('generated_unique_award_id','../bad')])
def test_wrong_parent_source_reference_fails_closed(context,tmp_path,field,bad):
    cases=captured(tmp_path,context,lambda t:t['child']['details'][0]['json']['parent_award'].__setitem__(field,bad))
    r=report(cases,baseline_package=context[0],selected_action=context[4]);assert not r['newly_resolved_synthetic_requirements']


def test_live_opt_in_cannot_apply_to_synthetic_source(context,tmp_path,monkeypatch):
    import src.source_verification as c12
    monkeypatch.setattr(c12,'HTTPTransport',lambda *_:pytest.fail('network initialized'))
    target={**context[2],'action_parent_capture':str(tmp_path/'child'),'action_parent_history':str(tmp_path/'parent')}
    with pytest.raises(ValueError):collect(tmp_path/'journal',fallback(target),live=True)
    with pytest.raises(ValueError):collect(tmp_path/'journal',fallback(target))
    assert not (tmp_path/'journal').exists()


def test_prior_C17_source_cannot_be_rebound_as_new(context):
    case=deepcopy(context[1][-1]);case['action_parent_capture']='new'
    with pytest.raises(ValueError):fallback(case)


@pytest.mark.parametrize('name',['detail-000.json','detail-001.body','experiment-commit.json'])
def test_missing_request_history_preserved_not_repaired(context,tmp_path,name):
    cases=captured(tmp_path,context);root=Path(cases[-1]['action_parent_capture']);(root/name).unlink();before=inventory(root)
    with pytest.raises(ValueError):report(cases,baseline_package=context[0],selected_action=context[4])
    assert inventory(root)==before


def test_stable_reports_static_html_and_tamper_rejection(context,tmp_path):
    cases=captured(tmp_path/'source',context);kwargs={'baseline_package':context[0],'selected_action':context[4]}
    a,b=tmp_path/'a',tmp_path/'b'
    assert write_report(a,cases,**kwargs)==write_report(b,cases,**kwargs) and inventory(a)==inventory(b)
    value=verify_report(a,cases,**kwargs);value['untrusted_text']='<script>alert(1)</script>```'
    raw=projections(value);assert b'<script>' not in raw['action-authority.html'] and b'&lt;script&gt;' in raw['action-authority.html']
    (a/'action-authority.json').write_text('{}')
    with pytest.raises(ValueError):verify_report(a,cases,**kwargs)


def test_C18_package_replays_four_cases_and_finite_legacy_chain(context,tmp_path):
    cases=captured(tmp_path/'source',context);stage=tmp_path/'export';stage.mkdir();rel=[];absolute=[]
    for i,c in enumerate(cases):
        rr,aa=deepcopy(c),deepcopy(c)
        for key in ('collections','sam_captures','c12_capture','historical_probe','parent_history','continuation','authority_binding','new_parent_capture','new_parent_history','action_parent_capture','action_parent_history'):
            if not c.get(key):continue
            vv=c[key] if key in ('collections','sam_captures') else [c[key]];names=[f'case-{i}-{key}-{j}' for j in range(len(vv))]
            for v,n in zip(vv,names):shutil.copytree(v,stage/n)
            rr[key]=names if key in ('collections','sam_captures') else names[0]
            pp=[str(stage/n) for n in names];aa[key]=pp if key in ('collections','sam_captures') else pp[0]
        rel.append(rr);absolute.append(aa)
    shutil.copyfile(context[0],stage/'baseline-package.zip')
    (stage/'cases.json').write_text(canonical({'schema_version':1,'cases':rel,'baseline_package':'baseline-package.zip','selected_action':context[4],'sam_action_captures':[]}))
    write_report(stage/'report',absolute,baseline_package=stage/'baseline-package.zip',selected_action=context[4])
    archive=tmp_path/'c18.zip';receipt=build_package(stage,archive,phase='C18');assert receipt==verify_package(archive,expected_phase='C18')
    assert not receipt['resolved_real_source_plan_ids']
    for phase in ('C14','C15','C16','C17'):
        with pytest.raises(ValueError):verify_package(archive,expected_phase=phase)
    def forge(files):
        value=json.loads(files['report/action-authority.json']);value['financial_comparison_authorized']=True
        for n,raw in projections(value).items():files['report/'+n]=raw
        commit=json.loads(files['report/action-authority-commit.json']);commit['report_sha256']=digest(value)
        commit['files']={n[7:]:hashlib.sha256(raw).hexdigest() for n,raw in files.items() if n.startswith('report/') and n!='report/action-authority-commit.json'}
        files['report/action-authority-commit.json']=(canonical(commit)+'\n').encode()
        idx=json.loads(files['evidence-index.json']);idx['report_sha256']=digest(value);files['evidence-index.json']=(canonical(idx)+'\n').encode()
    bad=tmp_path/'bad.zip';rewrite_zip(archive,bad,forge,resign=True)
    with pytest.raises(ValueError):verify_package(bad)


@pytest.mark.parametrize('raw',['[1]','[null]','{}','['])
def test_malformed_C18_inputs_reject_before_source_access(tmp_path,raw,capsys):
    c=tmp_path/'cases.json';c.write_text(raw);a=tmp_path/'action.json';a.write_text('{}')
    assert main(['--cases',str(c),'--selected-action',str(a),'--baseline-package',str(tmp_path/'absent.zip'),'--plan-fallback'])==2
    assert json.loads(capsys.readouterr().out)['error_code']=='action_authority_failed_preserve_evidence'


def test_frozen_documents_remain_byte_identical():
    p=json.loads(Path('docs/primary-action-authority-protocol-v1.json').read_text());assert len(p['frozen_files'])==69
    for n,h in p['frozen_files'].items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==h
