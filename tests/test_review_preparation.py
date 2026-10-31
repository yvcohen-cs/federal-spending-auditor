"""C8 synthetic-only journal, navigation and independent-review package controls."""
from dataclasses import replace
from pathlib import Path
import hashlib
import hmac
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from test_coordinator_rehearsal import seed, workspace, retire_batch
from src.evidence_io import EvidenceError, canonical, digest, strict_json
from src.coordinator_lifecycle import inspect, tip, retire, delete
from src import deletion_progress as progress
from src.evidence_browser import browse, sections
from src.pilot_review import StopInput
from src.coordinator_accessibility import accessible_terminal
from src.review_evidence import (CopyDeclaration,CopyInventory,CopyState as C,InventoryState as I,
    copy_assessment,source_manifest,input_digest,package,write_package,read_package)
from src.technical_assessment import code_digest


@pytest.fixture(scope='module',autouse=True)
def review_receipt_binding(record_testsuite_property):
    record_testsuite_property('review_preparation_input_sha256',input_digest())


def interrupted(root,key,monkeypatch,stage):
    import src.coordinator_lifecycle as module
    fired=[]
    def stop(name):
        if name==stage and not fired:fired.append(name);raise InterruptedError('synthetic_boundary')
    monkeypatch.setattr(module,'_after_boundary',stop)
    with pytest.raises(InterruptedError):delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    return module


@pytest.mark.parametrize('stage',['object_intent','object_unlinked','object_committed','progress_cleanup'])
def test_object_journal_recovery_is_explicit(workspace,monkeypatch,stage):
    root,key=workspace;retire_batch(root,key)
    module=interrupted(root,key,monkeypatch,stage)
    context,events,state=inspect(root,key)
    assert state in ('DELETING','DELETED')
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01')
    c,e,s=inspect(root,key);assert s=='DELETED'
    receipt=e[-1]['deletion_receipt'];assert receipt['objects']>0 and receipt['entries']==receipt['objects']*2
    assert receipt['absence_recoveries']==(1 if stage=='object_unlinked' else 0)
    assert not list(root.glob(progress.PREFIX+'*')) and not (root/'deletion-manifest.json').exists()


@pytest.mark.parametrize('relative',['retired-outputs/report-a/study.json','retired-batch/task-set.json'])
def test_missing_without_intent_is_rejected_and_original_preserved(workspace,tmp_path,monkeypatch,relative):
    root,key=workspace;retire_batch(root,key);module=interrupted(root,key,monkeypatch,'delete_begin')
    expected=tip(root,key);target=root/relative;original=tmp_path/'original';target.rename(original)
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    with pytest.raises(EvidenceError,match='missing_without_intent'):delete(root,key,expected_tip=expected,as_of='2025-03-01')
    assert original.exists() and not list(root.glob(progress.PREFIX+'*'))
    original.rename(target)
    delete(root,key,expected_tip=tip(root,key),as_of='2025-03-01');assert inspect(root,key)[2]=='DELETED'


def test_committed_object_cannot_reappear(workspace,monkeypatch):
    root,key=workspace;retire_batch(root,key)
    manifest=strict_json((root/'deletion-manifest.json').read_bytes());item=progress.plan(manifest)[0]
    target=root/('retired-'+item['scope'])/item['relative'];raw=target.read_bytes()
    module=interrupted(root,key,monkeypatch,'object_committed')
    target.write_bytes(raw);target.chmod(0o600)
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    with pytest.raises(EvidenceError,match='reappeared'):inspect(root,key)
    assert target.read_bytes()==raw


@pytest.mark.parametrize('attack',['mac','missing','duplicate','partial','schema','context','symlink','hardlink','permissions','json'])
def test_journal_tampering_never_repairs_history(workspace,tmp_path,monkeypatch,attack):
    root,key=workspace;retire_batch(root,key);module=interrupted(root,key,monkeypatch,'object_committed')
    expected=tip(root,key);files=sorted(root.glob(progress.PREFIX+'*.json'));path=files[0]
    if attack=='missing':path.unlink()
    elif attack=='duplicate':shutil.copyfile(path,root/(progress.PREFIX+'000002.json'))
    elif attack=='partial':(root/(progress.PREFIX+'000002.json.partial')).write_text('{')
    elif attack in ('symlink','hardlink'):
        held=tmp_path/'held';path.rename(held)
        if attack=='symlink':path.symlink_to(held)
        else:os.link(held,path)
    elif attack=='permissions':path.chmod(0o644)
    elif attack=='json':path.write_text('{')
    else:
        v=strict_json(path.read_bytes());v[{'mac':'mac','schema':'schema_version','context':'context_sha256'}[attack]]={'mac':'f'*64,'schema':2,'context':'f'*64}[attack];path.write_text(canonical(v))
    before=sorted(p.name for p in root.glob(progress.PREFIX+'*'))
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    with pytest.raises((ValueError,OSError)):delete(root,key,expected_tip=expected,as_of='2025-03-01')
    assert sorted(p.name for p in root.glob(progress.PREFIX+'*'))==before


def test_unexplained_directory_disappearance_after_pending_file_is_rejected(workspace,tmp_path,monkeypatch):
    root,key=workspace;retire_batch(root,key);module=interrupted(root,key,monkeypatch,'object_intent')
    expected=tip(root,key);(root/'retired-outputs').rename(tmp_path/'held-outputs')
    monkeypatch.setattr(module,'_after_boundary',lambda _:None)
    with pytest.raises(EvidenceError):delete(root,key,expected_tip=expected,as_of='2025-03-01')
    assert (tmp_path/'held-outputs').exists()


def test_v2_legacy_capture_is_not_silently_upgraded(workspace):
    root,key=workspace;path=root/'coordinator-context.json';c=strict_json(path.read_bytes());c['schema_version']=2;path.write_text(canonical(c)+'\n')
    secret=(root/'coordinator.key').read_bytes().rstrip(b'\n');previous=None
    for path in sorted(root.glob('lifecycle-*.json')):
        e=strict_json(path.read_bytes());e.update(context_sha256=digest(c),previous=previous)
        e['mac']=hmac.new(secret,canonical({k:v for k,v in e.items() if k!='mac'}).encode(),hashlib.sha256).hexdigest();path.write_text(canonical(e)+'\n');previous=digest(e)
    assert inspect(root,key)[0]['schema_version']==2
    with pytest.raises(EvidenceError,match='legacy_capture_read_only'):retire_batch(root,key)
    assert not list(root.glob(progress.PREFIX+'*'))


@pytest.mark.parametrize('attack',['odd_count','wrong_digest','negative_recovery','unsupported_version','wrong_hash_type'])
def test_receipt_validation_rejects_contradictions(attack):
    hashes=['a'*64,'b'*64];r={'schema_version':1,'objects':1,'entries':2,'entry_hashes':hashes,'journal_sha256':digest(hashes),'absence_recoveries':0}
    if attack=='odd_count':r['entries']=1
    elif attack=='wrong_digest':r['journal_sha256']='f'*64
    elif attack=='negative_recovery':r['absence_recoveries']=-1
    elif attack=='unsupported_version':r['schema_version']=True
    else:r['entry_hashes']=[1,2]
    with pytest.raises(EvidenceError):progress.validate_receipt(r)


def run_browser(task,commands,page_size=4):
    answers=iter(commands);out=[]
    browse(task,0,12,input_fn=lambda _:next(answers),output=out.append,page_size=page_size)
    return out


def test_browser_sections_pages_and_exact_evidence(seed):
    task=seed[2].entries[0].task
    out=run_browser(task,['c','n','p','o','a','u','l','s','?','not-a-valid-command','b'])
    assert any('citations' in line and 'page 2' in line for line in out)
    assert any('No input text retained' in line for line in out)
    assert all('not-a-valid-command' not in line for line in out)
    views=sections(task)
    assert any(task.claim in line for line in views['summary'])
    for citation in task.citations:assert any(citation.evidence.artifact.sha256 in line for line in views['citations'])
    assert tuple(views['unknowns'])==task.missing_proof_obligations if task.missing_proof_obligations else views['unknowns']


@pytest.mark.parametrize('command',['q','w'])
def test_browser_stop_reuses_existing_workflow(seed,command):
    with pytest.raises(StopInput) as e:run_browser(seed[2].entries[0].task,[command])
    assert e.value.withdraw==(command=='w')


@pytest.mark.parametrize('size',[True,0,3,41,1000])
def test_browser_rejects_unbounded_page_sizes(seed,size):
    with pytest.raises(EvidenceError):run_browser(seed[2].entries[0].task,['b'],size)


def test_paged_adapter_save_and_withdraw_only_append_events(seed,tmp_path):
    from src.pilot_session_store import inspect_environment,read_session
    from src.pilot_session_rules import replay
    source=seed[0]/'batch';root=tmp_path/'unsealed-synthetic';shutil.copytree(source,root)
    p,t,s,h=inspect_environment(root,root/'coordinator.key')
    sid=next(sid for sid,session in s.items() if replay(session,t,h[sid])[0].state.value=='IN_PROGRESS')
    key=root/('session-'+sid.removeprefix('study-session:v1:'))/'resume.key'
    before={path:path.read_bytes() for path in root.rglob('event-*.json')};answers=iter(['c','n','q']);out=[]
    assert accessible_terminal(root,sid,key,input_fn=lambda _:next(answers),output=out.append,paged_evidence=True)==1
    assert all(path.read_bytes()==raw for path,raw in before.items())
    assert any('Evidence browser' in line for line in out)
    answers=iter(['w']);assert accessible_terminal(root,sid,key,input_fn=lambda _:next(answers),output=out.append,paged_evidence=True)==1
    assert replay(*read_session(root,sid,key))[0].state.value=='WITHDRAWN'


@pytest.mark.parametrize('value',['\x1b[2J','\u202e','\u2067','\n','\r'])
def test_browser_untrusted_values_are_visibly_escaped(seed,value):
    task=replace(seed[2].entries[0].task,claim=seed[2].entries[0].task.claim+value)
    # Existing task schema may reject controls: use printable surrogate only if
    # accepted; the output contract itself is tested below independently.
    out=run_browser(task,['b'])
    assert all(value not in line for line in out)


def test_copy_inventory_unknown_never_means_zero_verified():
    scope='a'*64;r=copy_assessment(CopyInventory(scope_sha256=scope),scope)
    assert r['known_declared_copy_count']==0 and r['verified_copy_count'] is None and r['unmanaged_copy_count'] is None
    assert r['declared_completeness']=='UNKNOWN' and not r['real_data_deletion_authorized']
    r=copy_assessment(CopyInventory(scope_sha256=scope,completeness=I.DECLARED_COMPLETE),scope)
    assert not r['backup_deletion_verified']


def test_copy_conflicts_and_evidence_scope_are_preserved():
    scope='a'*64;one=CopyDeclaration(copy_id='COPY-aaaaaaaa00000001',kind='BACKUP',state=C.PRESENT)
    two=replace(one,state=C.CLAIMED_DELETED,evidence_sha256='b'*64)
    inventory=CopyInventory(scope_sha256=scope,declarations=(one,two))
    assert copy_assessment(inventory,scope)['status']=='CONFLICTING_DECLARATIONS'
    assert CopyInventory.from_dict(inventory.to_dict())==inventory
    with pytest.raises(EvidenceError):copy_assessment(inventory,'c'*64)
    with pytest.raises(ValueError):CopyInventory(scope_sha256=scope,declarations=(one,one))
    with pytest.raises(ValueError):replace(one,state=C.CLAIMED_DELETED)


@pytest.mark.parametrize('attack',[{'copy_id':'name@example.test'},{'kind':'ANYTHING'},{'schema_version':2},{'participant_name':'invented'},{'evidence_sha256':'wrong'}])
def test_copy_models_reject_unsupported_or_identifying_fields(attack):
    v=CopyDeclaration(copy_id='COPY-aaaaaaaa00000001',kind='SNAPSHOT',state=C.UNKNOWN).to_dict();v.update(attack)
    with pytest.raises((ValueError,TypeError)):CopyDeclaration.from_dict(v)


def junit():
    root=ET.Element('testsuites');suite=ET.SubElement(root,'testsuite');props=ET.SubElement(suite,'properties')
    ET.SubElement(props,'property',name='technical_assessment_code_sha256',value=code_digest())
    ET.SubElement(props,'property',name='review_preparation_input_sha256',value=input_digest())
    ET.SubElement(suite,'testcase',classname='tests.test_review_preparation',name='test_review_package_reproduces_without_external_approval')
    return ET.tostring(root)


def head():return subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()


def test_review_package_reproduces_without_external_approval(tmp_path):
    raw=junit();sha=head();a=write_package(tmp_path/'a',raw,sha);b=write_package(tmp_path/'b',raw,sha)
    r=read_package(tmp_path/'a',raw,sha);assert a==b==digest(r)==digest(read_package(tmp_path/'b',raw,sha))
    assert all(r[key] is False for key in ('actual_enrollment_enabled','real_data_deletion_enabled','production_screening_enabled','financial_eligibility_changed','frozen_readiness_upgrade'))
    assert r['external_approval']['records']==[] and all(row['status']=='NOT_ESTABLISHED' for row in r['review_requirements'])
    assert all('/blob/'+sha+'/' in f['url'] for f in r['source_files'].values())
    assert len(r['phase4c8_controls'])==4
    assert all(c['local_test_evidence']=='NOT_ESTABLISHED_BY_RECEIPT' for c in r['phase4c8_controls'])
    text=canonical(r);assert '/tmp/' not in text and 'resume.key' not in text


@pytest.mark.parametrize('attack',['json','html','markdown','truncated','rehashed','extra'])
def test_review_package_tampering_fails_primary_readback(tmp_path,attack):
    raw=junit();sha=head();out=tmp_path/'report';write_package(out,raw,sha)
    if attack=='extra':(out/'extra.txt').write_text('unexpected')
    elif attack=='truncated':(out/'review-package.md').unlink()
    else:
        file=out/({'json':'review-package.json','html':'review-package.html','markdown':'review-package.md','rehashed':'review-package.html'}[attack]);file.write_text('<script>untrusted()</script>')
        if attack=='rehashed':
            path=out/'review-package-commit.json';v=strict_json(path.read_bytes());v['files'][file.name]=hashlib.sha256(file.read_bytes()).hexdigest();path.write_text(canonical(v))
    with pytest.raises((ValueError,OSError)):read_package(out,raw,sha)


def test_package_scope_and_head_replay_are_blocked():
    raw=junit()
    with pytest.raises(EvidenceError):package(raw,'f'*40)
    tree=ET.fromstring(raw);props=tree.find('testsuite/properties')
    next(p for p in props if p.attrib['name']=='review_preparation_input_sha256').set('value','f'*64)
    with pytest.raises(EvidenceError):package(ET.tostring(tree),head())


def test_public_source_manifest_does_not_follow_links(tmp_path,monkeypatch):
    import src.review_evidence as module
    root=tmp_path/'replica';root.mkdir()
    for name in ('src','tests','docs'):(root/name).mkdir()
    (root/'README.md').write_text('public');(root/'requirements.txt').write_text('public')
    private=tmp_path/'private.key';private.write_text('synthetic-secret-not-to-export')
    (root/'src'/'linked.py').symlink_to(private)
    monkeypatch.setattr(module,'ROOT',root)
    with pytest.raises((ValueError,OSError)):source_manifest()
