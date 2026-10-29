"""SIMULATED-only local controls. No participant information or human consent."""
from dataclasses import replace
from datetime import datetime,timezone,timedelta
from pathlib import Path
import hashlib
import hmac
import os
import shutil
import stat

import pytest

from src.evidence_io import EvidenceError,canonical,digest,strict_json
from src.review_validation_study import create_study
from src.review_validation_tasks import inventory
from src.review_validation_models import ReviewDecision as D
from src.pilot_session_models import (PilotTaskSet,StudyProtocol,StudySession,ConsentReceipt,ClockObservation,TaskPresentation,
    ReviewerResponse,SessionEvent,SessionSummary,SessionAction as A,SessionState as S,ConsentState as C,MeasurementKind as M,
    StudyAuthorization,derived_rationale)
from src.pilot_taskset import build_task_set,make_protocol,preparation,pin_sources,revalidate_tasks,governance_sha
from src.pilot_session_store import (create_environment,enroll,read_session,append_event,inspect_environment,private_location)
from src.pilot_session_rules import replay,timing
from src.pilot_review import act,present,respond,terminal,demo,SimulatedClock,LocalClock,display_task,main
from src.pilot_study_reporting import report,write_report,read_report,aggregate,html


@pytest.fixture(scope='module')
def source_study(tmp_path_factory):return create_study(tmp_path_factory.mktemp('c5-controls')/'source')


@pytest.fixture(scope='module')
def task_set(source_study):return build_task_set(source_study)


@pytest.fixture(scope='module')
def empty_store(tmp_path_factory,task_set):
    p=tmp_path_factory.mktemp('c5-private')/'empty'
    create_environment(p,task_set,make_protocol(task_set,timing=True))
    return p


@pytest.fixture
def store(tmp_path,empty_store):
    p=tmp_path/'private';shutil.copytree(empty_store,p);return p,p/'coordinator.key'


def registered(store,label='SIM-aaaaaaaa00000001'):
    p,key=store;sid,resume=enroll(p,key,label);return p,key,sid,resume


def start(store):
    p,key,sid,resume=registered(store);s,t,e=read_session(p,sid,resume);clock=SimulatedClock()
    receipt=ConsentReceipt(protocol_id=s.protocol.protocol_id,governance_sha256=s.protocol.governance_sha256,kind=M.SIMULATED,state=C.GRANTED,
        voluntary=True,purpose_understood=True,withdrawal_understood=True,timing_acknowledged=True)
    act(p,sid,resume,A.CONSENT,ClockObservation(timestamp_utc=None,kind=M.NONE),consent=receipt);act(p,sid,resume,A.START,clock.point())
    return p,key,sid,resume,clock


def answer(p,sid,key,clock,*,decision=D.MORE):
    _,tasks,ev=read_session(p,sid,key);summary,*_=replay(read_session(p,sid,key)[0],tasks,ev)
    task=tasks.entries[summary.tasks_completed].task
    present(p,sid,key,clock.point());act(p,sid,key,A.BEGIN_RESPONSE,clock.point())
    return respond(p,sid,key,clock.point(),decision,'missing_proof',task.missing_proof_obligations or ('none_identified',),
        tuple(sorted(c.citation_id for c in task.citations)),'revision_lineage')


def rewrite(path,change):
    v=strict_json(path.read_bytes());change(v);path.write_text(canonical(v)+'\n')


def context_dir(store):return next(store.glob('session-*'))


def event_path(store,i):return context_dir(store)/f'event-{i:06d}.json'


@pytest.fixture(scope='module')
def completed_demo(tmp_path_factory,source_study):
    p=tmp_path_factory.mktemp('c5-demo')/'private';key=demo(p,source_study);return p,key


def test_preregistered_demo_states_and_withdrawal_exclusion(completed_demo):
    p,key=completed_demo;value=report(p,key);m=value['synthetic_study_observations']['metrics']
    assert value['session_states']=={'NOT_STARTED':0,'IN_PROGRESS':1,'COMPLETED':1,'WITHDRAWN':1,'INVALIDATED':1}
    assert m['tasks_completed']==m['tasks_attempted']==12
    assert value['excluded_sessions']=={'withdrawn':1,'invalidated':1,'excluded_response_count':1}
    assert m['needs_more_evidence']==8 and m['escalations']==1 and m['invalid_submissions']==1
    assert m['uncertainty_responses']==12 and m['measured_responses']==12
    assert m['presentation_duration_ns']==13*10**9 and m['decision_duration_ns']==12*10**9
    assert value['actual_human_study_observations']['status']=='NOT_MEASURED'
    assert value['actual_human_study_observations']['metrics'] is None
    assert value['actual_human_study_status']=='NOT_CONDUCTED'
    assert value['financial_eligibility_changed'] is value['frozen_readiness_upgrade'] is value['production_screening_authorized'] is False


def test_aggregate_has_no_labels_session_ids_or_profiles(completed_demo):
    value=report(*completed_demo);raw=canonical(value)
    assert 'SIM-aaaaaaaa' not in raw and 'study-session:v1:' not in raw and 'resume.key' not in raw
    assert not value['privacy']['participant_labels_in_report'] and not value['privacy']['rankings']
    assert value['unmeasured_outcomes']['actual_human_usability']=='UNKNOWN'
    assert value['unmeasured_outcomes']['actual_human_throughput']=='UNKNOWN'


def test_fixed_task_set_fields_order_and_no_public_ground_truth(task_set):
    assert len(task_set.entries)==11
    assert PilotTaskSet.from_dict(task_set.to_dict())==task_set
    assert task_set.entries[0].reference_decision is D.ACCEPT
    assert all(e.reference_decision is None for e in task_set.entries[1:])
    assert task_set.entries[0].task.review_can_authorize_finances is False
    assert any(d.name=='revision' and d.status.value=='INSUFFICIENT' for e in task_set.entries for d in e.task.dimensions)
    assert any(e.logical_root=='unavailable_capture' for e in task_set.entries)


@pytest.mark.parametrize('attack',['reverse','duplicate','remove','invent_reference','wrong_origin'])
def test_altered_task_selection_or_reference_fails(task_set,attack):
    with pytest.raises((ValueError,TypeError)):
        entries=task_set.entries
        if attack=='reverse':entries=entries[::-1]
        elif attack=='duplicate':entries=(entries[0],)*11
        elif attack=='remove':entries=entries[:-1]
        elif attack=='invent_reference':entries=(entries[0],replace(entries[1],reference_decision=D.ACCEPT,reference_scope='authored_narrow_property_only_not_award_truth'))+entries[2:]
        else:entries=(replace(entries[0],origin='preserved_public_unverified',reference_decision=None),)+entries[1:]
        replace(task_set,entries=entries)


@pytest.mark.parametrize('label',['Alice Example','name@example.test','123456789','127.0.0.1','P-1234567890123456','P-aaaaaaaa00000001',
    'SIM-1234567890123456','SIM-../../../../etc','SIM-<script>','SIM-AAAAAAAA00000001',''])
def test_identifying_or_invalid_labels_never_create_session(store,label):
    p,key=store;before=inventory(p)
    with pytest.raises((ValueError,TypeError)):enroll(p,key,label)
    assert inventory(p)==before and not list(p.glob('session-*'))


def test_duplicate_pseudonym_and_session_id_collision_refused(store):
    p,key,sid,resume=registered(store);before=inventory(p)
    with pytest.raises(EvidenceError,match='duplicate'):enroll(p,key,'SIM-aaaaaaaa00000001')
    assert inventory(p)==before
    s,_,_=read_session(p,sid,resume)
    assert StudySession.from_dict(s.to_dict()).session_id==sid


def test_initial_consent_not_invented_and_start_requires_receipt(store):
    p,key,sid,resume=registered(store);s,t,e=read_session(p,sid,resume)
    assert s.state is S.NOT_STARTED and s.consent is C.NOT_REQUESTED and e==()
    with pytest.raises(EvidenceError):act(p,sid,resume,A.START,SimulatedClock().point())
    assert read_session(p,sid,resume)[2]==()


@pytest.mark.parametrize('change',[{'voluntary':False},{'purpose_understood':False},{'withdrawal_understood':False},
    {'state':C.WITHDRAWN},{'kind':M.NONE}])
def test_invalid_consent_model(change,task_set):
    p=make_protocol(task_set,timing=True)
    v=dict(protocol_id=p.protocol_id,governance_sha256=p.governance_sha256,kind=M.SIMULATED,state=C.GRANTED,
        voluntary=True,purpose_understood=True,withdrawal_understood=True,timing_acknowledged=True)
    v.update(change)
    with pytest.raises((ValueError,TypeError)):ConsentReceipt(**v)


@pytest.mark.parametrize('change',[{'protocol_id':'study-protocol:v1:'+'0'*64},{'governance_sha256':'0'*64},
    {'kind':M.HUMAN}])
def test_consent_context_and_timing_ack_required(store,change):
    p,key,sid,resume=registered(store);s,_,_=read_session(p,sid,resume)
    v=dict(protocol_id=s.protocol.protocol_id,governance_sha256=s.protocol.governance_sha256,kind=M.SIMULATED,state=C.GRANTED,
        voluntary=True,purpose_understood=True,withdrawal_understood=True,timing_acknowledged=True);v.update(change)
    r=ConsentReceipt(**v)
    with pytest.raises(EvidenceError):act(p,sid,resume,A.CONSENT,ClockObservation(timestamp_utc=None,kind=M.NONE),consent=r)
    assert not read_session(p,sid,resume)[2]


def test_decline_records_no_responses_and_is_terminal(store):
    p,key,sid,resume=registered(store);s,t,_=read_session(p,sid,resume);clock=SimulatedClock()
    r=ConsentReceipt(protocol_id=s.protocol.protocol_id,governance_sha256=s.protocol.governance_sha256,kind=M.SIMULATED,state=C.DECLINED,
        voluntary=False,purpose_understood=False,withdrawal_understood=False,timing_acknowledged=False)
    act(p,sid,resume,A.CONSENT,ClockObservation(timestamp_utc=None,kind=M.NONE),consent=r)
    summary,*_=replay(s,t,read_session(p,sid,resume)[2]);assert summary.state is S.WITHDRAWN and summary.tasks_completed==0
    with pytest.raises(EvidenceError):act(p,sid,resume,A.START,clock.point())


def test_human_enrollment_requires_separate_authorization_without_recording_humans(tmp_path,task_set):
    with pytest.raises(ValueError):make_protocol(task_set,kind=M.HUMAN,timing=False,instance_id='BATCH-bbbbbbbb00000001')
    p=replace(make_protocol(task_set),measurement_kind=M.HUMAN,selection_version='pilot-mixed-v1')
    with pytest.raises(ValueError):StudySession(protocol=p,pseudonym='P-aaaaaaaa00000001',resume_capability_sha256='0'*64)
    with pytest.raises(EvidenceError):create_environment(tmp_path/'human-empty',task_set,p)
    assert not (tmp_path/'human-empty').exists()
    with pytest.raises(EvidenceError):make_protocol(task_set,kind=M.HUMAN)


@pytest.mark.parametrize('field',['owner_authorized','privacy_storage_ready','voluntary_recruitment_ready'])
def test_unapproved_authorization_template_is_not_approval(task_set,field):
    p=make_protocol(task_set)
    v=dict(protocol_id=p.protocol_id,task_set_digest=p.task_set_digest,governance_sha256=p.governance_sha256,
        reference='APP-aaaaaaaa00000001',owner_authorized=True,privacy_storage_ready=True,voluntary_recruitment_ready=True);v[field]=False
    with pytest.raises(ValueError):StudyAuthorization(**v)


@pytest.mark.parametrize('cls', [StudyProtocol,ClockObservation,ConsentReceipt,TaskPresentation,ReviewerResponse,SessionEvent,StudySession,SessionSummary,PilotTaskSet,StudyAuthorization])
@pytest.mark.parametrize('version',[0,2,True,'1',None])
def test_unsupported_schema_versions_fail(cls,version):
    with pytest.raises(ValueError):cls.from_dict({'schema_type':cls.__name__,'schema_version':version})


@pytest.mark.parametrize('bad',['','{','[]','null','{"x":1,"x":2}','{"x":NaN}'])
def test_malformed_session_json_rejected(bad):
    with pytest.raises((ValueError,TypeError)):SessionEvent.from_dict(strict_json(bad.encode()))


def test_authorized_resume_keeps_state_and_source_bytes(store):
    p,key,sid,resume,clock=start(store);_,tasks,_=read_session(p,sid,resume)
    before={e.source_root:inventory(e.source_root) for e in tasks.entries}
    answer(p,sid,resume,clock);act(p,sid,resume,A.SUSPEND,clock.point())
    act(p,sid,resume,A.RESUME,clock.point())
    s,t,e=read_session(p,sid,resume);summary,*_=replay(s,t,e)
    assert summary.state is S.IN_PROGRESS and summary.tasks_completed==1
    assert {root:inventory(root) for root in before}==before


def test_wrong_capability_and_stale_submission_refused(store,tmp_path):
    p,key,sid,resume,clock=start(store);wrong=tmp_path/'wrong';wrong.mkdir(mode=0o700);f=wrong/'resume.key';f.write_text('a'*64+'\n');f.chmod(0o600)
    with pytest.raises(EvidenceError):read_session(p,sid,f)
    before=inventory(p)
    with pytest.raises(EvidenceError):append_event(p,sid,resume,expected_tip=None,action=A.RESUME,clock=clock.point())
    assert inventory(p)==before


def test_one_task_order_begin_and_response_replay(store):
    p,key,sid,resume,clock=start(store);present(p,sid,resume,clock.point())
    with pytest.raises(EvidenceError):present(p,sid,resume,clock.point())
    s,t,e=read_session(p,sid,resume);_,active,*_=replay(s,t,e)
    with pytest.raises(EvidenceError):act(p,sid,resume,A.COMPLETE,clock.point())
    act(p,sid,resume,A.BEGIN_RESPONSE,clock.point());task=t.entries[0].task
    first=respond(p,sid,resume,clock.point(),D.MORE,'missing_proof',task.missing_proof_obligations,
        tuple(sorted(c.citation_id for c in task.citations)),'complete_capture')
    with pytest.raises(EvidenceError):act(p,sid,resume,A.RESPOND,clock.point(),response=first.response)


@pytest.mark.parametrize('attack',['missing_citation','wrong_citation','bad_uncertainty','bad_rationale','no_ack','financial_override','no_follow_up'])
def test_invalid_structured_response_cannot_be_saved(store,attack):
    p,key,sid,resume,clock=start(store);present(p,sid,resume,clock.point());act(p,sid,resume,A.BEGIN_RESPONSE,clock.point())
    s,t,e=read_session(p,sid,resume);_,active,*_=replay(s,t,e);task=t.entries[0].task;cids=tuple(sorted(c.citation_id for c in task.citations));point=clock.point()
    v=dict(presentation_id=active.presentation_id,task_id=task.task_id,decision=D.MORE,reason_code='missing_proof',
        uncertainty_codes=task.missing_proof_obligations,citation_ids=cids,proof_acknowledged=True,follow_up_code='complete_capture',
        rationale=derived_rationale(task,'missing_proof',task.missing_proof_obligations,cids),clock=point)
    if attack=='missing_citation':v['citation_ids']=()
    elif attack=='wrong_citation':v['citation_ids']=('citation:v1:'+'0'*64,)
    elif attack=='bad_uncertainty':v['uncertainty_codes']=('invented',)
    elif attack=='bad_rationale':v['rationale']=replace(v['rationale'],interpretation='forged interpretation')
    elif attack=='no_ack':v['proof_acknowledged']=False
    elif attack=='financial_override':v['financial_authorization']=True
    else:v['follow_up_code']='none'
    before=inventory(p)
    with pytest.raises((ValueError,TypeError)):
        r=ReviewerResponse(**v);act(p,sid,resume,A.RESPOND,point,response=r)
    assert inventory(p)==before


def test_withdrawal_after_response_excludes_all_prior_performance(store):
    p,key,sid,resume,clock=start(store);answer(p,sid,resume,clock)
    assert report(p,key)['synthetic_study_observations']['metrics']['tasks_completed']==1
    act(p,sid,resume,A.WITHDRAW,clock.point());v=report(p,key)
    assert v['synthetic_study_observations']['metrics'] is None and v['excluded_sessions']['excluded_response_count']==1
    with pytest.raises(EvidenceError):act(p,sid,resume,A.RESUME,clock.point())


@pytest.mark.parametrize('attack',['event_delete','event_reorder','event_duplicate','receipt_delete','receipt_reorder','receipt_forge','partial','context_forge'])
def test_forged_truncated_or_reordered_logs_fail_closed(store,attack):
    p,key,sid,resume,clock=start(store)
    if attack=='event_delete':event_path(p,1).unlink()
    elif attack=='event_reorder':
        a,b=event_path(p,0),event_path(p,1);raw=a.read_bytes();a.write_bytes(b.read_bytes());b.write_bytes(raw)
    elif attack=='event_duplicate':event_path(p,1).write_bytes(event_path(p,0).read_bytes())
    elif attack=='receipt_delete':sorted(p.glob('receipt-*'))[-1].unlink()
    elif attack=='receipt_reorder':
        a,b=sorted(p.glob('receipt-*'))[:2];raw=a.read_bytes();a.write_bytes(b.read_bytes());b.write_bytes(raw)
    elif attack=='receipt_forge':rewrite(sorted(p.glob('receipt-*'))[-1],lambda d:d.__setitem__('event_id','forged'))
    elif attack=='partial':(context_dir(p)/'event-000002.json.partial').write_text('{}');(context_dir(p)/'event-000002.json.partial').chmod(0o600)
    else:rewrite(context_dir(p)/'context.json',lambda d:d.__setitem__('pseudonym','SIM-aaaaaaaa00000002'))
    with pytest.raises((ValueError,TypeError)):read_session(p,sid,resume)
    with pytest.raises((ValueError,TypeError)):report(p,key)


def test_hmac_receipt_cannot_be_forged_by_recomputing_public_hash(store):
    p,key,sid,resume,clock=start(store);f=sorted(p.glob('receipt-*'))[-1]
    def attack(d):d['event_sequence']=100;d['mac']=digest({k:v for k,v in d.items() if k!='mac'})
    rewrite(f,attack)
    with pytest.raises(EvidenceError,match='forged'):read_session(p,sid,resume)


def test_interruption_between_event_and_receipt_does_not_resume_silently(store,monkeypatch):
    import src.pilot_session_store as module
    p,key,sid,resume,clock=start(store);real=module._receipt
    def interrupted(*args,**kw):raise KeyboardInterrupt()
    monkeypatch.setattr(module,'_receipt',interrupted)
    with pytest.raises(KeyboardInterrupt):present(p,sid,resume,clock.point())
    with pytest.raises(EvidenceError):read_session(p,sid,resume)


@pytest.mark.parametrize('field,value',[('timestamp_utc','2024-01-01T00:00:00Z'),('monotonic_ns',0),('epoch','bbbbbbbbbbbbbbbb')])
def test_reordered_or_unannounced_clock_epoch_refused(store,field,value):
    p,key,sid,resume,clock=start(store);point=replace(clock.point(),**{field:value})
    with pytest.raises(EvidenceError):act(p,sid,resume,A.PRESENT,point,presentation=TaskPresentation(session_id=sid,
        task_id=read_session(p,sid,resume)[1].entries[0].task.task_id,position=0,event_sequence=2,clock=point))


def test_missing_and_cross_epoch_timing_never_defaults_to_zero():
    c=SimulatedClock();a,b,d=c.point(),c.point(),c.point()
    assert timing(a,b,d,M.SIMULATED)==(M.SIMULATED,10**9,10**9)
    missing=ClockObservation(timestamp_utc=None,kind=M.NONE)
    invalid=ClockObservation(timestamp_utc=None,kind=M.INVALID)
    assert timing(a,missing,d,M.SIMULATED)==(M.NONE,None,None)
    assert timing(a,b,replace(d,epoch='bbbbbbbbbbbbbbbb'),M.SIMULATED)==(M.NONE,None,None)
    assert timing(a,b,invalid,M.SIMULATED)==(M.INVALID,None,None)
    assert timing(a,b,replace(d,monotonic_ns=0),M.SIMULATED)==(M.INVALID,None,None)


def test_opt_out_clock_does_not_collect_timestamps_or_device_uptime():
    c=LocalClock(M.SIMULATED,False);point=c.point()
    assert point.timestamp_utc is point.monotonic_ns is point.epoch is None and point.kind is M.NONE
    timed=LocalClock(M.SIMULATED,True).point();assert timed.monotonic_ns<10**9


def test_terminal_one_task_no_identifying_raw_input_saved(store):
    p,key,sid,resume=registered(store);answers=iter(['1','1','1','1','1','person@example.test','q']);output=[]
    assert terminal(p,sid,resume,input_fn=lambda _:next(answers),output=output.append)==1
    assert sum(line.startswith('Task ') for line in output)==1
    raw=b''.join(f.read_bytes() for f in p.rglob('*') if f.is_file())
    assert b'person@example.test' not in raw and 'person@example.test' not in '\n'.join(output)
    value=report(p,key);assert value['synthetic_study_observations']['metrics']['invalid_submissions']==1
    assert value['synthetic_study_observations']['metrics']['tasks_completed']==0


@pytest.mark.parametrize('attack',['key_public','root_public','record_public','symlink_key','symlink_source'])
def test_permission_and_symlink_attacks(store,tmp_path,attack):
    p,key,sid,resume=registered(store)
    if attack=='key_public':resume.chmod(0o644)
    elif attack=='root_public':p.chmod(0o755)
    elif attack=='record_public':(context_dir(p)/'context.json').chmod(0o644)
    elif attack=='symlink_key':
        raw=resume.read_bytes();f=tmp_path/'other';f.write_bytes(raw);f.chmod(0o600);resume.unlink();resume.symlink_to(f)
    else:
        (p/'extra').symlink_to(p/'environment.json')
    with pytest.raises((ValueError,OSError)):read_session(p,sid,resume)


def test_path_traversal_git_and_nested_managed_stores_rejected(tmp_path):
    gitroot=tmp_path/'repo';gitroot.mkdir();(gitroot/'.git').mkdir();(gitroot/'.git'/'HEAD').write_text('ref: refs/heads/main')
    with pytest.raises(EvidenceError):private_location(gitroot/'private')
    managed=tmp_path/'managed';managed.mkdir();(managed/'pilot-plan.json').write_text('{}')
    with pytest.raises(EvidenceError):private_location(managed/'nested')
    with pytest.raises((ValueError,OSError)):private_location(tmp_path/'x'/'..'/'new')


def test_concurrent_local_writer_is_rejected(store):
    import fcntl
    from src.evidence_io import EvidenceRoot
    p,key=store
    with EvidenceRoot(p) as root:
        fcntl.flock(root.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises((OSError,ValueError)):enroll(p,key,'SIM-aaaaaaaa00000001')


def test_altered_task_json_and_missing_citations_fail(store):
    p,key=store
    rewrite(p/'task-set.json',lambda d:d['entries'][0]['task'].__setitem__('citations',[]))
    with pytest.raises((ValueError,TypeError)):inspect_environment(p,key)


def test_source_change_blocks_response_resume_and_report_but_withdrawal_remains_possible(tmp_path,task_set):
    copy=tmp_path/'source';shutil.copytree(task_set.entries[0].source_root,copy)
    entries=(replace(task_set.entries[0],source_root=str(copy)),)+task_set.entries[1:]
    changed=replace(task_set,entries=entries);store=tmp_path/'private';key=create_environment(store,changed,make_protocol(changed,timing=True))
    p,key,sid,resume,clock=start((store,key));answer(p,sid,resume,clock)
    (copy/'c3_attempt_000000.body').write_text('{}')
    with pytest.raises(EvidenceError):read_session(p,sid,resume)
    with pytest.raises(EvidenceError):report(p,key)
    act(p,sid,resume,A.WITHDRAW,clock.point())
    assert report(p,key)['excluded_sessions']['withdrawn']==1


@pytest.mark.parametrize('attack',['financial','human','states','summary','truncate_md','html_injection'])
def test_report_tampering_fails_even_with_rehashed_outer_commit(tmp_path,completed_demo,attack):
    p,key=completed_demo;out=tmp_path/'out';write_report(out,p,key)
    if attack in ('financial','human','states','summary'):
        def forge(d):
            if attack=='financial':d['report']['financial_eligibility_changed']=True
            elif attack=='human':d['report']['actual_human_study_status']='COMPLETED'
            elif attack=='states':d['report']['session_states']['WITHDRAWN']=0
            else:d['report']['synthetic_study_observations']['metrics']['tasks_completed']=999
            d['substantive_sha256']=digest(d['report'])
        rewrite(out/'study.json',forge)
    elif attack=='truncate_md':(out/'study.md').write_text('completed')
    else:(out/'study.html').write_text('<script>alert(1)</script>')
    commit={'schema_type':'PilotStudyReportCommit','schema_version':1,'files':{n:sha for n,sha in inventory(out).items() if n!='study-report-commit.json'}}
    (out/'study-report-commit.json').write_text(canonical(commit)+'\n');(out/'study-report-commit.json').chmod(0o600)
    with pytest.raises(EvidenceError):read_report(out,p,key)


def test_reports_repeat_digest_without_private_profiles(tmp_path,completed_demo):
    p,key=completed_demo;a=write_report(tmp_path/'a',p,key);b=write_report(tmp_path/'b',p,key)
    assert a==b and read_report(tmp_path/'a',p,key)==read_report(tmp_path/'b',p,key)
    raw=(tmp_path/'a'/'study.html').read_text();assert '<script' not in raw and 'default-src' in raw


def test_html_escaping_is_static_not_active_markup(completed_demo):
    value=report(*completed_demo);value['recommendation']='<script>track()</script><img src="https://evil.test/x">'
    raw=html(value);assert '<script>' not in raw and '<img ' not in raw and '&lt;script&gt;' in raw


def test_human_small_cells_suppressed_without_creating_participants(completed_demo):
    p,key=completed_demo;protocol,tasks,sessions,events=inspect_environment(p,key)
    one=next(replay(s,tasks,events[sid])[0] for sid,s in sessions.items() if replay(s,tasks,events[sid])[0].eligible_for_aggregation)
    # Pure schema/control fixture only; no OBSERVED_HUMAN session or consent is stored.
    hypothetical=replace(one,kind=M.HUMAN)
    assert aggregate([hypothetical],M.HUMAN)['metrics'] is None
    assert aggregate([],M.HUMAN)['status']=='NOT_MEASURED'


def test_no_large_scale_financial_or_frozen_readiness_authorization(completed_demo):
    value=report(*completed_demo)
    assert all(value[k] is False for k in ('financial_eligibility_changed','frozen_readiness_upgrade','production_screening_authorized'))
    assert all(r['status']=='UNKNOWN' for r in value['readiness'] if r['dimension'] in ('actual_human_usability','actual_human_throughput'))


def test_frozen_protocols_and_governance_unchanged():
    for name,sha in preparation()['frozen_protocols'].items():
        assert hashlib.sha256((Path('docs')/name).read_bytes()).hexdigest()==sha
    assert governance_sha()=='399471cfb597d245d7ae166bb3ee18dd46d46af7fb7d62b7c3f830038b5aa57f'


def test_invalidation_requires_coordinator_capability(store):
    p,key,sid,resume,clock=start(store);before=inventory(p)
    with pytest.raises(EvidenceError):act(p,sid,resume,A.INVALIDATE,clock.point(),invalid_code='coordinator_invalidated')
    assert inventory(p)==before
    act(p,sid,resume,A.INVALIDATE,clock.point(),invalid_code='coordinator_invalidated',coordinator_key=key)
    assert report(p,key)['excluded_sessions']['invalidated']==1


def test_completed_session_can_withdraw_and_stale_report_is_rejected(tmp_path,completed_demo):
    p0,k0=completed_demo;p=tmp_path/'copy';shutil.copytree(p0,p);key=p/'coordinator.key'
    protocol,tasks,sessions,histories=inspect_environment(p,key)
    sid=next(sid for sid,s in sessions.items() if replay(s,tasks,histories[sid])[0].state is S.COMPLETED)
    resume=p/('session-'+sid.removeprefix('study-session:v1:'))/'resume.key'
    out=tmp_path/'old-report';write_report(out,p,key)
    last=histories[sid][-1].clock
    now=replace(last,timestamp_utc=(datetime.fromisoformat(last.timestamp_utc)+timedelta(seconds=1)).isoformat(),monotonic_ns=last.monotonic_ns+10**9)
    act(p,sid,resume,A.WITHDRAW,now)
    with pytest.raises(EvidenceError):read_report(out,p,key)
    assert report(p,key)['synthetic_study_observations']['metrics']['tasks_completed']==1


def test_opt_out_session_stores_no_event_time_and_no_duration(tmp_path,task_set):
    p=tmp_path/'private';key=create_environment(p,task_set,make_protocol(task_set,timing=False))
    sid,resume=enroll(p,key,'SIM-aaaaaaaa00000001');s,t,_=read_session(p,sid,resume)
    clock=LocalClock(M.SIMULATED,False)
    receipt=ConsentReceipt(protocol_id=s.protocol.protocol_id,governance_sha256=s.protocol.governance_sha256,kind=M.SIMULATED,state=C.GRANTED,
        voluntary=True,purpose_understood=True,withdrawal_understood=True,timing_acknowledged=False)
    act(p,sid,resume,A.CONSENT,ClockObservation(timestamp_utc=None,kind=M.NONE),consent=receipt);act(p,sid,resume,A.START,clock.point())
    answer(p,sid,resume,clock)
    summary,*_=replay(s,t,read_session(p,sid,resume)[2]);assert summary.measured_responses==0 and summary.not_measured_responses==1
    assert summary.presentation_duration_ns is summary.decision_duration_ns is None
    assert all(e.clock.timestamp_utc is None for e in read_session(p,sid,resume)[2])


def test_resume_new_epoch_discards_abandoned_task_clock(store):
    p,key,sid,resume,clock=start(store);present(p,sid,resume,clock.point())
    old=clock.point();fresh=replace(old,epoch='bbbbbbbbbbbbbbbb',monotonic_ns=0)
    act(p,sid,resume,A.RESUME,fresh)
    pclock=replace(fresh,timestamp_utc='2025-03-01T00:00:10+00:00',monotonic_ns=10**9)
    present(p,sid,resume,pclock)
    s,t,e=read_session(p,sid,resume);summary,active,_,_,extra=replay(s,t,e)
    assert summary.tasks_attempted==1 and extra['presentations']==2 and extra['abandoned_presentations']==1
    assert summary.measured_responses==0 and active.clock.epoch=='bbbbbbbbbbbbbbbb'


def test_declining_terminal_consent_records_no_clock_or_response(store):
    p,key,sid,resume=registered(store);answers=iter(['2','2','2','2'])
    assert terminal(p,sid,resume,input_fn=lambda _:next(answers),output=lambda _:None)==1
    s,t,events=read_session(p,sid,resume)
    assert len(events)==1 and events[0].clock.timestamp_utc is None and events[0].clock.monotonic_ns is None
    summary,*_=replay(s,t,events);assert summary.state is S.WITHDRAWN and summary.tasks_completed==0


@pytest.mark.parametrize('changes',[{'needs_more_evidence':-1},{'reference_agreements':100},{'tasks_attempted':13},
    {'presentation_duration_ns':None},{'eligible_for_aggregation':False}])
def test_summary_cannot_invent_counts_timings_or_eligibility(completed_demo,changes):
    p,key=completed_demo;_,tasks,sessions,events=inspect_environment(p,key)
    summary=next(replay(s,tasks,events[sid])[0] for sid,s in sessions.items() if replay(s,tasks,events[sid])[0].state is S.COMPLETED)
    with pytest.raises(ValueError):replace(summary,**changes)


def test_participant_can_decline_timing_without_declining_study(store):
    p,key,sid,resume=registered(store);answers=iter(['1','1','1','2','q'])
    assert terminal(p,sid,resume,input_fn=lambda _:next(answers),output=lambda _:None)==1
    s,t,events=read_session(p,sid,resume);summary,*_=replay(s,t,events)
    assert summary.state is S.IN_PROGRESS and summary.consent is C.GRANTED
    assert events[0].consent.timing_acknowledged is False
    assert all(e.clock.kind is M.NONE and e.clock.timestamp_utc is None for e in events)


def test_measured_clock_without_consent_opt_in_is_rejected(store):
    p,key,sid,resume=registered(store);s,t,e=read_session(p,sid,resume)
    receipt=ConsentReceipt(protocol_id=s.protocol.protocol_id,governance_sha256=s.protocol.governance_sha256,kind=M.SIMULATED,state=C.GRANTED,
        voluntary=True,purpose_understood=True,withdrawal_understood=True,timing_acknowledged=False)
    act(p,sid,resume,A.CONSENT,ClockObservation(timestamp_utc=None,kind=M.NONE),consent=receipt)
    act(p,sid,resume,A.START,ClockObservation(timestamp_utc=None,kind=M.NONE))
    with pytest.raises(EvidenceError):present(p,sid,resume,SimulatedClock().point())


def test_reference_answer_cannot_be_assigned_to_ambiguous_control(task_set):
    uncertain=task_set.entries[1]
    with pytest.raises(ValueError):replace(task_set.entries[0],task=uncertain.task,selected_claim_ids=uncertain.selected_claim_ids)
