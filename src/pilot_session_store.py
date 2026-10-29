"""Private POSIX capability-gated append-only sessions, never inside git/evidence.

HMAC receipts bind local write authority, not participant identity. Same-UID or
privileged coherent rewrites remain outside local storage assurance.
"""
import fcntl
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import stat

from .evidence_io import EvidenceError,EvidenceRoot,canonical,digest,strict_json
from .review_packet_io import atomic_create,new_directory
from .review_validation_tasks import check_new_location
from .pilot_session_models import (PilotTaskSet,StudyProtocol,StudySession,SessionEvent,SessionAction as A,
    SessionState as S,ConsentState as C,MeasurementKind as M,StudyAuthorization)
from .pilot_taskset import preparation,governance_sha,pin_sources,revalidate_tasks
from .pilot_session_rules import replay

LIMIT=32*1024*1024


def private_location(path):
    target=check_new_location(path,study=True)
    for ancestor in (target,)+tuple(target.parents):
        if (ancestor/'environment.json').exists() or (ancestor/'study-report-commit.json').exists():
            raise EvidenceError('new_private_store_inside_existing_study_or_report')
        marker=ancestor/'.git'
        # Managed runtimes may expose empty .git sentinel directories outside
        # repositories. A gitdir file or a directory with HEAD is a worktree.
        if marker.is_file() or (marker/'HEAD').exists():raise EvidenceError('private_sessions_must_be_outside_git_worktrees')
    return target


def _private_fd(fd):
    s=os.fstat(fd)
    if s.st_uid!=os.getuid() or s.st_mode&0o077:raise EvidenceError('owner_only_private_storage_required')


def _key(path):
    target=Path(path).absolute()
    with EvidenceRoot(target.parent,max_bytes=128,max_total_bytes=256) as root:
        _private_fd(root.fd);s=os.stat(target.name,dir_fd=root.fd,follow_symlinks=False)
        if s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600:raise EvidenceError('private_capability_file_required')
        raw=root.read(target.name).data
        if re.fullmatch(b'[a-f0-9]{64}\n',raw) is None:raise EvidenceError('invalid_local_capability')
        return raw.rstrip(b'\n')


def _authenticate(path,expected):
    value=_key(path)
    if not hmac.compare_digest(hashlib.sha256(value).hexdigest(),expected):raise EvidenceError('unauthorized_local_study_access')
    return value


def _write(root,name,value):
    atomic_create(root.fd,name,(canonical(value)+'\n').encode())


def _receipt(root,secret,index,previous,session,context_sha,event=None):
    value={'schema_type':'StudyReceipt','schema_version':1,'sequence':index,'previous_receipt_id':previous,
        'session_id':session.session_id,'context_sha256':context_sha,'event_id':event.event_id if event else None,
        'event_sequence':event.sequence if event else -1}
    value['mac']=hmac.new(secret,canonical(value).encode(),hashlib.sha256).hexdigest()
    _write(root,f'receipt-{index:06d}.json',value)


def _load(root):
    _private_fd(root.fd);preparation()
    data={n:root.read(n) for n in root.discover()}
    if sum(len(s.data) for s in data.values())>LIMIT:raise EvidenceError('private_study_store_limit')
    for n in data:
        s=os.stat(n,dir_fd=root.fd,follow_symlinks=False)
        if s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600:raise EvidenceError('private_record_permissions_required')
    env=strict_json(data['environment.json'].data)
    if set(env)!={'schema_type','schema_version','protocol','task_set_file_sha256','coordinator_capability_sha256'} or env['schema_type']!='PrivateStudyEnvironment' or type(env['schema_version']) is not int or env['schema_version']!=1:
        raise EvidenceError('invalid_study_environment')
    p=StudyProtocol.from_dict(env['protocol']);tasks=PilotTaskSet.from_dict(strict_json(data['task-set.json'].data))
    if (data['task-set.json'].byte_sha256!=env['task_set_file_sha256'] or p.task_set_digest!=tasks.task_set_digest
            or p.evidence_inventory_digest!=tasks.evidence_inventory_digest or p.selection_version!=tasks.selection_version or p.governance_sha256!=governance_sha()):
        raise EvidenceError('private_task_set_protocol_or_governance_changed')
    secret=data['coordinator.key'].data.rstrip(b'\n')
    if re.fullmatch(b'[a-f0-9]{64}',secret) is None or hashlib.sha256(secret).hexdigest()!=env['coordinator_capability_sha256']:
        raise EvidenceError('coordinator_capability_conflict')
    names=set(data);required={'environment.json','task-set.json','coordinator.key'}
    context_names=sorted(n for n in names if re.fullmatch(r'session-[a-f0-9]{64}/context.json',n))
    if len(context_names)>4:raise EvidenceError('pilot_session_limit')
    sessions={};events={};labels=set();context_hashes={};dirname={}
    for name in context_names:
        directory=name.split('/')[0]
        with EvidenceRoot(Path(root.path)/directory,max_bytes=128,max_total_bytes=128) as child:_private_fd(child.fd)
        session=StudySession.from_dict(strict_json(data[name].data));sid=session.session_id
        if session.protocol!=p or directory!='session-'+sid.removeprefix('study-session:v1:') or sid in sessions or session.pseudonym in labels:
            raise EvidenceError('duplicate_or_conflicting_session_identity')
        key_name=directory+'/resume.key';key=data[key_name].data.rstrip(b'\n')
        if re.fullmatch(b'[a-f0-9]{64}',key) is None or hashlib.sha256(key).hexdigest()!=session.resume_capability_sha256:
            raise EvidenceError('resume_capability_conflict')
        ev_names=sorted(n for n in names if n.startswith(directory+'/event-'))
        if ev_names!=[directory+f'/event-{i:06d}.json' for i in range(len(ev_names))]:raise EvidenceError('truncated_partial_or_extra_session_events')
        history=tuple(SessionEvent.from_dict(strict_json(data[n].data)) for n in ev_names)
        replay(session,tasks,history)
        sessions[sid]=session;events[sid]=history;labels.add(session.pseudonym);context_hashes[sid]=data[name].byte_sha256;dirname[sid]=directory
        required.update((name,key_name));required.update(ev_names)
    receipt_names=sorted(n for n in names if n.startswith('receipt-'))
    if receipt_names!=[f'receipt-{i:06d}.json' for i in range(len(receipt_names))]:raise EvidenceError('truncated_or_extra_study_receipts')
    tips={};previous=None;counts={}
    for i,name in enumerate(receipt_names):
        value=strict_json(data[name].data)
        if not isinstance(value,dict) or set(value)!={'schema_type','schema_version','sequence','previous_receipt_id','session_id','context_sha256','event_id','event_sequence','mac'}:
            raise EvidenceError('invalid_study_receipt')
        signed={k:v for k,v in value.items() if k!='mac'}
        if (not isinstance(value['mac'],str) or not hmac.compare_digest(value['mac'],hmac.new(secret,canonical(signed).encode(),hashlib.sha256).hexdigest())
                or value['schema_type']!='StudyReceipt' or type(value['schema_version']) is not int or value['schema_version']!=1
                or type(value['sequence']) is not int or value['sequence']!=i or value['previous_receipt_id']!=previous):
            raise EvidenceError('forged_or_reordered_study_receipt')
        sid=value['session_id'];seq=value['event_sequence']
        if sid not in sessions or value['context_sha256']!=context_hashes[sid] or type(seq) is not int:
            raise EvidenceError('receipt_session_context_conflict')
        expected=counts.get(sid,-1)
        if seq!=expected or seq==-1 and value['event_id'] is not None or seq>=0 and (seq>=len(events[sid]) or value['event_id']!=events[sid][seq].event_id):
            raise EvidenceError('session_log_receipt_boundary_conflict')
        counts[sid]=expected+1;tips[sid]=value['event_id'];previous=digest(value)
    if set(counts)!=set(sessions) or any(counts[sid]!=len(events[sid]) for sid in sessions):
        raise EvidenceError('truncated_session_log_or_uncommitted_publication')
    required.update(receipt_names)
    if required!=names:raise EvidenceError('unexpected_private_study_artifacts')
    if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in data.items()}:
        raise EvidenceError('private_study_store_changed')
    return p,tasks,sessions,events,env,secret,receipt_names,previous,dirname


def create_environment(path,task_set,protocol):
    revalidate_tasks(task_set)
    if (protocol.task_set_digest!=task_set.task_set_digest or protocol.evidence_inventory_digest!=task_set.evidence_inventory_digest
            or protocol.selection_version!=task_set.selection_version or protocol.governance_sha256!=governance_sha()):raise EvidenceError('exact_study_protocol_required')
    target=private_location(path);new_directory(target)
    with EvidenceRoot(target,max_bytes=LIMIT,max_total_bytes=2*LIMIT,max_files=4096) as root:
        fcntl.flock(root.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        secret=secrets.token_hex(32).encode();raw=(task_set.to_json()+'\n').encode()
        atomic_create(root.fd,'coordinator.key',secret+b'\n');atomic_create(root.fd,'task-set.json',raw)
        _write(root,'environment.json',{'schema_type':'PrivateStudyEnvironment','schema_version':1,'protocol':protocol.to_dict(),
            'task_set_file_sha256':hashlib.sha256(raw).hexdigest(),'coordinator_capability_sha256':hashlib.sha256(secret).hexdigest()})
        _load(root)
    return target/'coordinator.key'


def enroll(path,coordinator_key,pseudonym,*,authorization=None):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=8*LIMIT,max_files=4096) as root:
        fcntl.flock(root.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        p,tasks,sessions,histories,env,secret,receipts,previous,_=_load(root)
        _authenticate(coordinator_key,env['coordinator_capability_sha256']);pin_sources(tasks)
        cap=secrets.token_hex(32).encode()
        session=StudySession(protocol=p,pseudonym=pseudonym,resume_capability_sha256=hashlib.sha256(cap).hexdigest(),authorization=authorization)
        if len(sessions)>=4 or any(s.pseudonym==pseudonym or s.session_id==session.session_id for s in sessions.values()):
            raise EvidenceError('duplicate_pseudonym_session_collision_or_limit')
        name='session-'+session.session_id.removeprefix('study-session:v1:')
        os.mkdir(name,0o700,dir_fd=root.fd)
        with EvidenceRoot(Path(path)/name,max_bytes=LIMIT,max_total_bytes=2*LIMIT) as child:
            _write(child,'context.json',session.to_dict());atomic_create(child.fd,'resume.key',cap+b'\n')
            sha=child.read('context.json').byte_sha256
        _receipt(root,secret,len(receipts),previous,session,sha)
        _load(root)
    return session.session_id,Path(path)/name/'resume.key'


def read_session(path,session_id,resume_key,*,verify_primary=True,expected_tip=None):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=4*LIMIT,max_files=4096) as root:
        fcntl.flock(root.fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        p,tasks,sessions,events,*_=_load(root)
        if session_id not in sessions:raise EvidenceError('unknown_private_session')
        session=sessions[session_id];_authenticate(resume_key,session.resume_capability_sha256)
        if expected_tip is not None and (not events[session_id] or events[session_id][-1].event_id!=expected_tip):raise EvidenceError('trusted_session_tip_conflict')
        if verify_primary:pin_sources(tasks)
        return session,tasks,events[session_id]


def append_event(path,session_id,resume_key,*,expected_tip,action,clock,consent=None,presentation=None,response=None,invalid_code=None,coordinator_key=None):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=8*LIMIT,max_files=4096) as root:
        fcntl.flock(root.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        p,tasks,sessions,histories,env,secret,receipts,previous,dirs=_load(root)
        if session_id not in sessions:raise EvidenceError('unknown_private_session')
        session=sessions[session_id];_authenticate(resume_key,session.resume_capability_sha256)
        if action is A.INVALIDATE:
            if coordinator_key is None:raise EvidenceError('coordinator_capability_required_to_invalidate')
            _authenticate(coordinator_key,env['coordinator_capability_sha256'])
        events=histories[session_id]
        if expected_tip!=(events[-1].event_id if events else None):raise EvidenceError('stale_or_replayed_session_submission')
        if action not in (A.WITHDRAW,A.INVALIDATE):pin_sources(tasks)
        summary,*_=replay(session,tasks,events);state=summary.state
        if action is A.START:state=S.IN_PROGRESS
        elif action is A.CONSENT and consent is not None and consent.state is C.DECLINED:state=S.WITHDRAWN
        elif action is A.COMPLETE:state=S.COMPLETED
        elif action is A.WITHDRAW:state=S.WITHDRAWN
        elif action is A.INVALIDATE:state=S.INVALIDATED
        event=SessionEvent(session_id=session_id,protocol_id=p.protocol_id,task_set_digest=p.task_set_digest,sequence=len(events),
            previous_event_id=expected_tip,action=action,state_after=state,clock=clock,consent=consent,presentation=presentation,response=response,invalid_code=invalid_code)
        replay(session,tasks,events+(event,))
        raw=(event.to_json()+'\n').encode()
        if len(raw)>65536:raise EvidenceError('private_session_event_limit')
        with EvidenceRoot(Path(path)/dirs[session_id],max_bytes=LIMIT,max_total_bytes=2*LIMIT) as child:
            atomic_create(child.fd,f'event-{len(events):06d}.json',raw)
            sha=child.read('context.json').byte_sha256
        _receipt(root,secret,len(receipts),previous,session,sha,event)
        _load(root)
    return event


def inspect_environment(path,coordinator_key,*,verify_primary=True):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=4*LIMIT,max_files=4096) as root:
        fcntl.flock(root.fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        p,tasks,sessions,events,env,*_=_load(root)
        _authenticate(coordinator_key,env['coordinator_capability_sha256'])
        if verify_primary:revalidate_tasks(tasks)
        return p,tasks,sessions,events
