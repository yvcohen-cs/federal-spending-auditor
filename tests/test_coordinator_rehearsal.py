"""Offline authored controls only. Public-slot surrogate is test-only, never a participant.

The exact frozen public inventory is exercised separately in the local completion
run; it is not committed or silently replaced by this CI fixture.
"""
from dataclasses import replace
from pathlib import Path
import fcntl
import hashlib
import json
import os
import shutil

import pytest

from src.evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from src.review_validation_study import create_study
from src.review_validation_tasks import build_tasks, inventory
from src.pilot_taskset import build_task_set, make_protocol
from src.pilot_session_models import PilotTaskSet, TaskBinding, StudyProtocol, MeasurementKind as M
from src.pilot_session_store import read_session, append_event
from src.coordinator_governance import (ApprovalRecord, ApprovalState as AS, ApprovalOrigin as AO,
    CoordinatorChecklist, SCOPES, pending_checklist, assess, require_approvals, protocol)
from src.coordinator_accessibility import safe_text, plain_output, show_task, accessible_terminal, audit
from src.coordinator_rehearsal import exercise
from src.coordinator_lifecycle import new_workspace, capture, inspect, tip, retire, delete, lifecycle_assessment
from src.coordinator_reporting import report, write_report, read_report, html
from src.coordinator_review import main


@pytest.fixture(scope='module')
def seed(tmp_path_factory):
    """12 logical slots, last authored synthetic source; no frozen-public claim."""
    import src.pilot_taskset as tasks_module
    import src.pilot_session_store as store_module
    import src.coordinator_rehearsal as rehearsal_module
    with pytest.MonkeyPatch.context() as patch:
        base=tmp_path_factory.mktemp('c6-synthetic');study=create_study(base/'controls')
        controls=build_task_set(study)
        source=Path(controls.entries[0].source_root)
        full=build_tasks(source)
        packet=next(p for p in full.packets.packets if p.claim.identity_result and p.claim.identity_result.claim=='award_association')
        public=build_tasks(source,claim_ids=(packet.claim.claim_id,))
        surrogate=TaskBinding(logical_root='preserved_public',source_root=str(source),source_inventory_json=public.source_inventory_json,
            selected_claim_ids=public.packets.selected_claim_ids,task=public.tasks[0],origin='preserved_public_unverified')
        tasks=PilotTaskSet(entries=controls.entries+(surrogate,),selection_version='pilot-mixed-v1')
        original=tasks_module.revalidate_tasks
        def synthetic_revalidate(value):
            # The one deliberately substituted trust boundary is explicit here.
            # Rebuild every actual synthetic primary task; never return True blindly.
            tasks_module.pin_sources(value)
            for e in value.entries:
                assert build_tasks(e.source_root,claim_ids=e.selected_claim_ids).tasks==(e.task,)
        patch.setattr(tasks_module,'revalidate_tasks',synthetic_revalidate)
        patch.setattr(store_module,'revalidate_tasks',synthetic_revalidate)
        patch.setattr(rehearsal_module,'build_task_set',lambda *a,**k:tasks)
        root=base/'seed';key=exercise(root,study,'TEST_ONLY_SYNTHETIC_PUBLIC_SURROGATE')
        yield root,key,tasks


@pytest.fixture
def workspace(tmp_path,seed):
    root=tmp_path/'private';key=new_workspace(root)
    for name in ('batch','outputs'):shutil.copytree(seed[0]/name,root/name)
    capture(root,key,as_of='2025-03-01')
    return root,key


def retire_batch(root,key,reason='WITHDRAWAL_REQUEST',as_of='2025-03-01'):
    return retire(root,key,expected_tip=tip(root,key),as_of=as_of,reason=reason)


def mutate(path,fn):
    value=strict_json(path.read_bytes());fn(value);path.write_text(canonical(value)+'\n')


def test_exact_logical_plan_and_preregistered_outcomes(seed):
    root,key,tasks=seed;c,e,s=inspect(root,key)
    assert len(tasks.entries)==12 and tuple(x.logical_root for x in tasks.entries)[-1]=='preserved_public'
    assert s=='ACTIVE'
    r=report(root,key,as_of='2025-03-01')
    assert r['simulated_observations']['metrics']['tasks_completed']==13
    assert r['simulated_observations']['excluded_sessions']['excluded_response_count']==1
    assert r['human_measurements']['status']=='NOT_CONDUCTED'
    assert len(r['prospective_governance']['missing_or_ineffective_scopes'])==7
    assert r['accessibility']['standards_conformance']=='NOT_EVALUATED'


@pytest.mark.parametrize('scope',SCOPES)
@pytest.mark.parametrize('state',['missing','simulated','expired','future','rejected'])
def test_missing_or_ineffective_independent_approval_blocks(seed,scope,state):
    p=make_protocol(seed[2]);pending=pending_checklist(p)
    approvals=[ApprovalRecord(scope=s,state=AS.APPROVED,origin=AO.PROSPECTIVE,
        reference='APPROVAL-aaaaaaaa'+f'{i:08x}',approved_on='2025-01-01',expires_on='2025-12-31') for i,s in enumerate(SCOPES)]
    i=SCOPES.index(scope)
    changes={'missing':None,'simulated':{'origin':AO.SIMULATED},'expired':{'expires_on':'2025-01-02'},
        'future':{'approved_on':'2025-04-01'},'rejected':{'state':AS.REJECTED}}[state]
    approvals[i]=ApprovalRecord(scope=scope) if changes is None else replace(approvals[i],**changes)
    checklist=replace(pending,approvals=tuple(approvals))
    with pytest.raises(EvidenceError):require_approvals(checklist,p,'2025-03-01')
    assert assess(checklist,p,'2025-03-01')['actual_enrollment_authorized'] is False


@pytest.mark.parametrize('field',['protocol_id','task_set_digest','governance_sha256','documents_sha256'])
def test_approval_scope_replay_rejected(seed,field):
    p=make_protocol(seed[2]);c=pending_checklist(p)
    wrong='study-protocol:v1:'+'f'*64 if field=='protocol_id' else 'f'*64
    with pytest.raises(EvidenceError):assess(replace(c,**{field:wrong}),p,'2025-03-01')


def test_complete_attestations_are_not_independent_authentication_or_enrollment(seed):
    p=make_protocol(seed[2]);c=pending_checklist(p)
    approvals=tuple(ApprovalRecord(scope=s,state=AS.APPROVED,origin=AO.PROSPECTIVE,reference='APPROVAL-aaaaaaaa'+f'{i:08x}',
        approved_on='2025-01-01',expires_on='2025-12-31') for i,s in enumerate(SCOPES))
    r=require_approvals(replace(c,approvals=approvals),p,'2025-03-01')
    assert r['approval_completeness']=='ATTESTATIONS_COMPLETE'
    assert not r['actual_enrollment_supported'] and not r['actual_enrollment_authorized']
    assert r['independent_approval_authenticity'].startswith('UNKNOWN')
    with pytest.raises(ValueError):replace(c,approvals=approvals[:1]*7)


@pytest.mark.parametrize('bad',[{'scope':'unrecognized'}, {'reference':'A Person'}, {'state':'APPROVED'},
    {'schema_version':2}, {'financial_authorization':True}, {'origin':'SIMULATED'}])
def test_invalid_or_fabricated_approval_schema(bad):
    value=ApprovalRecord(scope=SCOPES[0]).to_dict();value.update(bad)
    with pytest.raises((ValueError,TypeError)):ApprovalRecord.from_dict(value)


@pytest.mark.parametrize('text',['\x1b[2J','a\nb','\x07','\r','\x00','\u202eattack','\u2066x','\u2028x'])
def test_terminal_controls_cannot_change_focus_or_forge_lines(text):
    escaped=safe_text(text)
    assert '\\u' in escaped
    assert all(ord(c)>=32 for c in escaped)
    assert '\x1b' not in escaped and '\u202e' not in escaped


def test_keyboard_plain_labels_and_no_color(seed):
    lines=[];show_task(seed[2].entries[0].task,0,12,lines.append)
    assert 'Task 1 of 12' in lines and any('Unknown means proof is missing' in x for x in lines)
    out=[];plain_output(out.append)('1. ACCEPT_EVIDENCE')
    assert out==['1. Accept evidence for this narrow claim only']
    assert not audit()['color_only_cues'] and audit()['screen_reader_compatibility'].startswith('UNKNOWN')


def test_opt_in_terminal_invalid_input_and_pause_preserve_saved_response(workspace):
    root,key=workspace
    from src.pilot_session_store import inspect_environment
    from src.pilot_session_rules import replay
    p,t,s,ev=inspect_environment(root/'batch',root/'batch'/'coordinator.key')
    sid=next(sid for sid,session in s.items() if replay(session,t,ev[sid])[0].state.value=='IN_PROGRESS')
    resume=root/'batch'/('session-'+sid.removeprefix('study-session:v1:'))/'resume.key'
    answers=iter(['NOT_A_NAME_TO_PERSIST','q']);lines=[]
    assert accessible_terminal(root/'batch',sid,resume,input_fn=lambda _:next(answers),output=lines.append)==1
    assert any('Invalid choice' in x for x in lines)
    _,_,now=read_session(root/'batch',sid,resume)
    assert sum(e.action.value=='RESPOND' for e in now)==1
    assert all('NOT_A_NAME_TO_PERSIST' not in p.read_text() for p in (root/'batch').rglob('*.json'))
    # Managed capture detects any later session mutation; it cannot be presented as original.
    with pytest.raises(EvidenceError):inspect(root,key)


def test_retirement_invalidates_old_reports_and_resume_paths(workspace,tmp_path):
    root,key=workspace;out=tmp_path/'old-report';write_report(out,root,key,as_of='2025-03-01')
    before=inventory(root/'batch');retire_batch(root,key)
    assert not (root/'batch').exists() and not (root/'outputs').exists()
    assert inventory(root/'retired-batch')==before
    assert inspect(root,key)[2]=='RETIRED'
    with pytest.raises(EvidenceError):read_report(out,root,key,as_of='2025-03-01')



def test_deletion_only_unlinks_simulated_namespace_and_preserves_public_sources(workspace):
    root,key=workspace;c,_,_=inspect(root,key);sources=dict(c['source_roots'])
    retire_batch(root,key);delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    c,e,s=inspect(root,key)
    assert s=='DELETED' and not (root/'deletion-manifest.json').exists()
    assert not any(root.glob('*batch')) and not any(root.glob('*outputs'))
    assert c['source_roots']==sources
    text=canonical(report(root,key,as_of='2025-03-01'))
    assert 'study-session:v1:' not in text and 'SIM-cccc' not in text and 'resume.key' not in text
    assert 'VERIFIED_LOCAL_NAMESPACE_UNLINK' in text and 'UNKNOWN_external_coordinator_obligation' in text


@pytest.mark.parametrize('stage',['rename_batch','rename_outputs'])
def test_interrupted_retirement_requires_explicit_exact_resume(workspace,monkeypatch,stage):
    import src.coordinator_lifecycle as module
    root,key=workspace
    def interrupt(s):
        if s==stage:raise InterruptedError('authored interruption')
    monkeypatch.setattr(module,'_after_boundary',interrupt)
    with pytest.raises(InterruptedError):retire_batch(root,key)
    assert inspect(root,key)[2]=='RETIRING'
    with pytest.raises(EvidenceError):report(root,key,as_of='2025-03-01')
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    retire(root,key,expected_tip=tip(root,key),as_of='2025-03-01',reason='WITHDRAWAL_REQUEST')
    assert inspect(root,key)[2]=='RETIRED'


@pytest.mark.parametrize('stage',['delete_begin','unlink','remove_root','delete_commit'])
def test_interrupted_deletion_retains_marker_and_resumes_only_manifest_survivors(workspace,monkeypatch,stage):
    import src.coordinator_lifecycle as module
    root,key=workspace;retire_batch(root,key);seen=[]
    def interrupt(s):
        if s==stage and not seen:seen.append(s);raise InterruptedError('authored interruption')
    monkeypatch.setattr(module,'_after_boundary',interrupt)
    with pytest.raises(InterruptedError):delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    state=inspect(root,key)[2]
    assert state in ('DELETING','DELETED')
    if state=='DELETING':
        with pytest.raises(EvidenceError):report(root,key,as_of='2025-03-01')
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    assert inspect(root,key)[2]=='DELETED' and not (root/'deletion-manifest.json').exists()


@pytest.mark.parametrize('attack',['wrong_key','missing_tip','stale_tip','symlink','dangling_symlink','hardlink',
    'changed_record','unknown_file','empty_directory','missing_record','copied_root','duplicate_event','truncated_events',
    'bad_mac','version','context','reordered_date','partial_file','root_permissions','file_permissions'])
def test_adversarial_lifecycle_fails_closed(workspace,tmp_path,attack):
    root,key=workspace
    if attack=='wrong_key':
        key=tmp_path/'wrong.key';key.write_text('f'*64+'\n');key.chmod(0o600)
    elif attack in ('missing_tip','stale_tip'):
        with pytest.raises(EvidenceError):retire(root,key,expected_tip=None if attack=='missing_tip' else 'f'*64,as_of='2025-03-01',reason='DRY_RUN')
        return
    elif attack=='copied_root':
        target=tmp_path/'copy';shutil.copytree(root,target);root=target;key=root/'coordinator.key'
    elif attack in ('symlink','dangling_symlink','hardlink'):
        file=next((root/'batch').glob('receipt-*.json'));file.unlink()
        outside=tmp_path/'unrelated';outside.write_text('untouched');outside.chmod(0o600)
        if attack=='hardlink':os.link(outside,file)
        else:file.symlink_to(outside if attack=='symlink' else tmp_path/'missing')
    elif attack=='changed_record':next((root/'batch').glob('receipt-*.json')).write_text('{}')
    elif attack=='unknown_file':(root/'extra.json').write_text('{}')
    elif attack=='empty_directory':os.mkdir(root/'batch'/'unregistered',0o700)
    elif attack=='missing_record':next((root/'batch').glob('receipt-*.json')).unlink()
    elif attack=='duplicate_event':shutil.copyfile(root/'lifecycle-000000.json',root/'lifecycle-000001.json')
    elif attack=='truncated_events':(root/'lifecycle-000000.json').unlink()
    elif attack=='bad_mac':mutate(root/'lifecycle-000000.json',lambda v:v.update(mac='f'*64))
    elif attack=='version':mutate(root/'lifecycle-000000.json',lambda v:v.update(schema_version=2))
    elif attack=='context':mutate(root/'coordinator-context.json',lambda v:v.update(task_set_digest='f'*64))
    elif attack=='reordered_date':mutate(root/'lifecycle-000000.json',lambda v:v.update(as_of='2024-01-01'))
    elif attack=='partial_file':(root/'lifecycle-000001.json.partial').write_text('{')
    elif attack=='root_permissions':root.chmod(0o755)
    elif attack=='file_permissions':(root/'coordinator-context.json').chmod(0o644)
    with pytest.raises((ValueError,TypeError,OSError)):inspect(root,key)
    if attack in ('symlink','dangling_symlink','hardlink'):assert outside.read_text()=='untouched'


def test_concurrent_coordinator_or_C5_writer_blocks_retirement(workspace):
    root,key=workspace;expected=tip(root,key)
    for path in (root,root/'batch'):
        with EvidenceRoot(path) as reader:
            fcntl.flock(reader.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with pytest.raises(BlockingIOError):retire(root,key,expected_tip=expected,as_of='2025-03-01',reason='DRY_RUN')
    assert inspect(root,key)[2]=='ACTIVE'


def test_expired_retention_deadlines_and_backups_remain_unknown(workspace):
    root,key=workspace
    with pytest.raises(EvidenceError):retire_batch(root,key,reason='RETENTION_EXPIRED',as_of='2025-03-30')
    retire_batch(root,key,reason='RETENTION_EXPIRED',as_of='2025-03-31')
    c,e,s=inspect(root,key);a=lifecycle_assessment(c,e,s,'2025-04-01')
    assert a['local_deletion_overdue'] and a['backup_deletion'].startswith('UNKNOWN')
    with pytest.raises(EvidenceError):delete(root,key,expected_tip=tip(root,key),as_of='2025-03-30')


@pytest.mark.parametrize('attack',['html','json','markdown','commit','truncated','rehashed'])
def test_tampered_generated_reports_fail_primary_recomputation(seed,tmp_path,attack):
    root,key,_=seed;out=tmp_path/'report';write_report(out,root,key,as_of='2025-03-01')
    names={'html':'coordinator.html','json':'coordinator.json','markdown':'coordinator.md','commit':'coordinator-report-commit.json'}
    if attack=='truncated':(out/'coordinator.md').unlink()
    elif attack=='rehashed':
        (out/'coordinator.html').write_text('<script>evil()</script>')
        mutate(out/'coordinator-report-commit.json',lambda v:v['files'].update({'coordinator.html':hashlib.sha256((out/'coordinator.html').read_bytes()).hexdigest()}))
    else:(out/names[attack]).write_text('tampered')
    with pytest.raises((ValueError,TypeError)):read_report(out,root,key,as_of='2025-03-01')


def test_repeated_report_digests_and_escaped_static_html(seed,tmp_path):
    root,key,_=seed
    a=write_report(tmp_path/'a',root,key,as_of='2025-03-01');b=write_report(tmp_path/'b',root,key,as_of='2025-03-01')
    assert a==b==digest(read_report(tmp_path/'a',root,key,as_of='2025-03-01'))
    text=html({'injection':'<script>alert(1)</script>'})
    assert '<script>' not in text and '&lt;script&gt;' in text and "default-src 'none'" in text
    assert all(report(root,key,as_of='2025-03-01')[k] is False for k in ('financial_eligibility_changed','frozen_readiness_upgrade','production_screening_authorized'))


@pytest.mark.parametrize('target',['inside_store','inside_report','traversal','source'])
def test_new_output_paths_cannot_modify_managed_evidence(seed,tmp_path,target):
    root,key,tasks=seed
    if target=='inside_store':path=root/'new-report'
    elif target=='source':path=Path(tasks.entries[0].source_root)/'new-report'
    elif target=='traversal':path=tmp_path/'..'/'..'/'etc'/'new-report'
    else:
        parent=tmp_path/'report';write_report(parent,root,key,as_of='2025-03-01');path=parent/'nested'
    with pytest.raises((ValueError,OSError)):write_report(path,root,key,as_of='2025-03-01')


def test_wrong_public_inventory_never_silently_substituted(seed,tmp_path):
    # Invoke the real frozen builder, not the explicit harness surrogate seam.
    with pytest.raises(EvidenceError):build_task_set(Path(seed[2].entries[0].source_root).parents[1],public_root=seed[2].entries[0].source_root)


@pytest.mark.parametrize('payload',[b'{',b'{"a":1,"a":2}',b'NaN',b'\xff'])
def test_malformed_lifecycle_json_never_treated_as_empty(workspace,payload):
    root,key=workspace;(root/'lifecycle-000000.json').write_bytes(payload)
    with pytest.raises((ValueError,TypeError)):inspect(root,key)


def test_changed_original_source_after_review_is_rejected_and_never_repaired(seed):
    root,key,tasks=seed;source=Path(tasks.entries[0].source_root)
    path=source/next(iter(inventory(source)))
    original=path.read_bytes()
    try:
        path.write_bytes(original+b' ')
        with pytest.raises(EvidenceError):report(root,key,as_of='2025-03-01')
    finally:path.write_bytes(original)
    assert inspect(root,key)[2]=='ACTIVE'


def test_changed_survivor_blocks_interrupted_deletion(workspace,monkeypatch):
    import src.coordinator_lifecycle as module
    root,key=workspace;retire_batch(root,key)
    def interrupt(stage):
        if stage=='delete_begin':raise InterruptedError('authored interruption')
    monkeypatch.setattr(module,'_after_boundary',interrupt)
    with pytest.raises(InterruptedError):delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    expected=tip(root,key)
    next((root/'retired-batch').glob('receipt-*.json')).write_text('{}')
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    with pytest.raises(EvidenceError):delete(root,key,expected_tip=expected,as_of='2025-03-01')


def test_withdrawal_deadline_and_unknown_backup_obligation_are_separate(workspace):
    root,key=workspace;retire_batch(root,key)
    c,e,s=inspect(root,key);a=lifecycle_assessment(c,e,s,'2025-04-02')
    assert a['local_deletion_due']=='2025-03-08'
    assert a['backup_deletion_due']=='2025-03-31'
    assert a['local_deletion_overdue'] and a['backup_deadline_passed_unresolved']
    delete(root,key,expected_tip=tip(root,key),as_of='2025-04-02')
    c,e,s=inspect(root,key);a=lifecycle_assessment(c,e,s,'2025-04-02')
    assert a['local_deletion_met_deadline'] is False
    assert a['backup_deletion'].startswith('UNKNOWN')


def test_capture_cannot_sweep_unrelated_output_file_into_deletion(seed,tmp_path):
    root=tmp_path/'private';key=new_workspace(root)
    for name in ('batch','outputs'):shutil.copytree(seed[0]/name,root/name)
    unrelated=root/'outputs'/'not-a-report';unrelated.write_text('must remain');unrelated.chmod(0o600)
    with pytest.raises(EvidenceError):capture(root,key,as_of='2025-03-01')
    assert unrelated.read_text()=='must remain' and not (root/'coordinator-context.json').exists()


def test_unretired_batch_cannot_be_deleted(workspace):
    root,key=workspace
    with pytest.raises(EvidenceError):delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    assert inspect(root,key)[2]=='ACTIVE'
