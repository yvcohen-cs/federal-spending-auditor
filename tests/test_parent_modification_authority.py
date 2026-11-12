"""C17 deterministic offline evidence; no simulated authority becomes real proof."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import shutil
import pytest
from src.evidence_io import canonical,digest
from src.evidence_package import build_package,verify_package,verified_directory,_recipe
from src.authority_binding import parent_sources
from src.parent_modification_authority import assess
from src.parent_authority_acquisition import plan,collect
from src.parent_authority_reporting import report,write_report,verify_report,projections,main
from src.authority_reporting import write_report as write_c16
from src.history_demo import fixture,collect_fixture
from src.scope_models import ScopeRequest
from tests.test_historical_authority import context as old_context,captured_binding
from tests.test_evidence_acquisition import inventory
from tests.test_parent_coverage import rewrite_zip


def staging(root,cases,baseline,*,phase,selection=None):
    root.mkdir();rel=[];absolute=[]
    for i,c in enumerate(cases):
        r,a=deepcopy(c),deepcopy(c)
        for k in ('collections','c12_capture','parent_history','continuation','authority_binding','new_parent_capture','new_parent_history'):
            if not c.get(k):continue
            values=c[k] if k=='collections' else [c[k]]
            names=[f'case-{i}-{k}-{j}' for j in range(len(values))]
            for v,n in zip(values,names):shutil.copytree(v,root/n)
            r[k]=names if k=='collections' else names[0]
            pp=[str(root/n) for n in names];a[k]=pp if k=='collections' else pp[0]
        rel.append(r);absolute.append(a)
    shutil.copyfile(baseline,root/'baseline-package.zip')
    recipe={'schema_version':1,'cases':rel,'baseline_package':'baseline-package.zip'}
    if phase=='C17':recipe['selected_action']=selection
    (root/'cases.json').write_text(canonical(recipe)+'\n')
    if phase=='C16':write_c16(root/'report',absolute,baseline_package=root/'baseline-package.zip')
    else:write_report(root/'report',absolute,baseline_package=root/'baseline-package.zip',selected_action=selection)
    return absolute


@pytest.fixture(scope='module')
def context(tmp_path_factory):
    tmp=tmp_path_factory.mktemp('parent-modification')
    old=old_context.__wrapped__(tmp_path_factory)
    selected,data=fixture('equal_control')
    original_piid=selected.piid
    selected=replace(selected,piid='SYNTH-SECOND-00001',generated_id='SYNTHETIC-NATIVE-CHILD-SECOND')
    for response in data['responses']:
        if response['source']=='usaspending':
            for row in response['json']['results']:
                row['id']=row['id'].replace(original_piid,selected.piid).replace('_P00001_','_0_');row['modification_number']='0'
        else:response['text']=response['text'].replace(original_piid,selected.piid).replace('<f:modNumber>P00001</f:modNumber>','<f:modNumber>0</f:modNumber>')
    selected_root=tmp/'selected-original';collect_fixture(selected_root,selected,data)
    old=(old[0],old[1],{**old[2],'collections':[str(selected_root)]},old[3])
    (tmp/'binding').mkdir()
    _,cases,_=captured_binding(tmp/'binding',old)
    root=tmp/'c16-stage';staging(root,cases,old[0],phase='C16')
    archive=tmp/'c16.zip';build_package(root,archive,phase='C16')
    with verified_directory(archive,expected_phase='C16') as (rr,v):
        _,prior,_=_recipe(rr,'C16')
        with verified_directory(prior,expected_phase='C15') as (p,w):records=parent_sources(p,w)[0]['record_observations']
    action=assess(cases[1],records,modification='0',transaction='0')
    selection={'original_case_sha256':action['original_case_sha256'],'modification':'0','transaction':'0'}
    a,data=fixture('equal_control');oldpiid,oldparent=a.piid,a.parent_piid
    a=replace(a,piid='SYNTH-THIRD-0001',generated_id='SYNTH-NATIVE-THIRD',parent_piid='SYNTH-PARENT-THIRD')
    for response in data['responses']:
        if response['source']=='usaspending':
            for row in response['json']['results']:row['id']=row['id'].replace(oldpiid,a.piid).replace(oldparent,a.parent_piid)
        else:response['text']=response['text'].replace(oldpiid,a.piid).replace(oldparent,a.parent_piid)
    original=tmp/'third-original';collect_fixture(original,a,data)
    scope=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    target={'collections':[str(original)],'scope':scope.to_dict()}
    child={'generated_unique_award_id':a.generated_id,'piid':a.piid,'category':'contract','type':'C',
        'parent_award':{'generated_unique_award_id':'SYNTH-SOURCE-NATIVE-PARENT-THIRD','piid':a.parent_piid,'sub_agency_id':a.parent_agency_id}}
    parent={'generated_unique_award_id':'SYNTH-SOURCE-NATIVE-PARENT-THIRD','piid':a.parent_piid,'category':'idv','type':'IDV_B','parent_award':None}
    tx=deepcopy(data);tx['responses']=[r for r in tx['responses'] if r['source']=='usaspending']
    tx['responses'][0]['json']['page_metadata'].update(previous=None,next=None,hasPrevious=False)
    row={'id':f'CONT_TX_{a.parent_agency_id}_-NONE-_{a.parent_piid}_0_-NONE-_-NONE-',
        'type':'IDV_B','action_date':'2016-01-01','modification_number':'0','federal_action_obligation':0,'description':'Synthetic parent action'}
    parent_tx={'schema_version':1,'responses':[{'source':'usaspending','json':{'results':[row],
        'page_metadata':{'page':1,'previous':None,'next':None,'hasPrevious':False,'hasNext':False}}}]}
    synthetic={'child':{'details':[{'source':'usaspending','json':child},{'source':'usaspending','json':parent}],'transactions':tx},'parent':parent_tx}
    return archive,cases,target,synthetic,selection,records


def captured(tmp,ctx,change=None):
    tmp.mkdir(parents=True,exist_ok=True)
    transcript=deepcopy(ctx[3])
    if change:change(transcript)
    target={**ctx[2],'new_parent_capture':str(tmp/'new-child'),'new_parent_history':str(tmp/'new-parent')}
    collect(tmp/'journal',target,synthetic=transcript)
    return [*ctx[1],target]


def test_levels_one_to_three_never_establish_applicability(context):
    v=assess(context[1][1],context[5],modification='0',transaction='0')
    assert v['evidence_levels']['child_references_parent_modification']
    assert v['evidence_levels']['parent_modification_independently_observed']
    assert not v['evidence_levels']['authoritative_historical_applicability_rule_established']
    assert not v['evidence_levels']['historical_applicability_independently_verified']
    assert not v['financial_comparison_authorized'] and not v['authoritative_correction_relationships']


@pytest.mark.parametrize('modification,transaction',[('999','0'),('0','999'),('', '0'),(None,'0'),(0,'0'),('0',False)])
def test_missing_or_untyped_exact_action_is_rejected(context,modification,transaction):
    with pytest.raises(ValueError):assess(context[1][1],context[5],modification=modification,transaction=transaction)


@pytest.mark.parametrize('field,bad',[('modification_number','WRONG'),('action_date','2099-01-01')])
def test_parent_label_and_date_never_create_effective_rule(context,field,bad):
    records=deepcopy(context[5]);records[0][field]=bad
    if field=='modification_number':
        with pytest.raises(ValueError):assess(context[1][1],records,modification='0',transaction='0')
        return
    r=assess(context[1][1],records,modification='0',transaction='0')
    assert not r['historical_parent_applicability_intervals'] and not r['financial_comparison_authorized']


def test_absent_parent_modification_remains_missing(context):
    r=assess(context[1][1],[],modification='0',transaction='0')
    assert not r['evidence_levels']['parent_modification_independently_observed']
    assert 'referenced_parent_modification_not_observed' in r['blockers']


def test_reused_parent_modifications_are_not_a_revision_winner(context):
    records=deepcopy(context[5]);records.append(deepcopy(records[0]))
    from src.identity_matching import decode_usa_id
    records[-1]['source_native_record_id']=records[-1]['source_native_record_id'].rsplit('_',1)[0]+'_1'
    components,_=decode_usa_id(records[-1]['source_native_record_id'])
    records[-1]['native_action_components']={k:v.to_dict() for k,v in components.items()}
    r=assess(context[1][1],records,modification='0',transaction='0')
    assert r['reused_parent_modification_label'] and not r['authoritative_correction_relationships']


def test_synthetic_fallback_closes_only_original_missing_primary(context,tmp_path):
    cases=captured(tmp_path,context);r=report(cases,baseline_package=context[0],selected_action=context[4])
    assert len(r['previously_resolved_synthetic_requirements'])==2
    assert len(r['newly_resolved_synthetic_requirements'])==1
    assert not r['newly_resolved_real_source_requirements']
    assert set(r['newly_resolved_synthetic_requirements'])<=set(r['baseline']['remaining_original_plan_ids'])
    assert not r['financial_comparison_authorized'] and not r['historical_parent_applicability_intervals_established']
    assert all(not c['financial_comparison_authorized'] for c in r['cases'])
    assert not r['cases'][-1]['monetary_compatibility']['totals_or_deltas_computed']


@pytest.mark.parametrize('stage,status',[('child',401),('child',403),('child',404),('child',429),('child',500),('parent',403),('parent',503)])
def test_access_failures_preserved_without_retry_or_false_absence(context,tmp_path,stage,status):
    def change(t):
        if stage=='child':t['child']['details'][0]['status']=status
        else:t['parent']['responses'][0]['status']=status
    cases=captured(tmp_path,context,change)
    r=report(cases,baseline_package=context[0],selected_action=context[4])
    assert not r['newly_resolved_synthetic_requirements']
    if stage=='child':assert not Path(cases[-1]['new_parent_history']).exists()


@pytest.mark.parametrize('field,bad',[('piid','OTHER'),('sub_agency_id','0000'),('generated_unique_award_id','../bad')])
def test_conflicting_current_parent_references_never_close_claim(context,tmp_path,field,bad):
    cases=captured(tmp_path,context,lambda t:t['child']['details'][0]['json']['parent_award'].__setitem__(field,bad))
    r=report(cases,baseline_package=context[0],selected_action=context[4])
    assert not r['newly_resolved_synthetic_requirements']


@pytest.mark.parametrize('field,bad',[('id','CONT_TX_9999_-NONE-_OTHER_0_-NONE-_-NONE-'),('modification_number','1'),('type','C'),('action_date','bad')])
def test_unsupported_parent_records_do_not_resolve(context,tmp_path,field,bad):
    cases=captured(tmp_path,context,lambda t:t['parent']['responses'][0]['json']['results'][0].__setitem__(field,bad))
    r=report(cases,baseline_package=context[0],selected_action=context[4])
    assert not r['newly_resolved_synthetic_requirements']


def test_unconfigured_access_and_synthetic_live_confusion_never_initialize_network(context,tmp_path,monkeypatch):
    import src.source_verification as c12
    import src.parent_history_probe as parent
    monkeypatch.setattr(c12,'HTTPTransport',lambda *_:pytest.fail('network initialized'))
    monkeypatch.setattr(parent,'HTTPTransport',lambda *_:pytest.fail('network initialized'))
    target={**context[2],'new_parent_capture':str(tmp_path/'child'),'new_parent_history':str(tmp_path/'parent')}
    for kw in ({},{'live':True},{'live':True,'synthetic':context[3]},{'live':1}):
        with pytest.raises(ValueError):collect(tmp_path/'journal',target,**kw)
    assert not (tmp_path/'journal').exists()


@pytest.mark.parametrize('name',['experiment-commit.json','detail-000.json','detail-001.body','transactions/c3_attempt_000000.body'])
def test_interrupted_or_tampered_child_histories_are_not_repaired(context,tmp_path,name):
    cases=captured(tmp_path,context)
    (Path(cases[-1]['new_parent_capture'])/name).unlink()
    before=inventory(cases[-1]['new_parent_capture'])
    with pytest.raises(ValueError):report(cases,baseline_package=context[0],selected_action=context[4])
    assert inventory(cases[-1]['new_parent_capture'])==before


def test_reports_repeat_escape_and_recompute(context,tmp_path):
    cases=captured(tmp_path/'source',context)
    a,b=tmp_path/'a',tmp_path/'b'
    assert write_report(a,cases,baseline_package=context[0],selected_action=context[4])==write_report(b,cases,baseline_package=context[0],selected_action=context[4])
    assert inventory(a)==inventory(b)
    r=verify_report(a,cases,baseline_package=context[0],selected_action=context[4])
    r['unsafe_test_text']='<script>alert(1)</script>```'
    p=projections(r);assert b'<script>' not in p['parent-authority.html'] and b'&lt;script&gt;' in p['parent-authority.html']
    (a/'parent-authority.json').write_text('{}')
    with pytest.raises(ValueError):verify_report(a,cases,baseline_package=context[0],selected_action=context[4])


def test_C17_package_replays_nested_C16_and_new_raw_primary(context,tmp_path):
    cases=captured(tmp_path/'source',context)
    root=tmp_path/'export';staging(root,cases,context[0],phase='C17',selection=context[4])
    out=tmp_path/'c17.zip';v=build_package(root,out,phase='C17')
    assert v==verify_package(out,expected_phase='C17')
    for phase in ('C14','C15','C16'):
        with pytest.raises(ValueError):verify_package(out,expected_phase=phase)
    bad=tmp_path/'bad.zip'
    rewrite_zip(out,bad,lambda f:f.__setitem__('report/parent-authority.json',b'{}'),resign=True)
    with pytest.raises(ValueError):verify_package(bad)


@pytest.mark.parametrize('stage',['child','parent'])
def test_incomplete_pagination_cannot_certify_history(context,tmp_path,stage):
    def change(t):
        if stage=='child':t['child']['transactions']['responses'][0]['json']['page_metadata'].update(hasNext=True,next=2)
        else:
            t['parent']['responses'][0]['json']['page_metadata'].update(hasNext=True,next=2)
            # A second unavailable page is a preserved partial failure.
            t['parent']['responses'].append({'source':'usaspending','status':503,'text':''})
    cases=captured(tmp_path,context,change)
    r=report(cases,baseline_package=context[0],selected_action=context[4])
    assert not r['historical_parent_applicability_intervals_established'] and not r['financial_comparison_authorized']
    if stage=='child':
        assert not Path(cases[-1]['new_parent_history']).exists()
        assert not r['newly_resolved_synthetic_requirements']


@pytest.mark.parametrize('field,value',[('modification_number','0'),('id','CONT_TX_9999_0002_OTHER_0_SYNTH-PARENT-THIRD_0')])
def test_contradictory_current_child_action_prevents_fallback(context,tmp_path,field,value):
    cases=captured(tmp_path,context,lambda t:t['child']['transactions']['responses'][0]['json']['results'][0].__setitem__(field,value))
    r=report(cases,baseline_package=context[0],selected_action=context[4])
    assert not Path(cases[-1]['new_parent_history']).exists()
    assert not r['newly_resolved_synthetic_requirements']


@pytest.mark.parametrize('marker',['malformed','2099-01-01T00:00:00Z',None])
def test_timestamps_never_establish_effective_dates_or_precedence(context,marker):
    records=deepcopy(context[5])
    for r in records:r['evidence']['source_update_raw']=marker
    a=assess(context[1][1],records,modification='0',transaction='0')
    assert not a['evidence_levels']['historical_applicability_independently_verified']
    assert not a['authoritative_correction_relationships']


@pytest.mark.parametrize('field,bad',[('source_native_record_id','forged'),('modification_number','WRONG')])
def test_forged_parent_record_components_are_rejected(context,field,bad):
    records=deepcopy(context[5]);records[0][field]=bad
    with pytest.raises(ValueError):assess(context[1][1],records,modification='0',transaction='0')


def test_source_scope_is_not_selected_by_amount_or_alias(context):
    c=deepcopy(context[1][1]);c['scope']['agency']='9999'
    with pytest.raises(ValueError):assess(c,context[5],modification='0',transaction='0')


def test_mismatched_baseline_or_duplicate_cases_fail_closed(context,tmp_path):
    cases=captured(tmp_path,context)
    with pytest.raises(ValueError):report(cases+[cases[-1]],baseline_package=context[0],selected_action=context[4])
    selection={**context[4],'original_case_sha256':'0'*64}
    with pytest.raises(ValueError):report(cases,baseline_package=context[0],selected_action=selection)


def test_frozen_protocols_unchanged():
    p=json.loads(Path('docs/parent-modification-authority-protocol-v1.json').read_text())
    assert len(p['frozen_files'])==66
    for n,h in p['frozen_files'].items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==h


def test_duplicate_parent_occurrences_are_not_reuse_or_corroboration(context):
    rows=deepcopy(context[5]);rows.append(deepcopy(rows[0]))
    r=assess(context[1][1],rows,modification='0',transaction='0')
    assert r['duplicate_parent_observation_occurrences']==1
    assert not r['reused_parent_modification_label'] and not r['duplicates_are_independent_corroboration']
    assert not r['historical_parent_applicability_intervals']


def test_conflicting_historical_parent_modification_assertions_are_preserved(tmp_path):
    a,t=fixture('equal_control')
    xml=t['responses'][-1]['text']
    start=xml.index('<entry>');end=xml.index('</entry>')+8
    entry=xml[start:end]
    begin=entry.index('<f:referencedIDVID>');finish=entry.index('</f:referencedIDVID>')
    alternate=entry[:begin]+entry[begin:finish].replace('<f:modNumber>0</f:modNumber>','<f:modNumber>1</f:modNumber>')+entry[finish:]
    assert alternate!=entry
    t['responses'][-1]['text']=xml.replace('</feed>',alternate+'</feed>')
    root=tmp_path/'original';collect_fixture(root,a,t)
    scope=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    case={'collections':[str(root)],'scope':scope.to_dict()}
    from src.correction_reporting import report as original_report,_parent_modification
    from src.revision_lineage import LineageObservation
    graph=original_report([case])['cases'][0]['observation_graph']
    refs=[]
    for raw in graph['nodes']:
        n=LineageObservation.from_dict({k:v for k,v in raw.items() if k!='node_id'})
        if n.source=='fpds':refs.append(_parent_modification(n,case))
    assert set(refs)=={'0','1'}
    with pytest.raises(ValueError):assess(case,[],modification='P00001',transaction='0')


def test_fully_resigned_false_financial_history_and_resolution_reports_are_rejected(context,tmp_path):
    cases=captured(tmp_path/'source',context)
    root=tmp_path/'export';staging(root,cases,context[0],phase='C17',selection=context[4])
    original=tmp_path/'source.zip';build_package(root,original,phase='C17')
    for field in ('financial_comparison_authorized','historical_parent_applicability_intervals_established','authoritative_real_source_correction_edges'):
        def forge(files):
            value=json.loads(files['report/parent-authority.json']);value[field]=True if field=='financial_comparison_authorized' else 1
            for name,raw in projections(value).items():files['report/'+name]=raw
            commit=json.loads(files['report/parent-authority-commit.json'])
            commit['report_sha256']=digest(value)
            commit['files']={n.removeprefix('report/'):hashlib.sha256(raw).hexdigest() for n,raw in files.items() if n.startswith('report/') and n!='report/parent-authority-commit.json'}
            files['report/parent-authority-commit.json']=(canonical(commit)+'\n').encode()
            index=json.loads(files['evidence-index.json']);index['report_sha256']=digest(value)
            files['evidence-index.json']=(canonical(index)+'\n').encode()
        bad=tmp_path/(field+'.zip');rewrite_zip(original,bad,forge,resign=True)
        with pytest.raises(ValueError):verify_package(bad)


@pytest.mark.parametrize('raw',['[1]','[null]','{}','['])
def test_malformed_case_json_fails_before_any_source_access(tmp_path,raw,monkeypatch,capsys):
    import src.source_verification as source
    monkeypatch.setattr(source,'HTTPTransport',lambda *_:pytest.fail('network initialized'))
    f=tmp_path/'cases.json';f.write_text(raw)
    selection=tmp_path/'action.json';selection.write_text('{}')
    assert main(['--cases',str(f),'--selected-action',str(selection),'--baseline-package',str(tmp_path/'missing.zip'),'--plan-fallback'])==2
    assert json.loads(capsys.readouterr().out)['error_code']=='parent_authority_failed_preserve_evidence'
