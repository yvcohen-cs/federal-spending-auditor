"""Append-only structured decisions wrapping existing C6 workflow events.

Local labels and hashes are not authentication or signatures. Source evidence
and automated statuses are never writable through this module.
"""
import fcntl
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .review_events import ReviewWorkflowEvent, WorkflowState as W, validate_events
from .review_packet_io import atomic_create, new_directory, outside, check_store_location
from .review_packet_models import RecommendedVerificationAction
from .review_validation_models import ReviewerDecisionEvent, ReviewDecision as D, ReviewKind
from .review_validation_tasks import validate_primary, build_tasks, check_new_location

MAX_BYTES=16*1024*1024


def notes(decision,rationale,kind):
    return canonical({'decision':decision.value,'rationale':rationale.to_dict(),'kind':kind.value,
        'authority':'evidence_quality_only_no_financial_authority'})


def review_states(manifest,events):
    validate_decisions(manifest,events)
    result=[]
    for task in manifest.tasks:
        choices={e.decision for e in events if e.task_id==task.task_id}
        conflict=D.ACCEPT in choices and D.REJECT in choices
        state=('CONFLICTING_REVIEW' if conflict else 'NOT_EVALUATED' if not choices else
            'ESCALATE_FOR_REVIEW' if D.ESCALATE in choices else 'NEEDS_MORE_EVIDENCE' if D.MORE in choices else
            'UNRESOLVED_REVIEW' if len(choices)>1 else next(iter(choices)).value)
        result.append({'task_id':task.task_id,'review_state':state,'contradiction':conflict,
            'resolution':'independent_adjudication_with_new_cited_evidence_required_no_winner_selected' if conflict else 'all_assertions_preserved',
            'financial_authorization':False})
    return result


def validate_decisions(manifest,events,kind=None):
    if len(events)>1000: raise EvidenceError('review_decision_event_limit')
    tasks={t.task_id:t for t in manifest.tasks};previous=None;payloads=set();kinds=set()
    for i,event in enumerate(events):
        if not isinstance(event,ReviewerDecisionEvent): raise TypeError('typed_decision_event_required')
        task=tasks.get(event.task_id);w=event.workflow_event;kinds.add(event.kind)
        if (task is None or event.task_manifest_sha256!=manifest.substantive_sha256
                or event.previous_decision_event_id!=previous or w.sequence!=i
                or w.packet_id!=task.packet_id or w.claim_id!=task.claim_id
                or w.notes!=notes(event.decision,event.rationale,event.kind)):
            raise EvidenceError('review_decision_context_or_chain_conflict')
        expected=W.PENDING_REVIEW if not any(p.task_id==task.task_id for p in events[:i]) else (
            W.NEEDS_MORE_EVIDENCE if event.decision in (D.MORE,D.ESCALATE) else W.REVIEWED)
        if w.state is not expected:
            raise EvidenceError('unauthorized_review_workflow_change')
        known={c.citation_id for c in task.citations}
        if not set(event.rationale.citation_ids)<=known or event.rationale.acknowledged_obligations!=task.missing_proof_obligations:
            raise EvidenceError('rationale_must_cite_task_and_acknowledge_all_missing_proofs')
        if w.follow_up or any(c not in known for a in event.follow_up for c in a.citation_ids):
            raise EvidenceError('unknown_or_misplaced_decision_follow_up')
        if event.decision in (D.MORE,D.ESCALATE) and not event.follow_up:
            raise EvidenceError('follow_up_required_for_unresolved_review')
        payload=digest({'task':event.task_id,'decision':event.decision.value,'rationale':event.rationale.to_dict(),
            'attribution':event.attribution_label,'kind':event.kind.value,'timestamp':w.timestamp_utc,
            'follow_up':[f.to_dict() for f in event.follow_up]})
        if payload in payloads: raise EvidenceError('duplicate_review_decision_submission')
        payloads.add(payload);previous=event.decision_event_id
    if len(kinds)>1 or kind is not None and kinds and kinds!={kind}:
        raise EvidenceError('simulated_and_human_histories_must_remain_separate')
    validate_events(manifest.packets,tuple(e.workflow_event for e in events))


def context(manifest,kind):
    return {'schema_type':'ReviewerDecisionContext','schema_version':1,
        'task_manifest_sha256':manifest.substantive_sha256,'packet_manifest_sha256':manifest.packets.substantive_sha256,
        'selected_claim_ids':list(manifest.packets.selected_claim_ids),
        'kind':kind.value,'attribution':'provided_labels_not_authenticated_identities','financial_authorization':False}


def _read(reader,manifest,kind):
    names=reader.discover();data={n:reader.read(n) for n in names}
    if sum(len(s.data) for s in data.values())>MAX_BYTES: raise EvidenceError('review_decision_log_size_limit')
    if 'review-context.json' not in data or strict_json(data['review-context.json'].data)!=context(manifest,kind):
        raise EvidenceError('review_decision_context_conflict')
    event_names=tuple(n for n in names if n!='review-context.json')
    if event_names!=tuple(f'decision-{i:06d}.json' for i in range(len(event_names))):
        raise EvidenceError('partial_extra_or_missing_decision_events')
    events=tuple(ReviewerDecisionEvent.from_dict(strict_json(data[n].data)) for n in event_names)
    validate_decisions(manifest,events,kind)
    if {n:reader.read(n,recheck=True).byte_sha256 for n in reader.discover()}!={n:s.byte_sha256 for n,s in data.items()}:
        raise EvidenceError('review_decision_log_changed')
    return events


def read_decisions(path,root,manifest,kind,*,expected_tip=None):
    validate_primary(root,manifest)
    with EvidenceRoot(path,max_bytes=65536,max_total_bytes=2*MAX_BYTES,max_files=1001) as reader:
        fcntl.flock(reader.fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        events=_read(reader,manifest,kind)
    if expected_tip is not None and (not events or events[-1].decision_event_id!=expected_tip):
        raise EvidenceError('review_decision_trusted_tip_conflict')
    validate_primary(root,manifest)
    return events


def append_decision(path,root,manifest,*,task_id,decision,rationale,kind,attribution_label,timestamp_utc,follow_up=(),protected=()):
    validate_primary(root,manifest)
    target=outside(path,(root,)+tuple(protected));check_store_location(target);check_new_location(target)
    if not isinstance(kind,ReviewKind): raise ValueError('explicit_review_kind_required')
    task=next((t for t in manifest.tasks if t.task_id==task_id),None)
    if task is None: raise EvidenceError('unknown_review_task')
    def prepare(events):
        initial=not any(e.task_id==task_id for e in events)
        state=W.PENDING_REVIEW if initial else W.NEEDS_MORE_EVIDENCE if decision in (D.MORE,D.ESCALATE) else W.REVIEWED
        workflow=ReviewWorkflowEvent(packet_manifest_sha256=manifest.packets.substantive_sha256,packet_id=task.packet_id,
            claim_id=task.claim_id,sequence=len(events),previous_event_id=events[-1].workflow_event.event_id if events else None,
            state=state,reviewer=attribution_label,notes=notes(decision,rationale,kind),timestamp_utc=timestamp_utc,follow_up=())
        event=ReviewerDecisionEvent(task_manifest_sha256=manifest.substantive_sha256,task_id=task_id,
            previous_decision_event_id=events[-1].decision_event_id if events else None,
            decision=decision,rationale=rationale,kind=kind,attribution_label=attribution_label,workflow_event=workflow,follow_up=follow_up)
        validate_decisions(manifest,events+(event,),kind)
        raw=(event.to_json()+'\n').encode()
        if len(raw)>65536: raise EvidenceError('review_decision_size_limit')
        return event,raw
    if not target.exists():
        prepare(())
        new_directory(target)
    with EvidenceRoot(target,max_bytes=65536,max_total_bytes=5*MAX_BYTES,max_files=1001) as reader:
        fcntl.flock(reader.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if not reader.discover():
            atomic_create(reader.fd,'review-context.json',(canonical(context(manifest,kind))+'\n').encode())
        events=_read(reader,manifest,kind);event,raw=prepare(events)
        validate_primary(root,manifest)
        if _read(reader,manifest,kind)!=events: raise EvidenceError('review_decision_log_changed')
        if sum(len(reader.read(n,recheck=True).data) for n in reader.discover())+len(raw)>MAX_BYTES:
            raise EvidenceError('review_decision_log_size_limit')
        atomic_create(reader.fd,f'decision-{len(events):06d}.json',raw)
        if _read(reader,manifest,kind)!=events+(event,): raise EvidenceError('review_decision_append_changed')
    validate_primary(root,manifest)
    return event


def tasks_for_log(root,path,*,packet_bundle=None):
    if packet_bundle is not None:
        return build_tasks(root,packet_bundle=packet_bundle)
    with EvidenceRoot(path,max_bytes=65536,max_total_bytes=131072,max_files=1001) as reader:
        saved=strict_json(reader.read('review-context.json').data)
    selected=saved.get('selected_claim_ids') if isinstance(saved,dict) else None
    if not isinstance(selected,list) or not 1<=len(selected)<=100 or any(not isinstance(c,str) for c in selected) or selected!=sorted(set(selected)):
        raise EvidenceError('review_log_frozen_claim_selection_required')
    return build_tasks(root,claim_ids=tuple(selected))
