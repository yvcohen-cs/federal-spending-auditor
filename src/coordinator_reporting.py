"""Aggregate-only primary-checked C6 reports. No human measurements inferred."""
from html import escape
from pathlib import Path
import hashlib

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .review_packet_io import atomic_create, new_directory
from .pilot_session_models import StudyProtocol
from .pilot_session_store import private_location, _private_fd
from .coordinator_governance import protocol, pending_checklist, assess, PROTOCOL_SHA
from .coordinator_accessibility import audit
from .coordinator_lifecycle import inspect, lifecycle_assessment, LIMIT


def report(store,key,*,as_of,checklist=None):
    context,events,state=inspect(store,key)
    if state in ('RETIRING','DELETING'):
        raise EvidenceError('incomplete_lifecycle_cannot_publish_report')
    p=StudyProtocol.from_dict(context['study_protocol'])
    governance=assess(checklist or pending_checklist(p),p,as_of)
    captured=context['captured_report']
    return {'schema_type':'CoordinatorRehearsalReport','schema_version':1,
        'assessment_as_of':as_of,'protocol_version':protocol()['version'],'preregistration_sha256':PROTOCOL_SHA,
        'task_set_digest':context['task_set_digest'],'evidence_inventory_digest':p.evidence_inventory_digest,
        'source_inventory_digests':sorted(context['source_roots'].values()),
        'software_controls':{'frozen_protocols':'VERIFIED_BYTE_HASHES','primary_source_inventory':'VERIFIED_LOCAL_HASHES',
            'lifecycle_history':'VERIFIED_LOCAL_MAC_CHAIN_AND_NAMESPACE',
            'session_validation_scope':'CAPTURED_PRE_RETIREMENT_PRIMARY_REPLAY' if state!='ACTIVE' else 'CAPTURED_PRIMARY_REPLAY_AND_UNCHANGED_BYTES',
            'session_history_currently_available':state!='DELETED',
            'independent_security_inspection':'NOT_ESTABLISHED_BY_THIS_SELF_REPORT'},
        'simulated_observations':{'kind':'SIMULATED','actual_people':False,
            'session_states':captured['session_states'],
            'metrics':captured['synthetic_study_observations']['metrics'],
            'excluded_sessions':captured['excluded_sessions'],
            'captured_C5_report_sha256':context['captured_report_sha256'],
            'task_count':12,'source_API_calls':0,
            'limits':'Scripted software rehearsal, not human accuracy, usability, agreement or throughput.'},
        'prospective_governance':governance,'accessibility':audit(),
        'privacy_and_deletion':lifecycle_assessment(context,events,state,as_of),
        'human_measurements':{'status':'NOT_CONDUCTED','participants':0,'consent_observed':False,
            'usability':'UNKNOWN','throughput':'UNKNOWN','accuracy':'NOT_MEASURED'},
        'unknown_outcomes':['Independent approval authenticity, eligibility and consent comprehension.',
            'Actual assistive-technology and human usability performance.',
            'Encryption, physical access, secure erasure, copies and backup deletion.'],
        'financial_eligibility_changed':False,'frozen_readiness_upgrade':False,'production_screening_authorized':False,
        'blockers':{'small_human_pilot':governance['missing_or_ineffective_scopes']+['independent_governance_verification','accessibility_and_storage_signoff','real_data_deletion_design_review'],
            'SAM_source_validation':['separate_authorized_access_and_bounded_validation'],
            'revision_conditioned_finances':['authoritative_identity_history_revision_and_monetary_basis_proof'],
            'production':['separate_operational_security_privacy_and_frozen_readiness_authorization']},
        'recommendation':'Phase 4C7: independent governance/accessibility/deletion-design inspection; only then consider a separately authorized voluntary pilot.'}


def markdown(value):
    lines=['# Phase 4C6 coordinator rehearsal','',
        'SIMULATED software observations only. Actual human study: NOT_CONDUCTED.',
        'No financial authority, readiness upgrade or production screening authorization.']
    for key in sorted(value):lines.extend(['','## '+key,'','    '+canonical(value[key])])
    return '\n'.join(lines)+'\n'


def html(value):
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'; form-action \'none\'">'
        '<title>Coordinator rehearsal</title><h1>Coordinator rehearsal</h1><pre>'+escape(markdown(value))+'</pre></html>')


def _files(value):
    return {'coordinator.json':(canonical({'report':value,'substantive_sha256':digest(value)})+'\n').encode(),
            'coordinator.md':markdown(value).encode(),'coordinator.html':html(value).encode()}


def write_report(path,store,key,*,as_of,checklist=None):
    value=report(store,key,as_of=as_of,checklist=checklist)
    target=private_location(path);source=Path(store).absolute()
    if source==target or source in target.parents or target in source.parents:
        raise EvidenceError('coordinator_report_must_be_outside_private_workspace')
    for ancestor in (target,)+tuple(target.parents):
        if (ancestor/'coordinator-context.json').exists() or (ancestor/'coordinator-report-commit.json').exists():
            raise EvidenceError('coordinator_report_inside_managed_root')
    files=_files(value)
    if sum(map(len,files.values()))>LIMIT:raise EvidenceError('coordinator_report_limit')
    new_directory(target)
    with EvidenceRoot(target,max_bytes=LIMIT,max_total_bytes=2*LIMIT) as root:
        for name,raw in files.items():atomic_create(root.fd,name,raw)
        if report(store,key,as_of=as_of,checklist=checklist)!=value:raise EvidenceError('coordinator_changed_during_report')
        atomic_create(root.fd,'coordinator-report-commit.json',(canonical({'schema_type':'CoordinatorReportCommit','schema_version':1,
            'files':{n:hashlib.sha256(raw).hexdigest() for n,raw in files.items()}})+'\n').encode())
    return digest(value)


def read_report(path,store,key,*,as_of,checklist=None):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=2*LIMIT,max_files=4) as root:
        _private_fd(root.fd);data={n:root.read(n) for n in root.discover()}
        if set(data)!={'coordinator.json','coordinator.md','coordinator.html','coordinator-report-commit.json'}:
            raise EvidenceError('truncated_coordinator_report')
        for name in data:
            import os,stat
            s=os.stat(name,dir_fd=root.fd,follow_symlinks=False)
            if s.st_uid!=os.getuid() or stat.S_IMODE(s.st_mode)!=0o600:raise EvidenceError('private_coordinator_report_required')
        expected={'schema_type':'CoordinatorReportCommit','schema_version':1,
            'files':{n:s.byte_sha256 for n,s in data.items() if n!='coordinator-report-commit.json'}}
        if strict_json(data['coordinator-report-commit.json'].data)!=expected:raise EvidenceError('coordinator_report_hash_conflict')
        value=report(store,key,as_of=as_of,checklist=checklist)
        if any(data[n].data!=raw for n,raw in _files(value).items()):raise EvidenceError('coordinator_report_not_primary_projection')
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in data.items()}:
            raise EvidenceError('coordinator_report_changed')
    return value
