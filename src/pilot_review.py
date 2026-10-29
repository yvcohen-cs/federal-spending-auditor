"""Minimal offline one-task terminal interface and explicit coordinator commands."""
import argparse
from datetime import datetime,timezone,timedelta
from pathlib import Path
import secrets
import time

from .evidence_io import EvidenceError,EvidenceRoot,canonical,strict_json
from .pilot_session_models import (ClockObservation,ConsentReceipt,ConsentState as C,MeasurementKind as M,
    SessionState as S,SessionAction as A,TaskPresentation,ReviewerResponse,StudyAuthorization,
    REASONS,FOLLOW_UP,derived_rationale)
from .review_validation_models import ReviewDecision as D
from .pilot_taskset import build_task_set,make_protocol
from .pilot_session_store import create_environment,enroll,read_session,append_event
from .pilot_session_rules import replay
from .pilot_study_reporting import write_report


class LocalClock:
    def __init__(self,kind,timing):self.kind=kind;self.timing=timing;self.epoch=secrets.token_hex(8);self.base=time.monotonic_ns() if timing else None
    def point(self):
        return ClockObservation(timestamp_utc=datetime.now(timezone.utc).isoformat() if self.timing else None,kind=self.kind if self.timing else M.NONE,
            monotonic_ns=time.monotonic_ns()-self.base if self.timing else None,epoch=self.epoch if self.timing else None)


class SimulatedClock:
    """Authored test clock, never a real participant duration measurement."""
    def __init__(self):self.tick=0
    def point(self):
        self.tick+=1
        return ClockObservation(timestamp_utc=(datetime(2025,3,1,tzinfo=timezone.utc)+timedelta(seconds=self.tick)).isoformat(),
            kind=M.SIMULATED,monotonic_ns=self.tick*10**9,epoch='aaaaaaaaaaaaaaaa')


def act(store,sid,key,action,clock,**payload):
    session,tasks,events=read_session(store,sid,key,verify_primary=action not in (A.WITHDRAW,A.INVALIDATE))
    return append_event(store,sid,key,expected_tip=events[-1].event_id if events else None,action=action,clock=clock,**payload)


def present(store,sid,key,clock):
    session,tasks,events=read_session(store,sid,key);summary,active,*_=replay(session,tasks,events)
    if active is not None:raise EvidenceError('task_already_presented')
    t=TaskPresentation(session_id=sid,task_id=tasks.entries[summary.tasks_completed].task.task_id,
        position=summary.tasks_completed,event_sequence=len(events),clock=clock)
    return act(store,sid,key,A.PRESENT,clock,presentation=t)


def respond(store,sid,key,clock,decision,reason_code,uncertainty_codes,citation_ids,follow_up_code):
    session,tasks,events=read_session(store,sid,key);_,active,begin,*_=replay(session,tasks,events)
    if active is None or begin is None:raise EvidenceError('response_without_active_task')
    task=tasks.entries[active.position].task
    r=ReviewerResponse(presentation_id=active.presentation_id,task_id=task.task_id,decision=decision,
        reason_code=reason_code,uncertainty_codes=uncertainty_codes,citation_ids=citation_ids,proof_acknowledged=True,
        follow_up_code=follow_up_code,rationale=derived_rationale(task,reason_code,uncertainty_codes,citation_ids),clock=clock)
    return act(store,sid,key,A.RESPOND,clock,response=r)


def display_task(task,position,total,output=print,source_root=None):
    output(f'Task {position+1} of {total}')
    output('Claim under review: '+task.claim)
    output('Evidence-quality review only. Acceptance cannot authorize financial arithmetic or screening.')
    output('Applicable rules: '+', '.join(task.rule_versions))
    output('AUTOMATED ASSESSMENT:')
    for d in task.dimensions:output(d.name+': '+d.status.value+' — '+d.rationale)
    if source_root is not None:output('Read-only evidence root: '+canonical(str(source_root)))
    output('PRIMARY EVIDENCE REFERENCES:')
    for i,c in enumerate(task.citations):
        e=c.evidence;role='packet claim evidence' if c.citation_id in task.packet_citation_ids else 'additional returned context/counterevidence; identity not assumed'
        output(str(i+1)+'. '+role+' '+canonical({'citation_id':c.citation_id,'source':e.reference.source,
            'path':e.artifact.relative_path,'sha256':e.artifact.sha256,'locator':e.reference.locator,
            'representation':e.artifact.representation.value,'endpoint':e.artifact.endpoint,'retrieved_at_utc':e.artifact.retrieved_at_utc}))
    for basis,title in (('source_native_value','OBSERVED SOURCE FIELDS'),('C4_component_interpretation','DERIVED IDENTIFIER INTERPRETATIONS'),('derived_source_context','DERIVED SOURCE CONTEXT')):
        output(title+':')
        for f in task.observed_fields:
            if f.basis==basis:output(canonical({'citation_id':f.citation_id,'field':f.path,'original':f.original_json}))
    output('Missing proof obligations: '+', '.join(task.missing_proof_obligations))
    output('Unknown parent, pagination, history and revision are not complete/absent. Do not infer misconduct.')
    output('q = save and stop; w = withdraw. No names, contact information or arbitrary free text are recorded.')


class StopInput(Exception):
    def __init__(self,withdraw=False):self.withdraw=withdraw


def terminal(store,sid,key,*,input_fn=input,output=print):
    session,tasks,events=read_session(store,sid,key);summary,*_=replay(session,tasks,events)
    opt_in=any(e.action is A.CONSENT and e.consent.state is C.GRANTED and e.consent.timing_acknowledged for e in events)
    clock=LocalClock(session.protocol.measurement_kind,session.protocol.timing_enabled and opt_in)
    def choice(prompt,options):
        while True:
            output(prompt)
            for i,(code,label) in enumerate(options):output(str(i+1)+'. '+label)
            raw=input_fn('Choose a number (q save, w withdraw): ').strip()
            if raw in ('q','w'):raise StopInput(raw=='w')
            if raw.isascii() and raw.isdigit() and 1<=int(raw)<=len(options):return options[int(raw)-1][0]
            # Raw invalid input is discarded, never echoed/stored.
            _,_,now=read_session(store,sid,key);s,active,*_=replay(session,tasks,now)
            if s.state is S.IN_PROGRESS and active is not None:act(store,sid,key,A.INVALID_SUBMISSION,clock.point(),invalid_code='invalid_choice')
            output('Invalid choice; no input text retained.')
    try:
        if summary.state in (S.COMPLETED,S.WITHDRAWN,S.INVALIDATED):raise EvidenceError('terminal_session_cannot_resume')
        if summary.state is S.NOT_STARTED:
            if summary.consent is C.NOT_REQUESTED:
                output('Voluntary study; you may decline or withdraw. Read the participant and governance documents first.')
                answers=[choice(text,(('yes','Yes'),('no','No')))=='yes' for text in
                    ('Do you voluntarily agree to this study?','Do you understand its evidence-usability purpose?','Do you understand withdrawal and batch deletion?')]
                timed=choice('Optional timing: do you agree to duration recording?',(('yes','Yes'),('no','No')))=='yes' if session.protocol.timing_enabled else False
                agreed=all(answers);opt_in=agreed and timed
                receipt=ConsentReceipt(protocol_id=session.protocol.protocol_id,governance_sha256=session.protocol.governance_sha256,
                    kind=session.protocol.measurement_kind,state=C.GRANTED if agreed else C.DECLINED,
                    voluntary=answers[0],purpose_understood=answers[1],withdrawal_understood=answers[2],timing_acknowledged=timed)
                act(store,sid,key,A.CONSENT,ClockObservation(timestamp_utc=None,kind=M.NONE),consent=receipt)
                if not agreed:output('Declined. No responses recorded.');return 1
            clock=LocalClock(session.protocol.measurement_kind,session.protocol.timing_enabled and opt_in)
            act(store,sid,key,A.START,clock.point())
        else:act(store,sid,key,A.RESUME,clock.point())
        while True:
            session,tasks,events=read_session(store,sid,key);summary,*_=replay(session,tasks,events)
            if summary.tasks_completed==len(tasks.entries):
                act(store,sid,key,A.COMPLETE,clock.point());output('Session completed. No financial authority granted.');return 0
            index=summary.tasks_completed;task=tasks.entries[index].task
            present(store,sid,key,clock.point());display_task(task,index,len(tasks.entries),output,source_root=tasks.entries[index].source_root)
            choice('Begin the structured response when ready.',(('begin','Begin response'),))
            act(store,sid,key,A.BEGIN_RESPONSE,clock.point())
            decision=choice('Evidence-quality decision:',tuple((d,d.value) for d in D))
            reason=choice('Interpretation:',tuple(REASONS.items()))
            uncertain=task.missing_proof_obligations or ('none_identified',)
            uncertainty=choice('Select a principal unresolved issue:',tuple((u,u) for u in uncertain))
            citation=choice('Select an exact supporting/countervailing citation:',tuple((c.citation_id,c.citation_id) for c in task.citations))
            follow=choice('Follow-up:',tuple((k,v) for k,v in FOLLOW_UP.items() if k!='none' or decision not in (D.MORE,D.ESCALATE)))
            ack=choice('Acknowledge ALL missing proof obligations: '+', '.join(task.missing_proof_obligations),(('yes','Acknowledge'),('no','Not ready')))
            if ack!='yes':
                act(store,sid,key,A.INVALID_SUBMISSION,clock.point(),invalid_code='invalid_rationale')
                act(store,sid,key,A.SUSPEND,clock.point());output('Saved without a response; unresolved obligations retained.');return 1
            respond(store,sid,key,clock.point(),decision,reason,(uncertainty,),(citation,),follow)
            output('Response saved; original evidence and automated findings unchanged.')
    except StopInput as stop:
        _,_,events=read_session(store,sid,key,verify_primary=not stop.withdraw);summary,*_=replay(session,tasks,events)
        if stop.withdraw:act(store,sid,key,A.WITHDRAW,clock.point());output('Withdrawn. All prior responses excluded from performance aggregates.')
        elif summary.state is S.IN_PROGRESS:act(store,sid,key,A.SUSPEND,clock.point());output('Saved. Resume requires the exact private session capability.')
        else:output('Not started; no response recorded.')
        return 1
    except (EOFError,KeyboardInterrupt):
        _,_,events=read_session(store,sid,key);summary,*_=replay(session,tasks,events)
        if summary.state is S.IN_PROGRESS:act(store,sid,key,A.SUSPEND,clock.point())
        return 130


def demo(store,study_root):
    tasks=build_task_set(study_root);p=make_protocol(tasks,timing=True);coordinator=create_environment(store,tasks,p)
    for number in range(1,5):
        sid,key=enroll(store,coordinator,'SIM-aaaaaaaa'+f'{number:08x}');clock=SimulatedClock()
        receipt=ConsentReceipt(protocol_id=p.protocol_id,governance_sha256=p.governance_sha256,kind=M.SIMULATED,state=C.GRANTED,
            voluntary=True,purpose_understood=True,withdrawal_understood=True,timing_acknowledged=True)
        act(store,sid,key,A.CONSENT,ClockObservation(timestamp_utc=None,kind=M.NONE),consent=receipt);act(store,sid,key,A.START,clock.point())
        if number==4:
            act(store,sid,key,A.INVALIDATE,clock.point(),invalid_code='coordinator_invalidated',coordinator_key=coordinator);continue
        count=len(tasks.entries) if number==1 else 1
        for i in range(count):
            task=tasks.entries[i].task;present(store,sid,key,clock.point())
            if number==1 and i==0:act(store,sid,key,A.INVALID_SUBMISSION,clock.point(),invalid_code='invalid_choice')
            act(store,sid,key,A.BEGIN_RESPONSE,clock.point())
            decision=D.ACCEPT if i in (0,6) else D.ESCALATE if i==3 else D.MORE
            respond(store,sid,key,clock.point(),decision,'narrow_support' if decision is D.ACCEPT else 'missing_proof',
                task.missing_proof_obligations or ('none_identified',),tuple(sorted(c.citation_id for c in task.citations)),
                'none' if decision is D.ACCEPT else 'revision_lineage')
        if number==1:act(store,sid,key,A.COMPLETE,clock.point())
        elif number==2:act(store,sid,key,A.WITHDRAW,clock.point())
        else:
            act(store,sid,key,A.SUSPEND,clock.point());act(store,sid,key,A.RESUME,clock.point())
    return coordinator


def main(argv=None):
    p=argparse.ArgumentParser(description='Offline private pilot preparation; no actual study without separate authorization.')
    mode=p.add_mutually_exclusive_group(required=True)
    for flag in ('prepare','enroll','review','withdraw','invalidate','report','demo'):mode.add_argument('--'+flag,action='store_true')
    p.add_argument('--store',required=True);p.add_argument('--study-root');p.add_argument('--public-root');p.add_argument('--output')
    p.add_argument('--coordinator-key');p.add_argument('--session-id');p.add_argument('--resume-key');p.add_argument('--pseudonym');p.add_argument('--authorization')
    p.add_argument('--kind',choices=[M.SIMULATED.value,M.HUMAN.value],default=M.SIMULATED.value);p.add_argument('--timing',action='store_true');p.add_argument('--batch-id')
    a=p.parse_args(argv)
    try:
        if a.prepare:
            if not a.study_root:raise EvidenceError('frozen_C4_study_root_required')
            tasks=build_task_set(a.study_root,public_root=a.public_root);protocol=make_protocol(tasks,kind=M(a.kind),timing=a.timing,instance_id=a.batch_id)
            key=create_environment(a.store,tasks,protocol);print(canonical({'coordinator_key_path':str(key),'no_human_participation_inferred':True}));return 0
        if a.demo:
            if not a.study_root or not a.output or a.kind!=M.SIMULATED.value:raise EvidenceError('explicit_synthetic_demo_inputs_required')
            key=demo(a.store,a.study_root);sha=write_report(a.output,a.store,key)
            print(canonical({'substantive_sha256':sha,'measurement_kind':'SIMULATED','actual_human_study':'NOT_CONDUCTED'}));return 1
        if a.enroll:
            if not a.coordinator_key or not a.pseudonym:raise EvidenceError('explicit_coordinator_and_opaque_pseudonym_required')
            authorization=None
            if a.authorization:
                from .pilot_session_store import _private_fd
                target=Path(a.authorization).absolute()
                with EvidenceRoot(target.parent,max_bytes=8192,max_total_bytes=16384) as root:
                    _private_fd(root.fd);authorization=StudyAuthorization.from_dict(strict_json(root.read(target.name).data))
            sid,key=enroll(a.store,a.coordinator_key,a.pseudonym,authorization=authorization)
            print(canonical({'session_id':sid,'resume_key_path':str(key),'state':'NOT_STARTED','consent':'NOT_REQUESTED'}));return 0
        if a.report:
            if not a.coordinator_key or not a.output:raise EvidenceError('coordinator_report_inputs_required')
            print(canonical({'substantive_sha256':write_report(a.output,a.store,a.coordinator_key)}));return 1
        if not a.session_id or not a.resume_key:raise EvidenceError('exact_session_and_private_resume_key_required')
        if a.review:return terminal(a.store,a.session_id,a.resume_key)
        session,_,_=read_session(a.store,a.session_id,a.resume_key,verify_primary=False)
        clock=LocalClock(session.protocol.measurement_kind,session.protocol.timing_enabled)
        # A new clock epoch is not used for elapsed arithmetic on terminal state changes.
        point=ClockObservation(timestamp_utc=None,kind=M.NONE)
        if a.invalidate and not a.coordinator_key:raise EvidenceError('coordinator_capability_required_to_invalidate')
        action=A.WITHDRAW if a.withdraw else A.INVALIDATE
        act(a.store,a.session_id,a.resume_key,action,point,**({'invalid_code':'coordinator_invalidated','coordinator_key':a.coordinator_key} if a.invalidate else {}));return 0
    except KeyboardInterrupt:return 130
    except (ValueError,TypeError,KeyError,IndexError,OSError,RecursionError):
        print(canonical({'error_code':'pilot_blocked_or_invalid_no_private_details','exit_code':2}));return 2


if __name__=='__main__':raise SystemExit(main())
