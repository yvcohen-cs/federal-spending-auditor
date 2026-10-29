"""Deterministic readiness tables and safe offline output, reusing C6 actions."""
from html import escape

from .evidence_io import EvidenceError,EvidenceRoot,digest,strict_json
from .history_reporting import bounded_json
from .pilot_store import PilotStore
from .readiness_models import ReadinessAssessment
from .readiness_rules import remediation,conclusions,measurement
from .review_packet_io import outside
from .review_packet_models import RecommendedVerificationAction

BASELINES=(
    {'phase':'4A','numerator':12,'denominator':24,'unit':'original_technically_completed_selected_slots','cohort':'original_frozen_pilot','kind':'historical_reference_not_recomputed'},
    {'phase':'4B1','numerator':24,'denominator':24,'unit':'technically_reanalyzed_selected_slots','cohort':'same_frozen_pilot_recovery','kind':'historical_reference_not_collection_completeness'},
    {'phase':'4B2','numerator':18,'denominator':58,'unit':'verified_in_scope_occurrences','cohort':'separate_three_query_bounded_probe','kind':'historical_reference_not_population_precision'},
    {'phase':'4B3','numerator':331,'denominator':None,'unit':'observed_pair_results','cohort':'frozen_pilot_history_evaluation','breakdown':{'scope_uncertain':238,'insufficient_counterpart_history':75,'revision_unknown':18},'kind':'historical_reference_rule_specific'})


def projection(assessment):
    assessment=ReadinessAssessment.from_dict(assessment.to_dict())
    names=sorted({m.name for c in assessment.cohorts for s in c.slots for m in s.measurements})
    measurements=[]
    for name in names:
        n,d,complete=measurement(assessment.cohorts,name)
        units={m.unit for c in assessment.cohorts for s in c.slots for m in s.measurements if m.name==name}
        if len(units)!=1: raise EvidenceError('readiness_measurement_unit_conflict')
        measurements.append({'name':name,'numerator':n,'denominator':d,'unit':next(iter(units)),'complete':complete})
    frozen_dimensions,frozen_hard,frozen_modes=conclusions(assessment.cohorts[:1])
    next_step=RecommendedVerificationAction(instruction='Resolve supported native parent/query context and primary revision lineage; validate an authorized bounded SAM schema/pagination contract before requesting larger financial screening.')
    return {'schema_type':'ReadinessResearchReport','schema_version':1,'assessment':assessment.to_dict(substantive=True),
        'measurements':measurements,'baseline_references':list(BASELINES),
        'auxiliary_cohort_measurements':[{'cohort':c.role,**m.to_dict()} for c in assessment.cohorts for m in c.auxiliary_measurements],
        'cohort_interpretation':'Historical baselines, frozen reanalysis, and holdout have separate units and are not interchangeable rates.',
        'frozen_only_mode_matrix':[m.to_dict() for m in frozen_modes],
        'remediation_backlog':remediation(assessment.cohorts),
        'modernization':{'kind':'documentation_review_plus_unknown_authenticated_capability','reviewed_on':'2026-10-28',
            'sources':['https://open.gsa.gov/api/contract-awards/','https://sam.gov/fpds'],
            'authenticated_live_verification':'not_performed','authentication_availability':'not_established_for_authorized_API_use',
            'existing_adapter':'sam-contract-awards-v1-first-page_contractId_only',
            'supported_boundary':'fixed_HTTPS_endpoint_native_identifiers_one_page_environment_auth_opt_in',
            'unsupported_features':['validated_continuation','positive_parent_absence_rules','common_revision_certificate','complete_history_or_deletions','SAM_to_C5_financial_mapping','scale_entitlement'],
            'migration_prerequisites':['authorized_account_and_bounded_public_capture','paging_and_strict_response_contract','native_identity_parent_and_action_validation',
                'revision_correction_deletion_financial_definitions','freshness_history_and_scale_evidence','human_reviewed_parallel_validation_before_separate_replacement_approval'],
            'lineage':'shared_procurement_data_not_independent_corroboration'},
        'next_engineering_milestone':next_step.to_dict(),
        'human_verification_requirements':['Review usability and throughput are unmeasured','Confirm source-native revision/correction evidence','Validate authorized SAM access and source-specific coverage criteria'],
        'assumptions':['Feasibility labels are engineering estimates','Sorted bounded prefixes and frozen diversity sample are not probability samples'],
        'decision_scope':'Mode-specific evidence readiness only; no collection authorization or financial correctness inference.'}


def text_report(report):
    a=report['assessment'];lines=['Federal contract screening readiness (readiness-protocol-v1)',
        'Technical completion is separate from evidentiary reliability. No mode decision authorizes collection.',
        'Protocol digest: '+digest(a['protocol']),'Implementation: '+a['implementation_commit']+' / '+a['implementation_sha256'],'',
        '| Dimension | Result | Numerator / denominator | Unit | Rule and rationale |','|---|---|---|---|---|']
    def cell(v): return str(v).replace('|',' / ').replace('\n',' ')
    for d in a['dimensions']:
        lines.append('| '+' | '.join(cell(v) for v in (d['name'],d['result'],str(d['numerator'])+' / '+str(d['denominator']),d['unit'],d['rule']+'; '+d['rationale']))+' |')
    lines.extend(['','| Proposed mode | Decision | Blockers | Conditions |','|---|---|---|---|'])
    for m in a['modes']: lines.append('| '+' | '.join(cell(v) for v in (m['mode'],m['result'],', '.join(m['blockers']),', '.join(m['conditions'])))+' |')
    lines.append('\nFrozen-pilot-only mode decisions (separate scope from combined holdout assessment):')
    lines.extend(m['mode']+': '+m['result'] for m in report['frozen_only_mode_matrix'])
    lines.append('\nNon-negotiable controls:')
    lines.extend(g['name']+': '+g['result']+'; '+g['rationale'] for g in a['hard_gates'])
    lines.append('\nDerived measurements (explicit units; unknown totals are not known zero):')
    lines.extend(str(m) for m in report['measurements'])
    lines.extend(str(m) for m in report['auxiliary_cohort_measurements'])
    lines.append('\nHistorical source references, not interchangeable metrics:')
    lines.extend(str(b) for b in report['baseline_references'])
    lines.append('\nEngineering remediation by affected slots, estimated feasibility, and evidence quality:')
    lines.extend(str(r) for r in report['remediation_backlog'])
    lines.append('\nSource facts and evidence references:')
    for c in a['cohorts']:
        lines.append(c['role']+': sample='+str(c['sample_sha256'])+' inventory='+str(c['inventory_sha256'])+'; '+str(c['limitations']))
        lines.extend(str(r) for r in c['evidence'])
        for s in c['slots']:
            for r in s['evidence']: lines.append(str(r))
    lines.append('\nSAM modernization: '+str(report['modernization']))
    lines.append('Assumptions: '+str(report['assumptions']))
    lines.append('Human verification requirements: '+str(report['human_verification_requirements']))
    lines.append('Next milestone: '+report['next_engineering_milestone']['instruction'])
    return '\n'.join(lines)+'\n'


def html_report(report):
    return '<!doctype html><meta charset="utf-8"><title>Evidence readiness</title><h1>Federal contract evidence readiness</h1><pre>'+escape(text_report(report))+'</pre>'


def write_readiness(path,assessment,*,protected=()):
    target=outside(path,protected);report=projection(assessment)
    payload=bounded_json({'report':report,'substantive_sha256':digest(report),'executed_at_utc':assessment.executed_at_utc})
    text=text_report(report).encode();html=html_report(report).encode()
    if sum(map(len,(payload,text,html)))>32*1024*1024: raise EvidenceError('readiness_output_byte_limit')
    with PilotStore(target,{'schema_type':'ReadinessOutputPlan','schema_version':1,'protocol_sha256':assessment.protocol.protocol_sha256,
            'config':{'max_run_bytes':40*1024*1024}}) as store:
        store.write_bytes('readiness.json',payload);store.write_bytes('readiness.md',text);store.write_bytes('readiness.html',html)
        store.write('readiness-commit.json',{'schema_type':'ReadinessOutputCommit','schema_version':1,'files':store.inventory()})
    return digest(report)


def read_readiness(path):
    with EvidenceRoot(path,max_bytes=32*1024*1024,max_total_bytes=40*1024*1024) as root:
        snapshots={n:root.read(n) for n in root.discover()}
        if set(snapshots)!={'readiness.json','readiness.md','readiness.html','readiness-commit.json','pilot-plan.json'}:
            raise EvidenceError('incomplete_readiness_output')
        expected={'schema_type':'ReadinessOutputCommit','schema_version':1,'files':{n:s.byte_sha256 for n,s in snapshots.items() if n!='readiness-commit.json'}}
        if strict_json(snapshots['readiness-commit.json'].data)!=expected: raise EvidenceError('readiness_output_hash_conflict')
        doc=strict_json(snapshots['readiness.json'].data)
        if set(doc)!={'report','substantive_sha256','executed_at_utc'}: raise EvidenceError('unsupported_readiness_wrapper')
        from dataclasses import replace
        assessment=replace(ReadinessAssessment.from_dict(doc['report']['assessment']),executed_at_utc=doc['executed_at_utc'])
        plan={'schema_type':'ReadinessOutputPlan','schema_version':1,'protocol_sha256':assessment.protocol.protocol_sha256,'config':{'max_run_bytes':40*1024*1024}}
        if strict_json(snapshots['pilot-plan.json'].data)!=plan: raise EvidenceError('readiness_output_plan_conflict')
        report=projection(assessment)
        if doc['report']!=report or doc['substantive_sha256']!=digest(report): raise EvidenceError('readiness_projection_conflict')
        if snapshots['readiness.md'].data!=text_report(report).encode() or snapshots['readiness.html'].data!=html_report(report).encode():
            raise EvidenceError('readiness_readable_projection_conflict')
        for n,s in snapshots.items():
            if root.read(n,recheck=True).byte_sha256!=s.byte_sha256: raise EvidenceError('readiness_output_changed')
        if set(root.discover())!=set(snapshots): raise EvidenceError('readiness_output_changed')
    return assessment
