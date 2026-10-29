"""Deterministic session replay and timing; never infers human participation."""
from datetime import datetime
from .evidence_io import EvidenceError
from .pilot_session_models import (SessionState as S,ConsentState as C,MeasurementKind as M,
    SessionAction as A,SessionSummary,derived_rationale)
from .review_validation_models import ReviewDecision as D


def replay(session,task_set,events):
    p=session.protocol
    if p.task_set_digest!=task_set.task_set_digest or p.evidence_inventory_digest!=task_set.evidence_inventory_digest:
        raise EvidenceError('session_task_set_or_inventory_conflict')
    state=S.NOT_STARTED;consent=C.NOT_REQUESTED;active=None;begin=None;responses=[];attempted=set()
    previous=None;last_clock=None;timing_opted_in=False;presentations=0;abandoned=0;invalid=0;seen=set();durations=[]
    for index,e in enumerate(events):
        if (e.session_id!=session.session_id or e.protocol_id!=p.protocol_id or e.task_set_digest!=p.task_set_digest
                or e.sequence!=index or e.previous_event_id!=previous or index>=256):
            raise EvidenceError('session_event_context_order_or_chain_conflict')
        clock=e.clock
        if clock.kind not in (p.measurement_kind,M.NONE,M.INVALID) or (not timing_opted_in and clock.kind not in (M.NONE,M.INVALID)):
            raise EvidenceError('simulated_human_or_unmeasured_clock_conflict')
        if last_clock and clock.timestamp_utc is not None:
            if datetime.fromisoformat(clock.timestamp_utc.replace('Z','+00:00'))<datetime.fromisoformat(last_clock.timestamp_utc.replace('Z','+00:00')):
                raise EvidenceError('session_timestamp_order_conflict')
            if clock.epoch is not None and last_clock.epoch is not None:
                if clock.epoch!=last_clock.epoch and e.action not in (A.RESUME,A.START):
                    raise EvidenceError('clock_epoch_change_requires_explicit_resume')
                if clock.epoch==last_clock.epoch and clock.monotonic_ns<last_clock.monotonic_ns:
                    raise EvidenceError('monotonic_clock_reordered')
        expected_payload={A.CONSENT:'consent',A.PRESENT:'presentation',A.RESPOND:'response'}.get(e.action)
        if any(getattr(e,k) is not None for k in ('consent','presentation','response') if k!=expected_payload) or expected_payload and getattr(e,expected_payload) is None:
            raise EvidenceError('unsupported_session_payload')
        if e.action not in (A.INVALID_SUBMISSION,A.INVALIDATE) and e.invalid_code is not None:
            raise EvidenceError('invalid_code_outside_fixed_diagnostic')
        if e.action is A.CONSENT:
            r=e.consent
            if (state is not S.NOT_STARTED or consent is not C.NOT_REQUESTED or r.protocol_id!=p.protocol_id
                    or r.governance_sha256!=p.governance_sha256 or r.kind is not p.measurement_kind
                    or r.timing_acknowledged and not p.timing_enabled):
                raise EvidenceError('invalid_or_duplicate_consent')
            consent=r.state;timing_opted_in=r.state is C.GRANTED and r.timing_acknowledged and p.timing_enabled
            if consent is C.DECLINED:state=S.WITHDRAWN
        elif e.action is A.START:
            if state is not S.NOT_STARTED or consent is not C.GRANTED:raise EvidenceError('consent_required_before_start')
            state=S.IN_PROGRESS
        elif e.action is A.PRESENT:
            t=e.presentation
            if (state is not S.IN_PROGRESS or active is not None or len(responses)>=len(task_set.entries)
                    or t.position!=len(responses) or t.task_id!=task_set.entries[t.position].task.task_id
                    or t.session_id!=session.session_id or t.event_sequence!=index or t.clock!=clock):
                raise EvidenceError('one_exact_next_task_only')
            active=t;begin=None;attempted.add(t.position);presentations+=1
        elif e.action is A.BEGIN_RESPONSE:
            if state is not S.IN_PROGRESS or active is None or begin is not None:raise EvidenceError('presentation_required_before_response_entry')
            begin=clock
        elif e.action is A.RESPOND:
            r=e.response
            if state is not S.IN_PROGRESS or active is None or begin is None:raise EvidenceError('active_presentation_and_response_entry_required')
            task=task_set.entries[active.position].task
            known={c.citation_id for c in task.citations};uncertain=set(task.missing_proof_obligations) or {'none_identified'}
            if (r.presentation_id!=active.presentation_id or r.task_id!=task.task_id or r.clock!=clock or r.response_id in seen
                    or not set(r.citation_ids)<=known or not set(r.uncertainty_codes)<=uncertain
                    or r.rationale!=derived_rationale(task,r.reason_code,r.uncertainty_codes,r.citation_ids)):
                raise EvidenceError('replayed_forged_or_invalid_structured_response')
            seen.add(r.response_id);responses.append((active.position,r));durations.append(timing(active.clock,begin,clock,p.measurement_kind))
            active=None;begin=None
        elif e.action is A.INVALID_SUBMISSION:
            if state is not S.IN_PROGRESS or active is None or e.invalid_code not in ('invalid_choice','invalid_rationale','replayed_submission'):
                raise EvidenceError('bounded_active_invalid_submission_only')
            invalid+=1
        elif e.action in (A.SUSPEND,A.RESUME):
            if state is not S.IN_PROGRESS:raise EvidenceError('only_in_progress_session_can_suspend_or_resume')
            abandoned+=int(active is not None);active=None;begin=None
        elif e.action is A.COMPLETE:
            if state is not S.IN_PROGRESS or active is not None or len(responses)!=len(task_set.entries):
                raise EvidenceError('all_tasks_required_before_completion')
            state=S.COMPLETED
        elif e.action is A.WITHDRAW:
            if state is S.WITHDRAWN:raise EvidenceError('withdrawal_is_terminal')
            abandoned+=int(active is not None);active=None;begin=None;state=S.WITHDRAWN;consent=C.WITHDRAWN
        elif e.action is A.INVALIDATE:
            if state in (S.WITHDRAWN,S.INVALIDATED) or e.invalid_code not in ('evidence_integrity','coordinator_invalidated'):
                raise EvidenceError('invalid_invalidation_transition')
            abandoned+=int(active is not None);active=None;begin=None;state=S.INVALIDATED
        else:raise EvidenceError('unsupported_session_action')
        if e.state_after is not state:raise EvidenceError('unauthorized_session_state_change')
        previous=e.event_id
        if clock.timestamp_utc is not None:last_clock=clock
    eligible=state in (S.IN_PROGRESS,S.COMPLETED) and consent is C.GRANTED
    measured=[d for d in durations if d[0] is p.measurement_kind]
    refs=[(task_set.entries[i].reference_decision,r.decision) for i,r in responses if task_set.entries[i].reference_decision is not None]
    summary=SessionSummary(session_id=session.session_id,state=state,consent=consent,kind=p.measurement_kind,
        tasks_attempted=len(attempted),tasks_completed=len(responses),needs_more_evidence=sum(r.decision is D.MORE for _,r in responses),
        escalations=sum(r.decision is D.ESCALATE for _,r in responses),invalid_submissions=invalid,
        uncertainty_responses=sum(bool(r.uncertainty_codes) for _,r in responses),reference_agreements=sum(a is b for a,b in refs),reference_denominator=len(refs),
        measured_responses=len(measured),not_measured_responses=sum(d[0] is M.NONE for d in durations),invalid_timing_responses=sum(d[0] is M.INVALID for d in durations),
        presentation_duration_ns=sum(d[1] for d in measured) if measured else None,
        decision_duration_ns=sum(d[2] for d in measured) if measured else None,eligible_for_aggregation=eligible)
    return summary,active,begin,tuple(responses),{'presentations':presentations,'abandoned_presentations':abandoned,'pending_presentation':active is not None}


def timing(presentation,begin,end,kind):
    points=(presentation,begin,end)
    if any(p.kind is M.INVALID for p in points):return M.INVALID,None,None
    if any(p.kind is M.NONE for p in points):return M.NONE,None,None
    if any(p.kind is not kind for p in points) or len({p.epoch for p in points})!=1:return M.NONE,None,None
    a=begin.monotonic_ns-presentation.monotonic_ns;b=end.monotonic_ns-begin.monotonic_ns
    return (kind,a,b) if a>=0 and b>=0 else (M.INVALID,None,None)
