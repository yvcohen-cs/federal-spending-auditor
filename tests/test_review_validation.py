"""Offline authored workflow controls; no actual participants or network calls."""
from copy import deepcopy
from dataclasses import replace
import fcntl
from pathlib import Path
import shutil
from unittest.mock import Mock

import pytest

from src.evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from src.review_events import WorkflowState as W
from src.review_packet_models import RecommendedVerificationAction
from src.review_validation_models import (DecisionRationale, ReviewerDecisionEvent, ReviewerDecisionInput,
    ReviewerTask, ReviewerTaskManifest, ReviewDecision as D, ReviewKind as K, EvidenceStatus as S)
from src.review_validation_tasks import build_tasks, inventory, validate_primary
from src.review_validation_events import (append_decision,read_decisions,validate_decisions,review_states,notes)
from src.review_validation_study import create_study,selected_tasks,replay_study,protocol,study_inventory
from src.review_validation_reporting import report,write_report,read_report,html_report,task_report
from src.review_validation import main


@pytest.fixture(scope='module')
def study(tmp_path_factory):
    return create_study(tmp_path_factory.mktemp('review-study')/'source')


@pytest.fixture(scope='module')
def study_rows(study):
    return replay_study(study)[0]


@pytest.fixture(scope='module')
def baseline(study):
    source=study/'verified_identity'/'source'
    return source,selected_tasks(source)


def rationale(task,**changes):
    value=dict(interpretation='Authored test assertion about evidence quality.',scope_explanation='Narrow saved claim only; no arithmetic authority.',
        uncertainty='Missing proof obligations remain unresolved.',citation_ids=tuple(sorted(c.citation_id for c in task.citations)),
        acknowledged_obligations=task.missing_proof_obligations)
    value.update(changes);return DecisionRationale(**value)


def append(path,source,manifest,decision=D.ACCEPT,**changes):
    t=manifest.tasks[0]
    params=dict(task_id=t.task_id,decision=decision,rationale=rationale(t),kind=K.SIMULATED,
        attribution_label='SIMULATED:test-sequence',timestamp_utc='2025-02-01T00:00:00Z',
        follow_up=(RecommendedVerificationAction(instruction='Obtain missing source proof.',citation_ids=(t.citations[0].citation_id,)),))
    params.update(changes)
    return append_decision(path,source,manifest,**params)


def rewrite(path,name,change):
    v=strict_json((path/name).read_bytes());change(v);(path/name).write_text(canonical(v)+'\n')


def resign_report(path):
    hashes=inventory(path)
    value={'schema_type':'ReviewValidationOutputCommit','schema_version':1,
        'files':{n:s for n,s in hashes.items() if n!='review-validation-commit.json'}}
    (path/'review-validation-commit.json').write_text(canonical(value)+'\n')


def pure_event(baseline):
    source,m=baseline;t=m.tasks[0];r=rationale(t)
    from src.review_events import ReviewWorkflowEvent
    w=ReviewWorkflowEvent(packet_manifest_sha256=m.packets.substantive_sha256,packet_id=t.packet_id,claim_id=t.claim_id,
        sequence=0,previous_event_id=None,state=W.PENDING_REVIEW,reviewer='SIMULATED:test-sequence',
        notes=notes(D.ACCEPT,r,K.SIMULATED),timestamp_utc='2025-02-01T00:00:00Z')
    return ReviewerDecisionEvent(task_manifest_sha256=m.substantive_sha256,task_id=t.task_id,previous_decision_event_id=None,
        decision=D.ACCEPT,rationale=r,kind=K.SIMULATED,attribution_label=w.reviewer,workflow_event=w)


@pytest.mark.parametrize('case_id', [c['case_id'] for c in protocol()['cases']])
def test_preregistered_twelve_case_focus_and_decisions(study_rows,case_id):
    row=next(r for r in study_rows if r['case_id']==case_id)
    assert row['expected_control_met'] is True
    if case_id=='tampered_reference':
        assert row['integrity_blocked'] and not row['tasks'] and not row['simulated_histories']
    else:
        assert len(row['tasks'])==1 and len(row['simulated_histories'])==2
        assert [h['sequence'] for h in row['simulated_histories']]==['A','B']


def test_simulated_study_metrics_no_actual_human_performance(study):
    value=report(study_root=study);m=value['metrics']
    assert m['attempted_study_cases']==12 and m['validated_tasks']==11 and m['blocked_integrity_controls']==1
    assert m['decision_events']==m['simulated_decision_events']==22
    assert m['self_reported_human_decision_events']==0
    assert m['contradictory_decision_task_contexts']==1
    assert value['human_study']=={'status':'NOT_CONDUCTED','participants':None,'results':None,'usability':'UNKNOWN','throughput':'UNKNOWN'}
    assert m['actual_human_accuracy'] is m['actual_human_acceptance'] is m['actual_human_throughput'] is None
    assert all(v is False for v in value['production_screening_authorized'].values())
    assert value['financial_eligibility_changed'] is value['frozen_readiness_upgrade'] is False
    readiness={r['dimension']:r['status'] for r in value['operational_readiness']}
    assert readiness['human_usability']==readiness['actual_reviewer_throughput']==readiness['historical_source_completeness']=='UNKNOWN'
    assert readiness['financial_comparison_authorization']=='NOT_AUTHORIZED_BY_REVIEW'


def test_two_separate_simulations_preserve_disagreement_without_winner(study):
    rows,_=replay_study(study);case=next(c for c in rows if c['case_id']=='duplicate_records')
    assert case['contradictory_simulated_decisions'] is True
    assert {h['events'][0]['decision'] for h in case['simulated_histories']}=={'ACCEPT_EVIDENCE','REJECT_EVIDENCE'}
    assert 'no winner selected' in case['disagreement_action']


def test_rejected_candidate_parent_context_never_hidden_by_packet_selection(study):
    m=selected_tasks(study/'contradictory_parent'/'source');t=m.tasks[0]
    assert t.context_citation_ids and set(t.context_citation_ids).isdisjoint(t.packet_citation_ids)
    assert len(t.citations)>len(m.packets.packets[0].citations)
    assert next(d for d in t.dimensions if d.name=='parent').status is S.CONFLICTING
    assert any('SYNTH-OTHER-PARENT' in f.original_json for f in t.observed_fields)


def test_models_stable_native_strings_provenance_and_round_trip(baseline):
    _,m=baseline;t=m.tasks[0]
    assert ReviewerTaskManifest.from_dict(m.to_dict())==m
    assert ReviewerTask.from_dict(t.to_dict())==t
    assert all(t.initial_reviewer_attribution is None for t in m.tasks)
    assert t.initial_review_timestamp is t.initial_decision_rationale is None
    assert any(f.original_json=='"0001"' for f in t.observed_fields)
    assert all(c.evidence.reference.locator and c.evidence.artifact.sha256 for c in t.citations)
    assert all(c.evidence.artifact.representation.value=='response_bytes' for c in t.citations)
    assert tuple(d.value for d in t.permitted_decisions)==tuple(d.value for d in D)


@pytest.mark.parametrize('changes',[
    {'review_can_authorize_finances':True},{'initial_reviewer_attribution':'invented'},
    {'initial_review_timestamp':'2025-01-01T00:00:00Z'},{'initial_decision_rationale':'invented'},
    {'citations':()},{'observed_fields':()},{'limitations':()},{'missing_proof_obligations':()},
    {'permitted_decisions':(D.ACCEPT,)},{'packet_citation_ids':()},{'source_snapshot_sha256':'bad'},
    {'rule_version':'review-task-v2'},
])
def test_invalid_task_cannot_hide_unknowns_or_fabricate_review(baseline,changes):
    with pytest.raises((ValueError,TypeError)):replace(baseline[1].tasks[0],**changes)


@pytest.mark.parametrize('field', ['dimensions','claim','claim_id','packet_id','observed_fields'])
def test_forged_task_projection_fails_even_with_valid_schema(baseline,field):
    _,m=baseline;doc=m.to_dict();t=doc['tasks'][0]
    if field=='dimensions':
        for d in t[field]:
            if d['name']=='revision':d['status']='VERIFIED'
    elif field=='observed_fields':t[field][0]['original_json']='"forged"'
    elif field=='packet_id':t[field]='review-packet:v1:'+'0'*64
    else:t[field]='forged'
    with pytest.raises((ValueError,TypeError)):ReviewerTaskManifest.from_dict(doc)


@pytest.mark.parametrize('change',[
    {'interpretation':''},{'scope_explanation':''},{'uncertainty':''},{'interpretation':'x\x00y'},
    {'interpretation':'x'*2049},{'citation_ids':()},{'citation_ids':('z','a')},
    {'acknowledged_obligations':('z','a')},
])
def test_structured_rationale_required(baseline,change):
    with pytest.raises((ValueError,TypeError)):rationale(baseline[1].tasks[0],**change)


@pytest.mark.parametrize('cls_name',['task','manifest','event','rationale','input'])
@pytest.mark.parametrize('version',[0,2,True,'1',None])
def test_unsupported_schema_versions_rejected(baseline,cls_name,version):
    _,m=baseline;e=pure_event(baseline)
    v=ReviewerDecisionInput(task_id=m.tasks[0].task_id,decision=D.ACCEPT,rationale=e.rationale,kind=K.SIMULATED,
        attribution_label=e.attribution_label,timestamp_utc=e.workflow_event.timestamp_utc)
    obj={'task':m.tasks[0],'manifest':m,'event':e,'rationale':e.rationale,'input':v}[cls_name]
    doc=obj.to_dict();doc['schema_version']=version
    with pytest.raises((ValueError,TypeError)):type(obj).from_dict(doc)


@pytest.mark.parametrize('bad',['','{','[]','null','{"x":1,"x":2}','{"x":NaN}','\xff'])
def test_malformed_json_fail_closed(tmp_path,bad):
    with pytest.raises((ValueError,TypeError)):ReviewerDecisionInput.from_dict(strict_json(bad.encode()))


@pytest.mark.parametrize('change',[
    {'financial_authorization':True},{'task_id':'review-task:v1:'+'0'*64},
    {'task_manifest_sha256':'0'*64},{'previous_decision_event_id':'review-decision:v1:'+'0'*64},
])
def test_forged_decision_context_and_financial_authority_rejected(baseline,change):
    e=pure_event(baseline)
    with pytest.raises((ValueError,TypeError)):validate_decisions(baseline[1],(replace(e,**change),))


@pytest.mark.parametrize('label,kind', [('real-person',K.SIMULATED),('SIMULATED:pretend',K.HUMAN),('',K.HUMAN),('x'*129,K.HUMAN)])
def test_attribution_never_fakes_actual_participants(baseline,label,kind):
    e=pure_event(baseline)
    with pytest.raises((ValueError,TypeError)):
        replace(e,attribution_label=label,kind=kind,workflow_event=replace(e.workflow_event,reviewer=label))


@pytest.mark.parametrize('state',[W.CLOSED,W.REVIEWED,W.NEEDS_MORE_EVIDENCE])
def test_unauthorized_initial_workflow_status_rejected(baseline,state):
    e=pure_event(baseline);e=replace(e,workflow_event=replace(e.workflow_event,state=state))
    with pytest.raises(EvidenceError):validate_decisions(baseline[1],(e,))


def test_append_only_accept_reject_conflict_no_finance_upgrade(tmp_path,baseline):
    source,m=baseline;before=inventory(source);log=tmp_path/'log'
    first=append(log,source,m);old=inventory(log)
    second=append(log,source,m,D.REJECT,attribution_label='SIMULATED:independent-sequence',timestamp_utc='2025-02-02T00:00:00Z')
    assert all(inventory(log)[n]==sha for n,sha in old.items())
    events=read_decisions(log,source,m,K.SIMULATED,expected_tip=second.decision_event_id)
    assert len(events)==2 and events[0]==first
    assert review_states(m,events)[0]['review_state']=='CONFLICTING_REVIEW'
    assert review_states(m,events)[0]['financial_authorization'] is False
    assert inventory(source)==before
    assert m.packets.financial_run==build_tasks(source).packets.financial_run


@pytest.mark.parametrize('decision',[D.MORE,D.ESCALATE])
def test_unresolved_decisions_require_follow_up(tmp_path,baseline,decision):
    source,m=baseline
    with pytest.raises(EvidenceError):append(tmp_path/'no',source,m,decision,follow_up=())
    assert not (tmp_path/'no').exists()


def test_unknown_citations_and_hidden_obligations_rejected_before_write(tmp_path,baseline):
    source,m=baseline;t=m.tasks[0]
    for r in (rationale(t,citation_ids=('citation:v1:'+'0'*64,)),rationale(t,acknowledged_obligations=())):
        with pytest.raises(EvidenceError):append(tmp_path/'no',source,m,rationale=r)
    assert not (tmp_path/'no').exists()


@pytest.mark.parametrize('attack',['duplicate','reorder','wrong_previous','wrong_timestamp','unknown_extra','missing_context','malformed','torn'])
def test_event_history_attacks_fail_closed(tmp_path,baseline,attack):
    source,m=baseline;log=tmp_path/'log';append(log,source,m)
    append(log,source,m,D.REJECT,timestamp_utc='2025-02-02T00:00:00Z')
    a=log/'decision-000000.json';b=log/'decision-000001.json'
    if attack=='duplicate':b.write_bytes(a.read_bytes())
    elif attack=='reorder':raw=a.read_bytes();a.write_bytes(b.read_bytes());b.write_bytes(raw)
    elif attack=='wrong_previous':rewrite(log,b.name,lambda e:e.__setitem__('previous_decision_event_id',None))
    elif attack=='wrong_timestamp':rewrite(log,b.name,lambda e:e['workflow_event'].__setitem__('timestamp_utc','2024-01-01T00:00:00Z'))
    elif attack=='unknown_extra':(log/'extra.json').write_text('{}')
    elif attack=='missing_context':(log/'review-context.json').unlink()
    elif attack=='malformed':b.write_text('{')
    else:(log/'decision-000002.json.partial').write_text('{}')
    with pytest.raises((ValueError,TypeError)):read_decisions(log,source,m,K.SIMULATED)


def test_duplicate_submission_rejected_without_overwriting_old_bytes(tmp_path,baseline):
    source,m=baseline;log=tmp_path/'log';append(log,source,m);before=inventory(log)
    with pytest.raises(EvidenceError,match='duplicate'):append(log,source,m)
    assert inventory(log)==before


def test_trusted_tip_detects_suffix_truncation(tmp_path,baseline):
    source,m=baseline;log=tmp_path/'log';append(log,source,m)
    last=append(log,source,m,D.REJECT,timestamp_utc='2025-02-02T00:00:00Z')
    (log/'decision-000001.json').unlink()
    with pytest.raises(EvidenceError,match='tip'):read_decisions(log,source,m,K.SIMULATED,expected_tip=last.decision_event_id)


def test_simulated_and_self_reported_human_histories_cannot_mix(tmp_path,baseline):
    source,m=baseline;log=tmp_path/'log';append(log,source,m)
    with pytest.raises((ValueError,TypeError)):
        append(log,source,m,kind=K.HUMAN,attribution_label='provided-test-pseudonym',timestamp_utc='2025-02-02T00:00:00Z')
    assert len(read_decisions(log,source,m,K.SIMULATED))==1


def test_human_attribution_is_self_reported_not_authenticated_study(tmp_path,baseline):
    source,m=baseline;log=tmp_path/'log'
    append(log,source,m,kind=K.HUMAN,attribution_label='provided-test-pseudonym')
    v=report(source_root=source,decision_log=log,kind=K.HUMAN)
    assert v['profile']=='ACTUAL HUMAN REVIEW' and v['metrics']['self_reported_human_decision_events']==1
    assert v['human_study']['status']=='NOT_CONDUCTED' and v['human_study']['participants'] is None
    assert 'not authenticated' in v['actual_human_attribution_limit']


@pytest.mark.parametrize('name',['c3_attempt_000000.body','c3_attempt_000001.json','c3_checkpoint.json'])
def test_changed_source_after_review_invalidates_decision_replay(tmp_path,baseline,name):
    source,_=baseline;copy=tmp_path/'source';shutil.copytree(source,copy);m=selected_tasks(copy)
    log=tmp_path/'log';append(log,copy,m);(copy/name).write_bytes(b'{}')
    with pytest.raises((ValueError,TypeError)):read_decisions(log,copy,m,K.SIMULATED)


def test_path_traversal_nested_source_and_symlinks_rejected(tmp_path,baseline):
    source,m=baseline
    with pytest.raises((ValueError,OSError)):append(source/'nested',source,m)
    link=tmp_path/'linked';link.symlink_to(source,target_is_directory=True)
    with pytest.raises((ValueError,OSError)):build_tasks(link)
    log=tmp_path/'log';append(log,source,m);(log/'evil').symlink_to(source/'c3_plan.json')
    with pytest.raises((ValueError,OSError)):read_decisions(log,source,m,K.SIMULATED)


def test_append_interruption_preserves_published_event_and_retry_is_not_duplicate(tmp_path,baseline,monkeypatch):
    import src.review_validation_events as module
    source,m=baseline;real=module.atomic_create
    def interrupted(fd,name,raw):
        real(fd,name,raw)
        if name.startswith('decision-'):raise KeyboardInterrupt()
    monkeypatch.setattr(module,'atomic_create',interrupted)
    log=tmp_path/'log'
    with pytest.raises(KeyboardInterrupt):append(log,source,m)
    assert len(read_decisions(log,source,m,K.SIMULATED))==1
    with pytest.raises(EvidenceError,match='duplicate'):append(log,source,m)


def test_static_html_script_injection_and_markdown_literal_source_values(tmp_path,baseline):
    source,m=baseline;log=tmp_path/'log';t=m.tasks[0]
    append(log,source,m,rationale=rationale(t,interpretation='<script>alert(1)</script><img src="https://evil.test/track">'))
    value=report(source_root=source,decision_log=log,kind=K.SIMULATED);html=html_report(value)
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert '<img ' not in html and 'default-src' in html
    write_report(tmp_path/'out',value,source_root=source,decision_log=log,kind=K.SIMULATED)
    assert read_report(tmp_path/'out',source_root=source,decision_log=log,kind=K.SIMULATED)==value


@pytest.mark.parametrize('field,value',[
    ('financial_eligibility_changed',True),('frozen_readiness_upgrade',True),('profile','ACTUAL HUMAN REVIEW'),
    ('decision_reproducibility','all humans correct'),('human_study',{'status':'COMPLETED','participants':12}),
])
def test_rehashed_forged_report_cannot_authorize_or_fabricate_humans(tmp_path,baseline,field,value):
    source,_=baseline;v=report(source_root=source);out=tmp_path/'out';write_report(out,v,source_root=source)
    def forge(doc):doc['report'][field]=value;doc['substantive_sha256']=digest(doc['report'])
    rewrite(out,'review-validation.json',forge);resign_report(out)
    with pytest.raises(EvidenceError,match='projection'):read_report(out,source_root=source)


@pytest.mark.parametrize('name',['review-validation.json','review-validation.md','review-validation.html','review-validation-commit.json'])
def test_truncated_reports_or_generated_summaries_fail_closed(tmp_path,baseline,name):
    source,_=baseline;out=tmp_path/'out';write_report(out,report(source_root=source),source_root=source)
    (out/name).write_bytes((out/name).read_bytes()[:20])
    with pytest.raises((ValueError,TypeError)):read_report(out,source_root=source)


def test_rehashed_changed_markdown_rejected_independently(tmp_path,baseline):
    source,_=baseline;out=tmp_path/'out';write_report(out,report(source_root=source),source_root=source)
    (out/'review-validation.md').write_text('financial arithmetic approved')
    resign_report(out)
    with pytest.raises(EvidenceError,match='readable'):read_report(out,source_root=source)


def test_reports_are_stable_and_do_not_mutate_sources(tmp_path,baseline):
    source,_=baseline;before=inventory(source);v=report(source_root=source)
    assert write_report(tmp_path/'a',v,source_root=source)==write_report(tmp_path/'b',report(source_root=source),source_root=source)
    assert read_report(tmp_path/'a',source_root=source)==v and inventory(source)==before
    assert v['profile']=='UNKNOWN' and v['metrics']['decision_events']==0
    assert all(t['unrecorded_review_metadata']['reviewer_attribution'] is None for t in v['source_review']['tasks'])


def test_full_study_repeated_report_digests_and_integrity(tmp_path,study):
    before=study_inventory(study);v=report(study_root=study)
    a=write_report(tmp_path/'a',v,study_root=study);b=write_report(tmp_path/'b',report(study_root=study),study_root=study)
    assert a==b==digest(v) and read_report(tmp_path/'a',study_root=study)==v
    assert study_inventory(study)==before


def test_study_rehashed_plan_or_source_tamper_is_not_accepted(tmp_path,study):
    p=tmp_path/'study';shutil.copytree(study,p)
    rewrite(p,'study-plan.json',lambda d:d.__setitem__('network_requests',1))
    hashes=study_inventory(p)
    (p/'study-commit.json').write_text(canonical({'schema_type':'OfflineReviewStudyCommit','schema_version':1,'files':{n:s for n,s in hashes.items() if n!='study-commit.json'}}))
    with pytest.raises(EvidenceError):replay_study(p)


def test_cli_append_is_explicit_and_does_not_echo_private_labels(tmp_path,baseline,capsys):
    source,m=baseline;t=m.tasks[0];request=ReviewerDecisionInput(task_id=t.task_id,decision=D.MORE,rationale=rationale(t),kind=K.SIMULATED,
        attribution_label='SIMULATED:private-input-label',timestamp_utc='2025-02-01T00:00:00Z',
        follow_up=(RecommendedVerificationAction(instruction='Find missing evidence.'),))
    # CLI default selection is all packets; bind input to that exact selection.
    all_tasks=build_tasks(source);t=all_tasks.tasks[0]
    request=replace(request,task_id=t.task_id,rationale=rationale(t))
    input_path=tmp_path/'input.json';input_path.write_text(request.to_json());log=tmp_path/'log'
    assert main(['--root',str(source),'--decision-log',str(log),'--append-input',str(input_path)])==0
    assert 'private-input-label' not in capsys.readouterr().out
    assert main(['--root',str(source),'--decision-log',str(log),'--review-kind',K.SIMULATED.value,'--run-dir',str(tmp_path/'report')])==1
    assert main(['--root',str(source),'--append-input',str(input_path)])==2


def test_frozen_protocols_and_no_new_financial_or_readiness_authority():
    import hashlib
    for name,sha in protocol()['frozen_protocols'].items():
        assert hashlib.sha256((Path('docs')/name).read_bytes()).hexdigest()==sha
    assert protocol()['financial_authorization'] is protocol()['production_screening_authorized'] is False


@pytest.mark.parametrize('text',['api_key=DO_NOT_PRESERVE','Authorization: Bearer DO_NOT_PRESERVE','cookie=private'])
def test_credential_like_free_text_rejected_without_persistence(tmp_path,baseline,text):
    source,m=baseline
    with pytest.raises(ValueError):append(tmp_path/'no',source,m,rationale=rationale(m.tasks[0],interpretation=text))
    assert not (tmp_path/'no').exists()


def test_selected_task_log_reconstructs_exact_selection_for_reports(tmp_path,baseline):
    source,m=baseline;log=tmp_path/'log';append(log,source,m)
    v=report(source_root=source,decision_log=log,kind=K.SIMULATED)
    assert v['metrics']['validated_tasks']==1 and v['metrics']['decision_events']==1
    out=tmp_path/'out';write_report(out,v,source_root=source,decision_log=log,kind=K.SIMULATED)
    assert read_report(out,source_root=source,decision_log=log,kind=K.SIMULATED)==v


@pytest.mark.parametrize('marker',['pilot-plan.json','research-plan.json','c3_plan.json','output-manifest.json','review-context.json','study-plan.json'])
def test_demo_cannot_write_inside_managed_evidence_or_output(tmp_path,marker):
    protected=tmp_path/'protected';protected.mkdir();(protected/marker).write_text('{}');before=inventory(protected)
    with pytest.raises(EvidenceError):create_study(protected/'new')
    assert inventory(protected)==before


@pytest.mark.parametrize('marker',['pilot-plan.json','research-plan.json'])
def test_decision_log_cannot_be_nested_in_other_managed_run(tmp_path,baseline,marker):
    source,m=baseline;protected=tmp_path/'protected';protected.mkdir();(protected/marker).write_text('{}')
    with pytest.raises(EvidenceError):append(protected/'new-log',source,m)
    assert not (protected/'new-log').exists() and (protected/marker).read_text()=='{}'


def test_task_rule_inventory_includes_financial_native_parent_and_parser_versions(baseline):
    source,_=baseline;m=build_tasks(source)
    expected={m.packets.financial_run.rule_version}|{p.rule_version for p in m.parent.assessments}|{p.baseline.parser_version for p in m.parent.assessments}
    assert all(expected<=set(t.rule_versions) for t in m.tasks)
