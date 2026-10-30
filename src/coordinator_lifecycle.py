"""Bounded simulated-batch retirement/deletion rehearsal, not secure erasure.

Only a dedicated C6 root and its captured C5 batch/outputs can be affected.
Cooperative POSIX locks exclude tool writers; same-UID/privileged coherent
rewrites and previously copied stores are explicitly outside this guarantee.
"""
from contextlib import contextmanager
from datetime import timedelta
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat

from .evidence_io import EvidenceError, EvidenceRoot, _directory, canonical, digest, strict_json
from .review_packet_io import atomic_create, new_directory
from .pilot_session_store import private_location, _private_fd, _authenticate, inspect_environment
from .pilot_session_models import MeasurementKind as M
from .pilot_study_reporting import read_report
from .review_validation_tasks import inventory
from .coordinator_governance import protocol, day

LIMIT = 64 * 1024 * 1024
STATES = {'CAPTURE': ('NEW', 'ACTIVE'), 'RETIRE_BEGIN': ('ACTIVE', 'RETIRING'),
          'RETIRE_COMMIT': ('RETIRING', 'RETIRED'), 'DELETE_BEGIN': ('RETIRED', 'DELETING'),
          'DELETE_COMMIT': ('DELETING', 'DELETED')}
REASONS = ('DRY_RUN', 'WITHDRAWAL_REQUEST', 'RETENTION_EXPIRED')


def _write(root, name, value):
    atomic_create(root.fd, name, (canonical(value) + '\n').encode())


def new_workspace(path):
    target = private_location(path)
    if any((p / 'coordinator-context.json').exists() or (p / 'coordinator.key').exists()
           for p in (target,) + tuple(target.parents)):
        raise EvidenceError('coordinator_workspace_inside_managed_root')
    new_directory(target)
    with EvidenceRoot(target) as root:
        atomic_create(root.fd, 'coordinator.key', secrets.token_hex(32).encode() + b'\n')
    return target / 'coordinator.key'


def _tree(path, *, bind_identity=False):
    if not os.path.lexists(path):
        return None
    with EvidenceRoot(path, max_bytes=LIMIT, max_total_bytes=LIMIT, max_files=4096) as root:
        _private_fd(root.fd)
        result = {}
        def identity(st):
            return [st.st_dev, st.st_ino, 'directory' if stat.S_ISDIR(st.st_mode) else 'file']
        if bind_identity: result['identity:.'] = identity(os.fstat(root.fd))
        for name in root.discover():
            s = os.stat(name, dir_fd=root.fd, follow_symlinks=False)
            if s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o600:
                raise EvidenceError('private_capture_permissions')
            result[name] = root.read(name).byte_sha256
            if bind_identity: result['identity:'+name] = identity(s)
        # Directories are also checked, including empty directories.
        def directories(fd,prefix=""):
            for name in os.listdir(fd):
                s = os.stat(name, dir_fd=fd, follow_symlinks=False)
                if stat.S_ISDIR(s.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    try:
                        result["directory:"+prefix+name]="DIRECTORY_0700"
                        if bind_identity: result["identity:"+prefix+name] = identity(os.fstat(child))
                        _private_fd(child); directories(child,prefix+name+"/")
                    finally:
                        os.close(child)
        directories(root.fd)
        return result


def _event(root, context, secret, events, action, as_of, reason):
    value = {'schema_type': 'CoordinatorLifecycleEvent', 'schema_version': 1,
        'sequence': len(events), 'previous': digest(events[-1]) if events else None,
        'context_sha256': digest(context), 'action': action, 'state': STATES[action][1],
        'as_of': as_of, 'reason': reason}
    value['mac'] = hmac.new(secret, canonical(value).encode(), hashlib.sha256).hexdigest()
    _write(root, f'lifecycle-{len(events):06d}.json', value)
    return digest(value)


def capture(path, key, *, as_of):
    """Seal only a completely simulated mixed-plan batch and two valid reports."""
    day(as_of); protocol()
    with EvidenceRoot(path, max_bytes=LIMIT, max_total_bytes=2*LIMIT, max_files=8192) as root:
        fcntl.flock(root.fd, fcntl.LOCK_EX | fcntl.LOCK_NB); _private_fd(root.fd)
        secret = root.read('coordinator.key').data.rstrip(b'\n')
        if re.fullmatch(b'[a-f0-9]{64}', secret) is None:
            raise EvidenceError('invalid_coordinator_key')
        _authenticate(key, hashlib.sha256(secret).hexdigest())
        if set(os.listdir(root.fd)) != {'coordinator.key', 'batch', 'outputs'}:
            raise EvidenceError('exact_new_rehearsal_workspace_required')
        batch = Path(path) / 'batch'; c5key = batch / 'coordinator.key'
        if set(os.listdir(Path(path)/'outputs')) != {'report-a','report-b'}:
            raise EvidenceError('only_exact_captured_reports_allowed')
        with EvidenceRoot(batch) as batch_guard:
            fcntl.flock(batch_guard.fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
            p, tasks, sessions, histories = inspect_environment(batch, c5key)
            if (p.measurement_kind is not M.SIMULATED or p.selection_version != 'pilot-mixed-v1'
                    or len(tasks.entries) != 12 or len(sessions) != 4
                    or any(s.protocol.measurement_kind is not M.SIMULATED for s in sessions.values())):
                raise EvidenceError('only_exact_simulated_twelve_task_rehearsal_can_be_retired')
            a = read_report(Path(path)/'outputs'/'report-a', batch, c5key)
            b = read_report(Path(path)/'outputs'/'report-b', batch, c5key)
            if a != b or a['actual_human_study_status'] != 'NOT_CONDUCTED':
                raise EvidenceError('rehearsal_report_conflict')
            expected = protocol()['rehearsal']
            if (a['session_states'] != {'NOT_STARTED':0,'IN_PROGRESS':1,'COMPLETED':1,'WITHDRAWN':1,'INVALIDATED':1}
                    or a['synthetic_study_observations']['metrics']['tasks_completed'] != expected['eligible_responses']
                    or a['excluded_sessions']['excluded_response_count'] != 1):
                raise EvidenceError('exact_simulated_session_outcomes_required')
            from .pilot_session_models import SessionAction as A
            if not any(any(e.action is A.RESUME for e in ev) and any(e.action is A.SUSPEND for e in ev) for ev in histories.values()):
                raise EvidenceError('pause_and_resume_rehearsal_required')
            manifest = {'batch': _tree(batch, bind_identity=True), 'outputs': _tree(Path(path)/'outputs', bind_identity=True)}
            if not manifest['batch'] or not manifest['outputs']:
                raise EvidenceError('complete_batch_capture_required')
            s = os.fstat(root.fd)
            context = {'schema_type': 'CoordinatorLifecycleContext', 'schema_version': 2,
                'root_device': s.st_dev, 'root_inode': s.st_ino,
                'coordinator_key_sha256': hashlib.sha256(secret).hexdigest(),
                'manifest_sha256': digest(manifest), 'closed_on': as_of,
                'study_protocol': p.to_dict(), 'task_set_digest': tasks.task_set_digest,
                'source_roots': {e.source_root: digest(strict_json(e.source_inventory_json.encode())) for e in tasks.entries},
                'captured_report': a, 'captured_report_sha256': digest(a)}
            _write(root, 'deletion-manifest.json', manifest)
            _write(root, 'coordinator-context.json', context)
            _event(root, context, secret, [], 'CAPTURE', as_of, 'DRY_RUN')
    return digest(context)



def _require_binding(context):
    if context['schema_version'] != 2:
        raise EvidenceError('legacy_capture_read_only_new_simulated_run_required')


def _validate_manifest(manifest, version):
    from .evidence_io import parts
    for entries in manifest.values():
        if not isinstance(entries,dict) or not entries:raise EvidenceError('invalid_target_manifest')
        files=set();directories={'.'};identities=set()
        for name,value in entries.items():
            if name.startswith('identity:'):
                path=name[len('identity:'):]
                if path!='.':parts(path)
                if (version!=2 or not isinstance(value,list) or len(value)!=3
                        or any(type(n) is not int or n<0 for n in value[:2]) or value[2] not in ('file','directory')):
                    raise EvidenceError('invalid_target_identity')
                identities.add(path)
            elif name.startswith('directory:'):
                path=name[len('directory:'):];parts(path)
                if value!='DIRECTORY_0700':raise EvidenceError('invalid_directory_manifest')
                directories.add(path)
            else:
                parts(name)
                if not isinstance(value,str) or re.fullmatch('[a-f0-9]{64}',value) is None:raise EvidenceError('invalid_file_manifest')
                files.add(name)
        if version==2:
            if identities!=files|directories:raise EvidenceError('incomplete_target_identity_binding')
            for path in identities:
                if entries['identity:'+path][2]!=('directory' if path in directories else 'file'):
                    raise EvidenceError('contradictory_target_kind')


def _load(root, key, expected_tip=None):
    _private_fd(root.fd); protocol()
    context = strict_json(root.read('coordinator-context.json').data)
    required = {'schema_type','schema_version','root_device','root_inode','coordinator_key_sha256',
                'manifest_sha256','closed_on','study_protocol','task_set_digest','source_roots',
                'captured_report','captured_report_sha256'}
    s = os.fstat(root.fd)
    if (set(context) != required or context['schema_type'] != 'CoordinatorLifecycleContext'
            or type(context['schema_version']) is not int or context['schema_version'] not in (1, 2)
            or (context['root_device'],context['root_inode']) != (s.st_dev,s.st_ino)):
        raise EvidenceError('copied_or_invalid_coordinator_context')
    secret = _authenticate(key, context['coordinator_key_sha256'])
    if root.read('coordinator.key').data != secret + b'\n':
        raise EvidenceError('coordinator_capability_changed')
    from .pilot_session_models import StudyProtocol
    p = StudyProtocol.from_dict(context['study_protocol'])
    if p.measurement_kind is not M.SIMULATED or p.selection_version != 'pilot-mixed-v1' or p.task_set_digest != context['task_set_digest']:
        raise EvidenceError('simulated_context_required')
    if digest(context['captured_report']) != context['captured_report_sha256']:
        raise EvidenceError('captured_report_changed')
    names = sorted(n for n in os.listdir(root.fd) if n.startswith('lifecycle-'))
    if len(names)>5 or names != [f'lifecycle-{i:06d}.json' for i in range(len(names))] or not names:
        raise EvidenceError('missing_or_reordered_lifecycle_history')
    events=[]; state='NEW'; previous=None; last_day=None
    for i,name in enumerate(names):
        e = strict_json(root.read(name).data)
        if set(e) != {'schema_type','schema_version','sequence','previous','context_sha256','action','state','as_of','reason','mac'}:
            raise EvidenceError('invalid_lifecycle_event')
        signed={k:v for k,v in e.items() if k!='mac'}
        if (e['schema_type']!='CoordinatorLifecycleEvent' or type(e['schema_version']) is not int or e['schema_version']!=1
                or type(e['sequence']) is not int or e['sequence']!=i or e['previous']!=previous
                or e['context_sha256']!=digest(context) or e['action'] not in STATES
                or STATES[e['action']]!=(state,e['state']) or e['reason'] not in REASONS
                or not isinstance(e['mac'],str) or not hmac.compare_digest(e['mac'],hmac.new(secret,canonical(signed).encode(),hashlib.sha256).hexdigest())):
            raise EvidenceError('forged_replayed_or_unauthorized_lifecycle_event')
        current=day(e['as_of'])
        if last_day is not None and current<last_day:
            raise EvidenceError('reordered_lifecycle_dates')
        if len(events)>1 and e['reason']!=events[1]['reason']:
            raise EvidenceError('lifecycle_reason_changed')
        state=e['state'];previous=digest(e);last_day=current;events.append(e)
    if expected_tip is not None and expected_tip!=previous:
        raise EvidenceError('stale_coordinator_tip')
    allowed={'coordinator.key','coordinator-context.json','deletion-manifest.json'}|set(names)|{'batch','outputs','retired-batch','retired-outputs'}
    if set(os.listdir(root.fd))-allowed:
        raise EvidenceError('unexpected_coordinator_artifact')
    manifest=None
    if 'deletion-manifest.json' in os.listdir(root.fd):
        manifest=strict_json(root.read('deletion-manifest.json').data)
        if digest(manifest)!=context['manifest_sha256'] or set(manifest)!={'batch','outputs'}:
            raise EvidenceError('deletion_manifest_changed')
        _validate_manifest(manifest, context['schema_version'])
    elif state!='DELETED':
        raise EvidenceError('missing_deletion_manifest')
    # Never allow a local tombstone to silently resume or count primary data.
    if state=='DELETED' and any(os.path.lexists(Path(root.path)/n) for n in ('batch','outputs','retired-batch','retired-outputs')):
        raise EvidenceError('deleted_batch_reappeared')
    for name in os.listdir(root.fd):
        if name not in ('batch','outputs','retired-batch','retired-outputs'):
            st=os.stat(name,dir_fd=root.fd,follow_symlinks=False)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)!=0o600:
                raise EvidenceError('private_control_permissions_or_link')
    return context,secret,events,state,manifest


@contextmanager
def locked(path,key,expected_tip=None):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=4*LIMIT,max_files=8192) as root:
        fcntl.flock(root.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield root,_load(root,key,expected_tip)


def _verify_trees(path,manifest,*,partial=False):
    locations={}
    for name,expected in manifest.items():
        candidates=[Path(path)/n for n in (name,'retired-'+name) if os.path.lexists(Path(path)/n)]
        if len(candidates)>1 or not partial and not candidates:
            raise EvidenceError('duplicate_or_missing_batch_namespace')
        if not candidates:continue
        actual=_tree(candidates[0], bind_identity='identity:.' in expected)
        if (not partial and actual!=expected or partial and any(expected.get(n)!=sha for n,sha in actual.items())):
            raise EvidenceError('changed_or_unexpected_private_evidence')
        locations[name]=candidates[0]
    return locations


def inspect(path,key):
    with locked(path,key) as (root,loaded):
        context,_,events,state,manifest=loaded
        if state!='DELETED':
            locations=_verify_trees(path,manifest,partial=state=='DELETING')
            if state=='ACTIVE' and any(p.name!=n for n,p in locations.items()) or state in ('RETIRED','DELETING') and any(p.name!='retired-'+n for n,p in locations.items()):
                raise EvidenceError('lifecycle_namespace_conflict')
        # Public primary evidence is always rechecked, including after deletion.
        for source,expected in context['source_roots'].items():
            if digest(inventory(source))!=expected:raise EvidenceError('rehearsal_source_changed')
        return context,events,state


def tip(path,key):
    return digest(inspect(path,key)[1][-1])


def retire(path,key,*,expected_tip,as_of,reason):
    day(as_of)
    if not isinstance(expected_tip,str) or re.fullmatch('[a-f0-9]{64}',expected_tip) is None:raise EvidenceError('exact_coordinator_tip_required')
    if reason not in REASONS:raise EvidenceError('bounded_retirement_reason_required')
    with locked(path,key,expected_tip) as (root,loaded):
        context,secret,events,state,manifest=loaded
        _require_binding(context)
        if day(as_of)<day(events[-1]['as_of']):raise EvidenceError('retirement_date_reordered')
        if state not in ('ACTIVE','RETIRING'):raise EvidenceError('batch_not_active_or_interrupted_retirement')
        if state=='RETIRING' and (reason!=events[-1]['reason'] or as_of!=events[-1]['as_of']):raise EvidenceError('exact_retirement_resume_required')
        if reason=='RETENTION_EXPIRED' and day(as_of)<day(context['closed_on'])+timedelta(days=30):
            raise EvidenceError('raw_retention_not_expired')
        locations=_verify_trees(path,manifest)
        if state=='ACTIVE' and any(p.name!=n for n,p in locations.items()):raise EvidenceError('active_namespace_conflict')
        with EvidenceRoot(locations['batch']) as batch:
            fcntl.flock(batch.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if state=='ACTIVE':
                _after_boundary('before_retire_begin')
                # Recheck after acquiring the C5 writer lock.
                _verify_trees(path,manifest)
                _event(root,context,secret,events,'RETIRE_BEGIN',as_of,reason)
                events=_load(root,key)[2];_after_boundary('after_retire_begin')
            for name in ('batch','outputs'):
                if locations[name].name==name:
                    os.rename(name,'retired-'+name,src_dir_fd=root.fd,dst_dir_fd=root.fd)
                    os.fsync(root.fd)
                    _after_boundary('rename_'+name)
            _verify_trees(path,manifest)
            return _event(root,context,secret,events,'RETIRE_COMMIT',as_of,reason)


def _after_boundary(stage):
    """Test interruption seam. Never catches or repairs an interrupted mutation."""


def _remove(path,expected):
    actual=_tree(path, bind_identity='identity:.' in expected)
    if actual is None:return
    if any(expected.get(n)!=sha for n,sha in actual.items()):raise EvidenceError('delete_survivor_changed')
    for name in sorted(n for n in actual if not n.startswith(("directory:", "identity:"))):
        target=Path(path)/name
        parent=_directory(target.parent)
        try:
            if 'identity:.' in expected:
                rel=target.parent.relative_to(path).as_posix()
                st=os.fstat(parent)
                if [st.st_dev,st.st_ino,'directory']!=expected['identity:'+rel]:raise EvidenceError('delete_parent_replaced')
            with EvidenceRoot(target.parent,max_bytes=LIMIT) as reader:
                if reader.read(target.name).byte_sha256!=expected[name]:raise EvidenceError('delete_target_changed')
                if 'identity:.' in expected:
                    st=os.stat(target.name,dir_fd=parent,follow_symlinks=False)
                    if [st.st_dev,st.st_ino,'file']!=expected['identity:'+name]:raise EvidenceError('delete_object_replaced')
            os.unlink(target.name,dir_fd=parent);os.fsync(parent)
        finally:os.close(parent)
        _after_boundary('unlink')
    # Only now remove empty directories, descriptor-relative and without following links.
    def empty(fd,prefix=""):
        if "identity:." in expected:
            st=os.fstat(fd)
            if [st.st_dev,st.st_ino,"directory"]!=expected["identity:"+(prefix.rstrip("/") or ".")]:raise EvidenceError("delete_directory_replaced")
        for name in os.listdir(fd):
            s=os.stat(name,dir_fd=fd,follow_symlinks=False)
            if not stat.S_ISDIR(s.st_mode):raise EvidenceError('unexpected_deletion_survivor')
            child=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            try:_private_fd(child);empty(child,prefix+name+"/")
            finally:os.close(child)
            _after_boundary('before_rmdir')
            if 'identity:.' in expected:
                st=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if [st.st_dev,st.st_ino,'directory']!=expected['identity:'+prefix+name]:raise EvidenceError('rmdir_target_replaced')
            os.rmdir(name,dir_fd=fd);os.fsync(fd)
            _after_boundary('after_rmdir')
    fd=_directory(path)
    try:empty(fd)
    finally:os.close(fd)
    parent=_directory(Path(path).parent)
    try:
        if 'identity:.' in expected:
            st=os.stat(Path(path).name,dir_fd=parent,follow_symlinks=False)
            if [st.st_dev,st.st_ino,'directory']!=expected['identity:.']:raise EvidenceError('delete_root_replaced')
        os.rmdir(Path(path).name,dir_fd=parent);os.fsync(parent)
    finally:os.close(parent)
    _after_boundary('remove_root')


def delete(path,key,*,expected_tip,as_of):
    """Unlink only manifest-bound SIMULATED data; allow exact interrupted survivors."""
    day(as_of)
    if not isinstance(expected_tip,str) or re.fullmatch('[a-f0-9]{64}',expected_tip) is None:raise EvidenceError('exact_coordinator_tip_required')
    with locked(path,key,expected_tip) as (root,loaded):
        context,secret,events,state,manifest=loaded
        if state!='DELETED':_require_binding(context)
        if state not in ('RETIRED','DELETING','DELETED'):raise EvidenceError('retirement_required_before_deletion')
        if day(as_of)<day(events[-1]['as_of']):raise EvidenceError('deletion_date_reordered')
        if state=='DELETED':
            if manifest is not None:os.unlink('deletion-manifest.json',dir_fd=root.fd);os.fsync(root.fd)
            return digest(events[-1])
        if state=='DELETING' and as_of!=events[-1]['as_of']:raise EvidenceError('exact_deletion_resume_required')
        locations=_verify_trees(path,manifest,partial=state=='DELETING')
        if any(p.name in ('batch','outputs') for p in locations.values()):raise EvidenceError('retirement_namespace_incomplete')
        # C5 writers use this same directory lock, even on the retired path.
        batch_fd=_directory(Path(path)/'retired-batch') if 'batch' in locations else None
        try:
            if batch_fd is not None:fcntl.flock(batch_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            _verify_trees(path,manifest,partial=state=='DELETING')
            if state=='RETIRED':
                _after_boundary('before_delete_begin')
                _event(root,context,secret,events,'DELETE_BEGIN',as_of,events[-1]['reason'])
                events=_load(root,key)[2];_after_boundary('delete_begin')
            for name in ('outputs','batch'):_remove(Path(path)/('retired-'+name),manifest[name])
            value=_event(root,context,secret,events,'DELETE_COMMIT',as_of,events[-1]['reason'])
            _after_boundary('delete_commit')
            os.unlink('deletion-manifest.json',dir_fd=root.fd);os.fsync(root.fd)
            return value
        finally:
            if batch_fd is not None:os.close(batch_fd)


def lifecycle_assessment(context,events,state,as_of):
    today=day(as_of)
    if today<day(events[-1]['as_of']):raise EvidenceError('assessment_predates_lifecycle')
    request=next((e for e in events if e['action']=='RETIRE_BEGIN'),None)
    request_day=day(request['as_of']) if request else None
    local_due=request_day+timedelta(days=7) if request and request['reason']=='WITHDRAWAL_REQUEST' else day(context['closed_on'])+timedelta(days=30)
    return {'state':state,'reports_invalidated':state!='ACTIVE',
        'local_deletion':'VERIFIED_LOCAL_NAMESPACE_UNLINK' if state=='DELETED' else 'INCOMPLETE' if state=='DELETING' else 'NOT_DELETED',
        'local_deletion_met_deadline':day(events[-1]['as_of'])<=local_due if state=='DELETED' else None,
        'local_deletion_due':local_due.isoformat(),'local_deletion_overdue':state!='DELETED' and today>local_due,
        'backup_deletion_due':(request_day+timedelta(days=30)).isoformat() if request_day else None,
        'backup_deadline_passed_unresolved':today>request_day+timedelta(days=30) if request_day else None,
        'backup_deletion':'UNKNOWN_external_coordinator_obligation_no_backup_inventory',
        'retained_control_data':'aggregate_simulation_snapshot_digests_dates_no_session_labels_or_event_histories',
        'secure_erasure':'NOT_ESTABLISHED','copied_stores_revoked':'NOT_ESTABLISHED',
        'identity_authentication':'NOT_ESTABLISHED','legacy_C5_direct_access_revoked_globally':False,
        'limitations':['Previously copied stores/backups are not discovered or revoked.',
            'Unlink is not secure erasure; filesystem snapshots, SSD behavior and backups are outside guarantees.',
            'Cooperative locks do not stop same-UID or privileged writers.',
            'Direct legacy C5 commands are not changed; retired paths and C6 gates provide local scope only.',
            'This deletion rehearsal supports simulated data only; real-data deletion requires separate review.']}
