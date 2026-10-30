"""C7 temporary synthetic fault injection; no human data or actual approvals."""
from dataclasses import replace
from pathlib import Path
import hashlib
import hmac
import os
import shutil
import xml.etree.ElementTree as ET

import pytest

from test_coordinator_rehearsal import seed, workspace, retire_batch
from src.evidence_io import EvidenceError, canonical, digest, strict_json
from src.coordinator_lifecycle import inspect, tip, retire, delete, _tree
from src.coordinator_governance import (pending_checklist, ApprovalRecord, ApprovalState as S,
    ApprovalOrigin as O, SCOPES)
from src.pilot_taskset import make_protocol
from src.technical_assessment import ApprovalDossier, assess_dossier, protocol, documents, code_digest
from src.technical_assessment_reporting import (assessment, write_report, read_report, html,
    test_receipt as normalize_receipt)
from src.coordinator_accessibility import safe_text, plain_output, show_task, accessible_terminal


@pytest.fixture(scope='module',autouse=True)
def receipt_binding(record_testsuite_property):
    record_testsuite_property('technical_assessment_code_sha256',code_digest())


def legacy_context(root):
    """Explicit synthetic v1 conversion, never modification of historical inputs."""
    manifest_path=root/'deletion-manifest.json'
    if manifest_path.exists():
        manifest=strict_json(manifest_path.read_bytes())
        manifest={k:{n:v for n,v in tree.items() if not n.startswith('identity:')} for k,tree in manifest.items()}
        manifest_path.write_text(canonical(manifest)+'\n')
    context=strict_json((root/'coordinator-context.json').read_bytes());context['schema_version']=1
    if manifest_path.exists():context['manifest_sha256']=digest(manifest)
    (root/'coordinator-context.json').write_text(canonical(context)+'\n')
    secret=(root/'coordinator.key').read_bytes().rstrip(b'\n');previous=None
    for path in sorted(root.glob('lifecycle-*.json')):
        value=strict_json(path.read_bytes());value.update(context_sha256=digest(context),previous=previous)
        value['mac']=hmac.new(secret,canonical({k:v for k,v in value.items() if k!='mac'}).encode(),hashlib.sha256).hexdigest()
        path.write_text(canonical(value)+'\n');previous=digest(value)


@pytest.mark.parametrize('name',['batch','outputs','retired-batch','retired-outputs'])
def test_deleted_namespace_dangling_link_rejected(workspace,name):
    root,key=workspace;retire_batch(root,key);delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    (root/name).symlink_to(root/'does-not-exist')
    # Exact old predicate ignores the entry. New validation must not.
    assert not (root/name).exists() and os.path.lexists(root/name)
    with pytest.raises(EvidenceError):inspect(root,key)
    assert (root/name).is_symlink() # rejected transition never cleans evidence


@pytest.mark.parametrize('target',['batch','outputs/report-a','batch/coordinator.key','batch/task-set.json','batch/session'])
def test_same_byte_target_replacement_rejected(workspace,tmp_path,target):
    root,key=workspace;expected=tip(root,key)
    path=next((root/'batch').glob('session-*')) if target=='batch/session' else root/target
    original=tmp_path/'original-object';path.rename(original)
    if original.is_dir():shutil.copytree(original,path)
    else:shutil.copyfile(original,path);path.chmod(0o600)
    assert _tree(path)==_tree(original) if path.is_dir() else path.read_bytes()==original.read_bytes()
    before={p.name for p in root.glob('lifecycle-*')}
    with pytest.raises(EvidenceError):retire(root,key,expected_tip=expected,as_of='2025-03-01',reason='DRY_RUN')
    assert original.exists() and path.exists()
    assert {p.name for p in root.glob('lifecycle-*')}==before


def test_legacy_capture_is_read_only(workspace):
    root,key=workspace;legacy_context(root)
    c,e,state=inspect(root,key);assert state=='ACTIVE' and c['schema_version']==1
    before=(root/'coordinator-context.json').read_bytes()
    with pytest.raises(EvidenceError,match='legacy_capture_read_only'):retire_batch(root,key)
    assert (root/'coordinator-context.json').read_bytes()==before and (root/'batch').exists()


@pytest.mark.parametrize('stage',['before_retire_begin','after_retire_begin','rename_batch','rename_outputs',
    'before_delete_begin','delete_begin','unlink','before_rmdir','after_rmdir','remove_root','delete_commit'])
def test_fault_boundaries_recover_or_reject(workspace,monkeypatch,stage):
    import src.coordinator_lifecycle as module
    root,key=workspace
    retirement=stage in ('before_retire_begin','after_retire_begin','rename_batch','rename_outputs')
    if not retirement:retire_batch(root,key)
    before_tip=tip(root,key);fired=[]
    def stop(name):
        if name==stage and not fired:fired.append(name);raise InterruptedError('synthetic_fault')
    monkeypatch.setattr(module,'_after_boundary',stop)
    with pytest.raises(InterruptedError):
        if retirement:retire_batch(root,key)
        else:delete(root,key,expected_tip=before_tip,as_of='2025-03-01')
    assert fired
    c,e,state=inspect(root,key)
    if stage in ('before_retire_begin','before_delete_begin'):assert tip(root,key)==before_tip
    elif stage!='delete_commit':assert state in ('RETIRING','DELETING')
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    if retirement:retire(root,key,expected_tip=tip(root,key),as_of='2025-03-01',reason='WITHDRAWAL_REQUEST')
    delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    assert inspect(root,key)[2]=='DELETED'


def test_directory_replacement_at_rmdir_boundary(workspace,tmp_path,monkeypatch):
    import src.coordinator_lifecycle as module
    root,key=workspace;retire_batch(root,key);old=tmp_path/'held-original';fired=[]
    def replace_at_boundary(stage):
        if stage=='before_rmdir' and not fired:
            path=root/'retired-outputs'/'report-a';path.rename(old);os.mkdir(path,0o700);fired.append(path)
    monkeypatch.setattr(module,'_after_boundary',replace_at_boundary)
    with pytest.raises(EvidenceError):delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    assert old.exists() and fired[0].exists()
    # Explicitly restore the retained original, not invented bytes/metadata.
    fired[0].rmdir();old.rename(fired[0]);monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    assert inspect(root,key)[2]=='DELETED'


@pytest.mark.parametrize('nth',[1,2,5])
def test_interruption_after_individual_unlinks(workspace,monkeypatch,nth):
    import src.coordinator_lifecycle as module
    root,key=workspace;retire_batch(root,key);count=[]
    def stop(stage):
        if stage=='unlink':
            count.append(stage)
            if len(count)==nth:raise InterruptedError('synthetic_fault')
    monkeypatch.setattr(module,'_after_boundary',stop)
    with pytest.raises(InterruptedError):delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    assert len(count)==nth and inspect(root,key)[2]=='DELETING'
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01');assert inspect(root,key)[2]=='DELETED'


@pytest.mark.parametrize('attack',['duplicate','missing','forged_state','wrong_mac','partial','source','unexpected_file','modified_survivor'])
def test_event_history_tampering_rejected(workspace,attack):
    root,key=workspace;retire_batch(root,key);expected=tip(root,key)
    if attack=='duplicate':shutil.copyfile(root/'lifecycle-000002.json',root/'lifecycle-000003.json')
    elif attack=='missing':(root/'lifecycle-000001.json').unlink()
    elif attack=='partial':(root/'lifecycle-000003.json.partial').write_text('{')
    elif attack in ('forged_state','wrong_mac'):
        path=root/'lifecycle-000002.json';v=strict_json(path.read_bytes());v['state' if attack=='forged_state' else 'mac']='DELETED' if attack=='forged_state' else 'f'*64;path.write_text(canonical(v))
    elif attack=='unexpected_file':
        p=root/'retired-batch'/'not-registered';p.write_text('evidence');p.chmod(0o600)
    elif attack=='modified_survivor':next((root/'retired-batch').glob('receipt-*.json')).write_text('{}')
    else:
        c,_,_=inspect(root,key);v=strict_json((root/'coordinator-context.json').read_bytes());v['source_roots']['/not-a-real-path']='f'*64;(root/'coordinator-context.json').write_text(canonical(v))
    original={p.name:p.read_bytes() for p in root.glob('lifecycle-*')}
    with pytest.raises((ValueError,OSError)):delete(root,key,expected_tip=expected,as_of='2025-03-01')
    assert {p.name:p.read_bytes() for p in root.glob('lifecycle-*')}==original


@pytest.mark.parametrize('mode',['wrong_key','stale_tip','copied_root'])
def test_capability_and_tip_rejection(workspace,tmp_path,mode):
    root,key=workspace;expected=tip(root,key)
    if mode=='wrong_key':key=tmp_path/'invalid.key';key.write_text('f'*64+'\n');key.chmod(0o600)
    elif mode=='stale_tip':expected='f'*64
    else:target=tmp_path/'copy';shutil.copytree(root,target);root=target;key=root/'coordinator.key'
    with pytest.raises(EvidenceError):retire(root,key,expected_tip=expected,as_of='2025-03-01',reason='DRY_RUN')
    assert (root/'batch').exists()


def approved(p):
    # Pure synthetic DTOs, never actual authority records or human enrollment.
    return replace(pending_checklist(p),approvals=tuple(ApprovalRecord(scope=scope,state=S.APPROVED,origin=O.PROSPECTIVE,
        reference='APPROVAL-eeeeeeee'+f'{i:08x}',approved_on='2025-01-01',expires_on='2025-12-31') for i,scope in enumerate(SCOPES)))


@pytest.mark.parametrize('index',range(7))
def test_conflicting_declarations_preserved(seed,index):
    p=make_protocol(seed[2]);a=approved(p);items=list(a.approvals);items[index]=replace(items[index],state=S.REJECTED)
    b=replace(a,approvals=tuple(items));d=ApprovalDossier(declarations=(a,b));r=assess_dossier(d,p,'2025-03-01')
    assert r['scope_results'][index]['status']=='CONFLICTING_DECLARATIONS'
    assert r['scope_results'][index]['states']==['APPROVED','REJECTED']
    assert r['approval_completeness']=='BLOCKED' and len(r['declaration_digests'])==2
    assert ApprovalDossier.from_dict(d.to_dict())==d


@pytest.mark.parametrize('mode',['unknown','expired','future','simulated','rejected'])
def test_approval_effectiveness_never_inferred(seed,mode):
    p=make_protocol(seed[2]);a=approved(p);items=list(a.approvals)
    items[0]=ApprovalRecord(scope=SCOPES[0]) if mode=='unknown' else replace(items[0],**{
        'expired':{'expires_on':'2025-01-02'},'future':{'approved_on':'2025-04-01'},
        'simulated':{'origin':O.SIMULATED},'rejected':{'state':S.REJECTED}}[mode])
    d=ApprovalDossier(declarations=(a,replace(a,approvals=tuple(items))))
    r=assess_dossier(d,p,'2025-03-01');assert r['approval_completeness']=='BLOCKED'
    assert not r['actual_enrollment_authorized'] and r['independent_approval_authenticity']=='UNKNOWN'


def test_cross_scope_reference_reuse_blocks(seed):
    p=make_protocol(seed[2]);a=approved(p);items=list(a.approvals)
    items[0]=replace(items[0],reference=a.approvals[1].reference);items[1]=replace(items[1],reference=a.approvals[0].reference)
    b=replace(a,approvals=tuple(items));r=assess_dossier(ApprovalDossier(declarations=(a,b)),p,'2025-03-01')
    assert all(row['status']=='CONFLICTING_DECLARATIONS' for row in r['scope_results'][:2])


@pytest.mark.parametrize('mode',['duplicate','protocol','task','governance','documents','schema'])
def test_dossier_replay_and_scope_expansion(seed,mode):
    p=make_protocol(seed[2]);a=approved(p)
    with pytest.raises((ValueError,TypeError)):
        if mode=='schema':value=ApprovalDossier(declarations=(a,)).to_dict();value['schema_version']=2;ApprovalDossier.from_dict(value)
        else:
            b=a if mode=='duplicate' else replace(a,**{{'protocol':'protocol_id','task':'task_set_digest','governance':'governance_sha256','documents':'documents_sha256'}[mode]:('study-protocol:v1:' if mode=='protocol' else '')+'f'*64})
            ApprovalDossier(declarations=(a,b))


def test_accessibility_plain_timing_and_observation_labels(seed,monkeypatch):
    import src.coordinator_accessibility as module
    from types import SimpleNamespace
    monkeypatch.setattr(module,'terminal',lambda *a,**k:0)
    import src.pilot_session_store as store
    monkeypatch.setattr(store,'read_session',lambda *a,**k:(SimpleNamespace(protocol=SimpleNamespace(measurement_kind=__import__('src.pilot_session_models',fromlist=['MeasurementKind']).MeasurementKind.SIMULATED)),None,None))
    lines=[];assert accessible_terminal('synthetic','synthetic','synthetic',output=lines.append)==0
    assert any('choose No to timing and continue untimed' in x for x in lines)
    assert any('Observation is a saved source field' in x for x in lines)
    assert any('q to save and stop' in x and 'w to withdraw' in x for x in lines)
    lines=[];show_task(seed[2].entries[0].task,0,12,lines.append)
    assert any('source fields separately from automated interpretations' in x for x in lines)


@pytest.mark.parametrize('value',['\x1b[2J','\u202e','\u2067','\x07','\n','\r','\u2028','\u2029'])
def test_terminal_control_preservation(value):
    assert value not in safe_text('observed:'+value)
    out=[];plain_output(out.append)('Source observation: 1. ACCEPT_EVIDENCE')
    assert out==['Source observation: 1. ACCEPT_EVIDENCE']


def junit(code=None,state=None):
    root=ET.Element('testsuites');suite=ET.SubElement(root,'testsuite');props=ET.SubElement(suite,'properties')
    ET.SubElement(props,'property',name='technical_assessment_code_sha256',value=code or code_digest())
    case=ET.SubElement(suite,'testcase',classname='tests.test_technical_assessment',name='test_assessment_digests_and_no_certification',time='999')
    if state:ET.SubElement(case,state)
    return ET.tostring(root)


@pytest.mark.parametrize('attack',['xml','entity','wrong_code','no_cases','duplicate','contradiction','wrong_root'])
def test_junit_receipt_rejects_unsupported_evidence(attack):
    raw=junit()
    if attack=='xml':raw=b'<broken'
    elif attack=='entity':raw=b'<!DOCTYPE a [<!ENTITY x "x">]><testsuites/>'
    elif attack=='wrong_code':raw=junit('f'*64)
    else:
        tree=ET.fromstring(raw);suite=tree.find('testsuite');case=suite.find('testcase')
        if attack=='no_cases':suite.remove(case)
        elif attack=='duplicate':suite.append(ET.fromstring(ET.tostring(case)))
        elif attack=='contradiction':ET.SubElement(case,'failure');ET.SubElement(case,'skipped')
        else:tree.tag='unrelated'
        raw=ET.tostring(tree)
    with pytest.raises(EvidenceError):normalize_receipt(raw)


@pytest.mark.parametrize('attack',['json','html','markdown','truncated','rehash'])
def test_assessment_report_tampering_rejected(tmp_path,attack):
    out=tmp_path/'report';write_report(out)
    name={'json':'assessment.json','html':'assessment.html','markdown':'assessment.md','truncated':'assessment.md','rehash':'assessment.html'}[attack]
    if attack=='truncated':(out/name).unlink()
    else:
        (out/name).write_text('<script>untrusted()</script>')
        if attack=='rehash':
            p=out/'assessment-commit.json';v=strict_json(p.read_bytes());v['files'][name]=hashlib.sha256((out/name).read_bytes()).hexdigest();p.write_text(canonical(v))
    with pytest.raises(EvidenceError):read_report(out)


def test_assessment_digests_and_no_certification(tmp_path):
    raw=junit();a=write_report(tmp_path/'a',raw);b=write_report(tmp_path/'b',raw)
    r=read_report(tmp_path/'a',raw);assert a==b==digest(r)
    assert r['external_approval']['records']==[] and r['actual_human_observation']['records']==[]
    assert 'NOT_AUTHENTICATED' in r['automated_tests']['scope']
    assert 'actual_human' not in canonical(r['automated_tests'])
    text=html({'x':'<script>evil()</script>'});assert '<script>' not in text and '&lt;script&gt;' in text
    t=ET.fromstring(raw);t.find('testsuite/testcase').set('time','0.001')
    assert normalize_receipt(raw)[0]==normalize_receipt(ET.tostring(t))[0]


def test_readiness_never_authorizes_humans_or_finances():
    r=assessment();assert len(r['readiness'])==12 and r['combined_score'] is None
    assert all(r[k] is False for k in ('actual_pilot_authorized','real_data_deletion_enabled','financial_eligibility_changed','frozen_readiness_upgrade','production_screening_authorized'))
    assert all(row['status']=='UNKNOWN' for row in r['readiness'] if row['dimension'] in ('accessibility','human_usability_evidence','human_throughput_evidence','independent_approval_authenticity'))
    assert r['automated_tests']['status'].startswith('NOT_EVALUATED')
    assert len(documents()['technical-findings-v1.json']['findings'])==20


@pytest.mark.parametrize('attack',['negative_inode','boolean_inode','missing_identity','wrong_kind','traversal','missing_all_bindings'])
def test_v2_manifest_rejects_unsupported_object_binding(tmp_path,attack):
    from src.coordinator_lifecycle import _validate_manifest
    file=tmp_path/'file';file.write_text('synthetic');file.chmod(0o600)
    entries=_tree(tmp_path,bind_identity=True)
    if attack=='negative_inode':entries['identity:file'][1]=-1
    elif attack=='boolean_inode':entries['identity:file'][1]=True
    elif attack=='missing_identity':entries.pop('identity:file')
    elif attack=='wrong_kind':entries['identity:file'][2]='directory'
    elif attack=='traversal':entries['../outside']='f'*64
    else:entries={k:v for k,v in entries.items() if not k.startswith('identity:')}
    with pytest.raises(EvidenceError):_validate_manifest({'batch':entries,'outputs':entries},2)


@pytest.mark.parametrize('attack',['unsupported_element','summary_disagrees','missing_name'])
def test_junit_rejects_false_positive_passes(attack):
    tree=ET.fromstring(junit());suite=tree.find('testsuite');case=suite.find('testcase')
    if attack=='unsupported_element':ET.SubElement(case,'unknown-failure')
    elif attack=='summary_disagrees':suite.set('failures','1')
    else:case.attrib.pop('name')
    with pytest.raises(EvidenceError):normalize_receipt(ET.tostring(tree))


def test_changed_source_hash_blocks_positive_inspection(workspace):
    from src.review_validation_tasks import inventory
    root,key=workspace;context,_,_=inspect(root,key)
    source=Path(next(iter(context['source_roots'])));path=source/next(iter(inventory(source)));original=path.read_bytes()
    try:
        path.write_bytes(original+b' ')
        with pytest.raises(EvidenceError):inspect(root,key)
    finally:path.write_bytes(original)
    assert inspect(root,key)[2]=='ACTIVE'


def test_receipt_binding_detects_shared_helper_only_change(tmp_path,monkeypatch):
    import src.technical_assessment as module
    original=module.ROOT;expected=code_digest();replica=tmp_path/'code-replica';replica.mkdir()
    for folder in ('src','tests'):
        (replica/folder).mkdir()
        for path in (original/folder).glob('*.py'):(replica/folder/path.name).write_bytes(path.read_bytes())
    (replica/'docs').mkdir()
    for path in (original/'docs').glob('*'):
        if path.is_file():(replica/'docs'/path.name).write_bytes(path.read_bytes())
    (replica/'requirements.txt').write_bytes((original/'requirements.txt').read_bytes())
    monkeypatch.setattr(module,'ROOT',replica)
    assert code_digest()==expected
    with (replica/'src'/'evidence_io.py').open('ab') as stream:stream.write(b'\n# authored helper-only change\n')
    assert code_digest()!=expected
    with pytest.raises(EvidenceError):normalize_receipt(junit(expected))


def test_unrelated_test_module_cannot_verify_named_regression():
    tree=ET.fromstring(junit());case=tree.find('testsuite/testcase')
    case.set('classname','unrelated.module');case.set('name','test_same_byte_target_replacement_rejected')
    r=assessment(ET.tostring(tree))
    finding=next(f for f in r['technical_review']['findings'] if f['finding_id']=='TA-002')
    assert finding['automated_verification']=='NOT_ESTABLISHED_BY_RECEIPT'
