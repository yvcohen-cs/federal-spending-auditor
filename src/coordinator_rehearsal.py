"""Deterministic 12-task coordinator simulation. Never enrolls actual people."""
from dataclasses import replace
from pathlib import Path
import os

from .evidence_io import EvidenceError, EvidenceRoot, digest
from .pilot_taskset import build_task_set, make_protocol
from .pilot_session_store import create_environment, enroll, read_session
from .pilot_session_models import (MeasurementKind as M, ConsentState as C, ConsentReceipt,
    ClockObservation, SessionAction as A)
from .pilot_review import act, present, respond, SimulatedClock
from .pilot_session_rules import replay
from .pilot_study_reporting import write_report
from .review_validation_models import ReviewDecision as D
from .coordinator_accessibility import show_task
from .coordinator_governance import pending_checklist, require_approvals, protocol
from .coordinator_lifecycle import new_workspace, capture, inspect, tip, retire, delete


class RehearsalClock(SimulatedClock):
    def __init__(self, tick=0, epoch='aaaaaaaaaaaaaaaa'):
        super().__init__(); self.tick=tick; self.epoch=epoch
    def point(self):return replace(super().point(), epoch=self.epoch)


def exercise(path, study_root, public_root, *, as_of='2025-03-01'):
    protocol()
    tasks=build_task_set(study_root,public_root=public_root)
    if tasks.selection_version!='pilot-mixed-v1' or len(tasks.entries)!=12:
        raise EvidenceError('exact_frozen_mixed_plan_required')
    key=new_workspace(path); store=Path(path)/'batch'
    p=make_protocol(tasks,timing=True,instance_id='BATCH-cccccccc00000006')
    c5key=create_environment(store,tasks,p)
    # Real approval absence is exercised, not replaced by fake approved records.
    try:require_approvals(pending_checklist(p),p,as_of)
    except EvidenceError as e:
        if e.code!='independent_governance_approvals_missing_or_ineffective':raise
    else:raise EvidenceError('missing_governance_failed_open')
    for number in range(1,5):
        sid,resume=enroll(store,c5key,'SIM-cccccccc'+f'{number:08x}')
        clock=RehearsalClock()
        receipt=ConsentReceipt(protocol_id=p.protocol_id,governance_sha256=p.governance_sha256,
            kind=M.SIMULATED,state=C.GRANTED,voluntary=True,purpose_understood=True,
            withdrawal_understood=True,timing_acknowledged=True)
        act(store,sid,resume,A.CONSENT,ClockObservation(timestamp_utc=None,kind=M.NONE),consent=receipt)
        act(store,sid,resume,A.START,clock.point())
        if number==4:
            act(store,sid,resume,A.INVALIDATE,clock.point(),invalid_code='coordinator_invalidated',coordinator_key=c5key)
            continue
        count=12 if number==1 else 1
        for i in range(count):
            task=tasks.entries[i].task
            if number==1 and i==6:
                present(store,sid,resume,clock.point())
                act(store,sid,resume,A.SUSPEND,clock.point())
                # Simulates a new process epoch, without inventing elapsed pause time.
                clock=RehearsalClock(tick=100,epoch='bbbbbbbbbbbbbbbb')
                act(store,sid,resume,A.RESUME,clock.point())
            present(store,sid,resume,clock.point())
            lines=[];show_task(task,i,12,lines.append,tasks.entries[i].source_root)
            if not any(task.claim in line for line in lines):raise EvidenceError('exact_claim_not_presented')
            # Read every cited primary artifact, including counterevidence. The
            # C4 task rebuild has independently checked locator/provenance scope.
            with EvidenceRoot(tasks.entries[i].source_root) as root:
                for citation in task.citations:
                    a=citation.evidence.artifact
                    if root.read(a.relative_path).byte_sha256!=a.sha256:raise EvidenceError('citation_primary_hash_conflict')
            act(store,sid,resume,A.BEGIN_RESPONSE,clock.point())
            decision=D.ACCEPT if i in (0,6) else D.ESCALATE if i==3 else D.MORE
            respond(store,sid,resume,clock.point(),decision,'narrow_support' if decision is D.ACCEPT else 'missing_proof',
                task.missing_proof_obligations or ('none_identified',),tuple(sorted(c.citation_id for c in task.citations)),
                'none' if decision is D.ACCEPT else 'independent_review' if decision is D.ESCALATE else 'revision_lineage')
        if number==1:act(store,sid,resume,A.COMPLETE,clock.point())
        elif number==2:act(store,sid,resume,A.WITHDRAW,clock.point())
        else:act(store,sid,resume,A.SUSPEND,clock.point())
        session,t,e=read_session(store,sid,resume)
        if replay(session,t,e)[0].tasks_completed!=count:raise EvidenceError('rehearsal_response_count_conflict')
    os.mkdir(Path(path)/'outputs',0o700)
    first=write_report(Path(path)/'outputs'/'report-a',store,c5key)
    second=write_report(Path(path)/'outputs'/'report-b',store,c5key)
    if first!=second:raise EvidenceError('nonreproducible_rehearsal')
    capture(path,key,as_of=as_of)
    context,events,state=inspect(path,key)
    result=context['captured_report']
    expected=protocol()['rehearsal']
    if (state!='ACTIVE' or result['synthetic_study_observations']['metrics']['tasks_completed']!=expected['eligible_responses']
            or result['excluded_sessions']['excluded_response_count']!=expected['withdrawn_responses_excluded']):
        raise EvidenceError('preregistered_rehearsal_outcome_conflict')
    return key


def retire_and_delete(path,key,*,as_of='2025-03-01',reason='WITHDRAWAL_REQUEST'):
    retire(path,key,expected_tip=tip(path,key),as_of=as_of,reason=reason)
    delete(path,key,expected_tip=tip(path,key),as_of=as_of)
    if inspect(path,key)[2]!='DELETED':raise EvidenceError('deletion_rehearsal_incomplete')
