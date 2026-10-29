"""Deterministic operational research reports; no production readiness upgrade."""
from collections import Counter
from html import escape

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .history_reporting import bounded_json
from .pilot_store import PilotStore
from .review_packet_io import outside
from .review_validation_models import EvidenceStatus, ReviewKind, workflow_spec
from .review_validation_events import read_decisions, review_states, validate_decisions, tasks_for_log
from .review_validation_tasks import build_tasks, validate_primary, check_new_location
from .review_validation_study import protocol, PROTOCOL_SHA, replay_study

READINESS=('evidence_traceability','review_task_completeness','decision_reproducibility','contradiction_handling',
    'security_integrity','reviewer_attribution','human_usability','actual_reviewer_throughput',
    'historical_source_completeness','financial_comparison_authorization')


def task_report(root,manifest,events):
    validate_primary(root,manifest);validate_decisions(manifest,events)
    states={s['task_id']:s for s in review_states(manifest,events)}
    return {'tasks':[{'definition':t.to_dict(),'source_packet':next(p.to_dict() for p in manifest.packets.packets if p.packet_id==t.packet_id),
        'automated_observations':{'category':'AUTOMATED OBSERVATION','fields':[f.to_dict() for f in t.observed_fields]},
        'automated_assessments':{'category':'AUTOMATED ASSESSMENT','dimensions':[d.to_dict() for d in t.dimensions]},
        'review_state':states[t.task_id], 'review_history':[e.to_dict() for e in events if e.task_id==t.task_id],
        'unrecorded_review_metadata':None if any(e.task_id==t.task_id for e in events) else
            {'reviewer_attribution':None,'decision_rationale':None,'review_timestamp':None,'category':'UNKNOWN'}} for t in manifest.tasks],
        'source_inventory_sha256':digest(strict_json(manifest.source_inventory_json.encode())),
        'task_manifest_sha256':manifest.substantive_sha256,
        'source_history_summary':{'rule':manifest.history.rule_version,'coverage':[c.to_dict() for c in manifest.history.coverage],
            'comparison_statuses':dict(Counter(c.status.value for c in manifest.history.comparisons)),
            'limitations':'No history, freshness or revision guarantee is conferred by review.'},
        'parent_assessments':[a.to_dict() for a in manifest.parent.assessments],
        'financial_eligibility_changed':False,'frozen_readiness_upgrade':False}


def readiness(study,valid_tasks,conflicts,controls_ok,has_events):
    rows=[]
    for dimension in READINESS:
        status='UNKNOWN';scope='untested_operational_assumption';rationale='No actual human usability or throughput study has been completed.'
        if dimension in ('evidence_traceability','review_task_completeness','decision_reproducibility','contradiction_handling','security_integrity'):
            status='DEMONSTRATED_OFFLINE' if controls_ok and valid_tasks else 'NOT_DEMONSTRATED'
            scope='authored_simulation_and_bounded_revalidation_only' if study else 'inspected_local_evidence_only'
            rationale='Bounded structural checks, primary replay and preserved assertions; no source-authenticity or human-performance guarantee.'
            if dimension=='contradiction_handling' and not conflicts: status='NOT_EVALUATED'
            if dimension=='decision_reproducibility' and not has_events: status='NOT_EVALUATED'
        elif dimension=='reviewer_attribution':
            status='UNKNOWN';rationale='Explicit simulated/self-reported labels are traceable; no authenticated reviewer identity or role established.'
        elif dimension=='historical_source_completeness': rationale='Partial/unknown source histories remain unknown regardless of reviewer acceptance.'
        elif dimension=='financial_comparison_authorization':
            status='NOT_AUTHORIZED_BY_REVIEW';rationale='Evidence acceptance cannot change C5/history financial eligibility or enable new arithmetic.'
        rows.append({'dimension':dimension,'status':status,'scope':scope,'rationale':rationale})
    return rows


def report(*,study_root=None,source_root=None,decision_log=None,kind=None,packet_bundle=None):
    if (study_root is None)==(source_root is None): raise EvidenceError('one_explicit_offline_review_input_required')
    if study_root is not None and any(v is not None for v in (decision_log,kind,packet_bundle)):
        raise EvidenceError('study_inputs_are_frozen')
    cases=[];events=[];source=None;source_sha=None
    if study_root is not None:
        cases,source_sha=replay_study(study_root)
        tasks=[t for c in cases for t in c['tasks']]
        events=[e for c in cases for h in c.get('simulated_histories',()) for e in h['events']]
        conflicts=sum(c.get('contradictory_simulated_decisions',False) for c in cases)
        controls=all(c['expected_control_met'] for c in cases)
        profile='SIMULATED REVIEW'
    else:
        manifest=tasks_for_log(source_root,decision_log,packet_bundle=packet_bundle) if decision_log else build_tasks(source_root,packet_bundle=packet_bundle)
        if decision_log:
            if not isinstance(kind,ReviewKind): raise EvidenceError('explicit_decision_log_kind_required')
            event_objects=read_decisions(decision_log,source_root,manifest,kind)
        else:
            if kind is not None: raise EvidenceError('review_kind_without_log')
            event_objects=()
        source=task_report(source_root,manifest,event_objects);tasks=source['tasks'];events=[e.to_dict() for e in event_objects]
        source_sha=source['source_inventory_sha256'];conflicts=sum(s['contradiction'] for s in review_states(manifest,event_objects))
        controls=True;profile='SIMULATED REVIEW' if kind is ReviewKind.SIMULATED else 'ACTUAL HUMAN REVIEW' if events else 'UNKNOWN'
    distribution=Counter(d['status'] for t in tasks for d in t['definition']['dimensions'])
    citations=[c for t in tasks for c in t['definition']['citations']]
    obligations=Counter(o for t in tasks for o in t['definition']['missing_proof_obligations'])
    simulated=sum(e['kind']==ReviewKind.SIMULATED.value for e in events)
    human=sum(e['kind']==ReviewKind.HUMAN.value for e in events)
    metrics={'attempted_study_cases':len(cases) if study_root else None,'validated_tasks':len(tasks),
        'distinct_task_ids':len({t['definition']['task_id'] for t in tasks}),
        'blocked_integrity_controls':sum(c['integrity_blocked'] for c in cases) if study_root else None,
        'traceable_tasks':len(tasks),'review_state_consistency':'validated_against_all_preserved_events',
        'decision_replay_valid_events':len(events),'report_integrity_policy':'primary_recompute_plus_exact_JSON_Markdown_HTML_commit',
        'complete_task_definitions':len(tasks),'task_completeness_denominator':len(tasks),
        'primary_citation_occurrences':len(citations),'valid_primary_citation_occurrences':len(citations),
        'unique_citation_ids':len({c['citation_id'] for c in citations}),
        'decision_events':len(events),'simulated_decision_events':simulated,'self_reported_human_decision_events':human,
        'contradictory_decision_task_contexts':conflicts,'missing_obligation_occurrences':sum(obligations.values()),
        'expected_study_controls_met':controls if study_root else None,
        'actual_human_accuracy':None,'actual_human_acceptance':None,'actual_human_throughput':None,
        'units':'tasks_citation_occurrences_and_assertions_separate_not_population_accuracy_or_performance'}
    return {'schema_type':'ReviewValidationReport','schema_version':1,'version':'review-validation-report-v1',
        'protocol':protocol(),'workflow_specification':workflow_spec(),'profile':profile,'source_inventory_sha256':source_sha,
        'epistemic_categories':['AUTOMATED OBSERVATION','AUTOMATED ASSESSMENT','SIMULATED REVIEW','ACTUAL HUMAN REVIEW','UNKNOWN'],
        'metrics':metrics,'evidence_status_distribution':{s.value:distribution[s.value] for s in EvidenceStatus},
        'missing_proof_obligations':dict(sorted(obligations.items())),'cases':cases,'source_review':source,
        'operational_readiness':readiness(study_root is not None,len(tasks),conflicts,controls,bool(events)),
        'simulated_sequences':['A','B'] if study_root else None,
        'decision_reproducibility':'primary_source_and_ordered_event_replay_verified_not_human_reliability' if events else 'NOT_EVALUATED',
        'human_study':{'status':'NOT_CONDUCTED','participants':None,'results':None,'usability':'UNKNOWN','throughput':'UNKNOWN'},
        'actual_human_attribution_limit':'Self-reported entries, when explicitly supplied, are not authenticated identities or completed usability research.',
        'financial_eligibility_changed':False,'frozen_readiness_upgrade':False,
        'production_screening_authorized':{'100_awards':False,'500_awards':False,'5000_awards':False},
        'operational_blockers':['No completed actual human usability, accuracy, timing or throughput study.',
            'Reviewer labels are unauthenticated; no identity, role or multiuser authorization established.',
            'Source histories, freshness and common revisions remain unknown; acceptance cannot enable financial arithmetic.',
            'Local hash chains require a separately trusted tip/inventory to detect a fully coherent rewrite or suffix deletion.',
            'Simulations test software invariants only; no population inference or reviewer efficiency claim.'],
        'recommendations':['Phase 4C5: conduct the preregistered small human usability study with explicit consent and pseudonymous attribution.',
            'Keep decisions independent and blinded before adjudicating disagreements using new primary evidence.',
            'Validate attribution/authentication, source lifecycle completeness and financial proof obligations separately before any operational proposal.']}


def text_report(value):
    lines=['# Phase 4C4 review workflow validation','', 'Profile: '+value['profile'],
        'Actual human study: NOT CONDUCTED; usability and throughput UNKNOWN.',
        'No new financial authorization or production screening.','', '## Metrics','', '    '+canonical(value['metrics']),
        '', '## Operational readiness','', '| Dimension | Evidence state | Scope |','|---|---|---|']
    lines.extend('| '+r['dimension']+' | '+r['status']+' | '+r['scope']+' |' for r in value['operational_readiness'])
    for key in sorted(value):
        if key not in ('metrics','operational_readiness'):
            lines.extend(['','## '+key,'','    '+canonical(value[key])])
    return '\n'.join(lines)+'\n'


def html_report(value):
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'; form-action \'none\'"><title>Review workflow validation</title><h1>Review workflow validation</h1><pre>'+escape(text_report(value))+'</pre></html>'


def output_plan():
    return {'schema_type':'ReviewValidationOutputPlan','schema_version':1,'protocol_sha256':PROTOCOL_SHA,'config':{'max_run_bytes':32*1024*1024}}


def protected_inputs(inputs):
    return tuple(v for k,v in inputs.items() if k in ('study_root','source_root','decision_log','packet_bundle') and v is not None)


def write_report(path,value,**inputs):
    if value!=report(**inputs): raise EvidenceError('review_validation_report_not_primary_projection')
    target=check_new_location(outside(path,protected_inputs(inputs)),study=True)
    raw=bounded_json({'report':value,'substantive_sha256':digest(value)})
    text=text_report(value).encode();html=html_report(value).encode()
    if sum(map(len,(raw,text,html)))>32*1024*1024: raise EvidenceError('review_validation_output_limit')
    with PilotStore(target,output_plan()) as store:
        store.write_bytes('review-validation.json',raw);store.write_bytes('review-validation.md',text);store.write_bytes('review-validation.html',html)
        if value!=report(**inputs): raise EvidenceError('review_validation_inputs_changed_during_write')
        store.write('review-validation-commit.json',{'schema_type':'ReviewValidationOutputCommit','schema_version':1,'files':store.inventory()})
    return digest(value)


def read_report(path,**inputs):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=64*1024*1024,max_files=5) as root:
        data={n:root.read(n) for n in root.discover()}
        if set(data)!={'pilot-plan.json','review-validation.json','review-validation.md','review-validation.html','review-validation-commit.json'}:
            raise EvidenceError('incomplete_review_validation_output')
        expected={'schema_type':'ReviewValidationOutputCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in data.items() if n!='review-validation-commit.json'}}
        if strict_json(data['review-validation-commit.json'].data)!=expected or strict_json(data['pilot-plan.json'].data)!=output_plan():
            raise EvidenceError('review_validation_output_hash_or_plan_conflict')
        doc=strict_json(data['review-validation.json'].data);value=doc['report']
        if value!=report(**inputs) or doc!={'report':value,'substantive_sha256':digest(value)}:
            raise EvidenceError('review_validation_report_projection_conflict')
        if data['review-validation.md'].data!=text_report(value).encode() or data['review-validation.html'].data!=html_report(value).encode():
            raise EvidenceError('review_validation_readable_projection_conflict')
        if {n:root.read(n,recheck=True).byte_sha256 for n in root.discover()}!={n:s.byte_sha256 for n,s in data.items()}:
            raise EvidenceError('review_validation_output_changed')
    return value
