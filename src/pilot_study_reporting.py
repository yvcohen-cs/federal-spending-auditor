"""Aggregate-only private study reports, with withdrawn/invalid data excluded."""
from collections import Counter
from html import escape
from pathlib import Path
import hashlib

from .evidence_io import EvidenceError,EvidenceRoot,canonical,digest,strict_json
from .review_packet_io import atomic_create,new_directory
from .pilot_session_models import MeasurementKind as M,SessionState as S
from .pilot_session_rules import replay
from .pilot_session_store import inspect_environment,private_location,_private_fd,LIMIT
from .pilot_taskset import preparation


def aggregate(summaries,kind):
    selected=[s for s in summaries if s.kind is kind and s.eligible_for_aggregation]
    measured_sessions=sum(s.measured_responses>0 for s in selected)
    if not selected or kind is M.HUMAN and len(selected)<2:
        return {'status':'NOT_MEASURED','reason':'no_eligible_sessions_or_human_small_cell_suppression','metrics':None}
    metrics={name:sum(getattr(s,name) for s in selected) for name in ('tasks_attempted','tasks_completed','needs_more_evidence','escalations',
        'invalid_submissions','uncertainty_responses','reference_agreements','reference_denominator','measured_responses','not_measured_responses','invalid_timing_responses')}
    timing_allowed=measured_sessions>0 and (kind is not M.HUMAN or measured_sessions>=2)
    metrics.update(presentation_duration_ns=sum(s.presentation_duration_ns or 0 for s in selected) if timing_allowed else None,
        decision_duration_ns=sum(s.decision_duration_ns or 0 for s in selected) if timing_allowed else None,
        timing_status=kind.value if timing_allowed else M.NONE.value,
        timing_denominator='valid_recorded_response_intervals_only_no_missing_values_imputed',
        reference_scope='authored_narrow_property_agreement_not_award_correctness',
        cohort='eligible_consented_completed_and_in_progress_sessions_excludes_withdrawn_invalidated_not_started')
    if kind is M.HUMAN and not timing_allowed:
        metrics['measured_responses']=None;metrics['not_measured_responses']=None;metrics['invalid_timing_responses']=None
    return {'status':kind.value,'metrics':metrics}


def report(store,coordinator_key):
    p,tasks,sessions,histories=inspect_environment(store,coordinator_key,verify_primary=False)
    summaries=[replay(s,tasks,histories[sid])[0] for sid,s in sessions.items()]
    eligible=any(s.eligible_for_aggregation for s in summaries)
    if eligible:
        # Full independent source/task rebuild before any positive metrics.
        p2,t2,s2,h2=inspect_environment(store,coordinator_key,verify_primary=True)
        if (p,tasks,sessions,histories)!=(p2,t2,s2,h2):raise EvidenceError('study_changed_during_aggregate')
    states={state.value:sum(s.state is state for s in summaries) for state in S}
    return {'schema_type':'PilotStudyReport','schema_version':1,'version':'pilot-study-report-v1','preparation':preparation(),
        'protocol':p.to_dict(),'task_set_digest':tasks.task_set_digest,'evidence_inventory_digest':tasks.evidence_inventory_digest,
        'software_control_validation':{'scope':'bounded_local_schema_chain_receipt_source_and_privacy_checks_not_human_performance',
            'session_log_validation':'verified','source_task_revalidation':'verified' if eligible else 'NOT_EVALUATED_all_sessions_excluded_or_not_started',
            'financial_authorization':False},
        'synthetic_study_observations':aggregate(summaries,M.SIMULATED),
        'actual_human_study_observations':aggregate(summaries,M.HUMAN),
        'actual_human_study_status':'LOCAL_AUTHORIZED_RECORDS_PRESENT_NOT_IDENTITY_AUTHENTICATION' if any(s.kind is M.HUMAN and s.tasks_completed for s in summaries) else 'NOT_CONDUCTED',
        'unmeasured_outcomes':{'actual_human_usability':'UNKNOWN','actual_human_throughput':'UNKNOWN','actual_reviewer_accuracy':'NOT_MEASURED_no_award_ground_truth'},
        'session_states':states,'excluded_sessions':{'withdrawn':states[S.WITHDRAWN.value],'invalidated':states[S.INVALIDATED.value],
            'excluded_response_count':sum(s.tasks_completed for s in summaries if s.state in (S.WITHDRAWN,S.INVALIDATED))},
        'unresolved_tasks':sum(len(tasks.entries)-s.tasks_completed for s in summaries if s.eligible_for_aggregation),
        'privacy':{'participant_labels_in_report':False,'session_ids_in_report':False,'response_text_or_event_histories_in_report':False,
            'rankings':False,'human_minimum_eligible_cell_size':2,'identity_assurance':'UNKNOWN_local_capabilities_are_not_people'},
        'readiness':[{'dimension':d,'status':status,'scope':scope} for d,status,scope in (
            ('reviewer_interface_controls','PREPARED_OFFLINE','one_task_and_closed_choices_not_measured_usability'),
            ('task_completeness','CHECKED','source_bound_existing_C4_models'),('evidence_traceability','CHECKED' if eligible else 'NOT_EVALUATED','preserved_bytes_not_remote_authenticity'),
            ('consent_preparedness','PREPARED_ONLY','local_receipts_do_not_verify_voluntariness_or_comprehension'),
            ('privacy_protections','PREPARED_LIMITED','opaque_labels_closed_fields_owner_only_storage_no_anonymity_guarantee'),
            ('session_integrity','CHECKED_LOCAL','HMAC_receipts_and_order_not_proof_against_same_UID_or_privileged_actor'),
            ('decision_reproducibility','CHECKED_LOCAL','ordered_replay_no_financial_authority'),
            ('simulated_workflow','SIMULATED' if p.measurement_kind is M.SIMULATED else 'NOT_MEASURED','not_actual_human_performance'),
            ('actual_human_usability','UNKNOWN','requires_separately_authorized_voluntary_study'),
            ('actual_human_throughput','UNKNOWN','no_extrapolation_from_simulations'))],
        'blockers':{'small_human_study':['Separate owner/institutional authorization, voluntary consent and approved encrypted storage/retention.',
            'Approve batch-wide deletion policy or separately implement selective deletion before recruitment.','Actual usability/accessibility and timing remain unmeasured.'],
            'SAM_validation':['Approved authorized credential and bounded source-validation plan remain separate; no live collection here.'],
            'revision_conditioned_finances':['Source-native identity/revision/correction/deletion, monetary basis and complete history proof obligations remain unresolved.'],
            'limited_production':['No production authorization; human usability, source validation, authentication/privacy and frozen readiness gates remain separate.']},
        'financial_eligibility_changed':False,'frozen_readiness_upgrade':False,'production_screening_authorized':False,
        'recommendation':'Phase 4C6: coordinator dry-run/governance sign-off, then separately authorized small human pilot; no production screening.'}


def markdown(value):
    lines=['# Phase 4C5 pilot preparation','', 'Actual human study status: '+value['actual_human_study_status'],
        'No participant labels, session identifiers, individual profiles or financial authorization.','', '## Session completion','',
        '    '+canonical(value['session_states']),'', '## Synthetic observations','', '    '+canonical(value['synthetic_study_observations']),
        '', '## Actual human observations','', '    '+canonical(value['actual_human_study_observations'])]
    for key in sorted(value):
        if key not in ('session_states','synthetic_study_observations','actual_human_study_observations'):
            lines.extend(['','## '+key,'','    '+canonical(value[key])])
    return '\n'.join(lines)+'\n'


def html(value):return '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>Pilot preparation</title><h1>Pilot preparation</h1><pre>'+escape(markdown(value))+'</pre></html>'


def write_report(path,store,coordinator_key):
    value=report(store,coordinator_key);target=private_location(path)
    source=Path(store).absolute()
    if source==target or source in target.parents:raise EvidenceError('study_report_must_be_separate_from_private_store')
    files={'study.json':(canonical({'report':value,'substantive_sha256':digest(value)})+'\n').encode(),
        'study.md':markdown(value).encode(),'study.html':html(value).encode()}
    if sum(map(len,files.values()))>LIMIT:raise EvidenceError('study_report_limit')
    new_directory(target)
    with EvidenceRoot(target,max_bytes=LIMIT,max_total_bytes=2*LIMIT) as root:
        for name,raw in files.items():atomic_create(root.fd,name,raw)
        if value!=report(store,coordinator_key):raise EvidenceError('study_changed_during_report')
        atomic_create(root.fd,'study-report-commit.json',(canonical({'schema_type':'PilotStudyReportCommit','schema_version':1,
            'files':{n:hashlib.sha256(raw).hexdigest() for n,raw in files.items()}})+'\n').encode())
    return digest(value)


def read_report(path,store,coordinator_key):
    with EvidenceRoot(path,max_bytes=LIMIT,max_total_bytes=2*LIMIT,max_files=4) as root:
        _private_fd(root.fd);data={n:root.read(n) for n in root.discover()}
        if set(data)!={'study.json','study.md','study.html','study-report-commit.json'}:raise EvidenceError('truncated_study_report')
        expected={'schema_type':'PilotStudyReportCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in data.items() if n!='study-report-commit.json'}}
        if strict_json(data['study-report-commit.json'].data)!=expected:raise EvidenceError('study_report_hash_conflict')
        doc=strict_json(data['study.json'].data);value=report(store,coordinator_key)
        if doc!={'report':value,'substantive_sha256':digest(value)} or data['study.md'].data!=markdown(value).encode() or data['study.html'].data!=html(value).encode():
            raise EvidenceError('study_report_not_primary_projection')
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in data.items()}:raise EvidenceError('study_report_changed')
    return value
