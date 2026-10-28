"""Preregistered categorical rules; no weights and no collection authorization."""
from .readiness_models import (CAUSES, CONTROLS, DIMENSIONS, MODES, Result as R, Decision as D,
    GateResult, ExpansionDecision)


def measurement(cohorts,name):
    items=[m for c in cohorts for s in c.slots for m in s.measurements if m.name==name]
    if not items: return None,None,False
    nums=[m.numerator for m in items];dens=[m.denominator for m in items]
    return (sum(v for v in nums if v is not None),sum(v for v in dens if v is not None) if any(v is not None for v in dens) else None,
        all(m.complete and m.numerator is not None for m in items) and len(items)==sum(c.selected_count for c in cohorts))


def full(n,d,complete):
    if not complete or n is None or not d: return R.UNKNOWN
    return R.PASS if n==d else R.CONDITIONAL if n>0 else R.FAIL


def mode_decisions(dimensions,hard_gates,*,distinct_holdout=False):
    values={d.name:d.result for d in dimensions}
    hard_fail=[g.name for g in hard_gates if g.result is R.FAIL]
    hard_unknown=[g.name for g in hard_gates if g.result is not R.PASS]
    core=('operational_integrity','evidence_provenance','reproducibility','security_bounded_collection')
    result=[]
    for mode in MODES:
        required=core if mode==MODES[0] else core+('source_access_api_stability','record_identity') if mode==MODES[1] else tuple(d for d in DIMENSIONS if d not in ('source_modernization','historical_coverage','revision_alignment','financial_comparability')) if mode==MODES[2] else DIMENSIONS
        blockers=['non_negotiable:'+c for c in hard_fail or hard_unknown]
        blockers.extend(d for d in core if values[d] is not R.PASS)
        conditions=[]
        if mode!=MODES[0]:
            if not distinct_holdout: blockers.append('successful_distinct_holdout_required')
            if mode==MODES[1]:
                blockers.extend(d for d in ('source_access_api_stability','record_identity') if values[d] not in (R.PASS,R.CONDITIONAL))
                conditions=['fixed_preapproved_budgets_and_manual_review','scope_and_revision_withholding_mandatory',
                    'research_only_no_financial_assurance_or_population_inference','human_acceptance_and_source_modernization_not_certified']
            else: blockers.extend(d for d in required if values[d] is not R.PASS)
        if mode==MODES[-1]: blockers.extend(('independent_scale_entitlement_unverified','review_throughput_unverified'))
        blockers=tuple(sorted(set(blockers)))
        if mode==MODES[2] and any(values[d] is not R.PASS for d in ('historical_coverage','revision_alignment','financial_comparability')):
            conditions=['validation_only_no_financial_screening_or_assurance','primary_history_and_revision_evidence_required_before_financial_claims']
        outcome=D.NO_GO if blockers else D.CONDITIONAL_GO if conditions else D.GO
        result.append(ExpansionDecision(mode=mode,result=outcome,required_dimensions=required,blockers=blockers,conditions=tuple(conditions)))
    return tuple(result)


def conclusions(cohorts):
    slots=[s for c in cohorts for s in c.slots]
    refs=tuple(sorted({r.evidence_id for s in slots for r in s.evidence}|{r.evidence_id for c in cohorts for r in c.evidence}))
    hard=[]
    for code in CONTROLS:
        bad=any(code in s.violations for s in slots) or code=='no_source_evidence_mutation' and any(not c.unchanged for c in cohorts)
        unknown=not slots or any(not s.processed or code in s.unknown_controls for s in slots) or any(not c.available for c in cohorts)
        state=R.FAIL if bad else R.UNKNOWN if unknown else R.PASS
        numerator=sum(s.processed and code not in s.violations+s.unknown_controls for s in slots)
        hard.append(GateResult(name=code,result=state,numerator=numerator,denominator=len(slots),unit='inspected_selected_slots',
            rule='any_observed_violation_blocks_all_modes_unknown_never_passes',rationale='Observed violation' if bad else 'Insufficient inspected control evidence' if unknown else 'Controls satisfied in inspected evidence and this read-only execution only',
            evidence_ids=refs,limitations=('not_a_universal_security_or_source_authenticity_certificate',)))
    hard=tuple(hard)
    holdouts=[c for c in cohorts if c.role=='holdout']
    distinct=bool(holdouts) and all(c.available and c.selected_count>0 and c.unchanged and all(s.processed for s in c.slots) for c in holdouts)
    original={s.selected_native_id for c in cohorts if c.role=='frozen_pilot' for s in c.slots if s.selected_native_id is not None}
    distinct=distinct and all(s.selected_native_id is not None and s.selected_native_id not in original for c in holdouts for s in c.slots)
    map_names={'operational_integrity':'operational_slots','source_access_api_stability':'source_http_success',
        'query_precision':'scope_verified','record_identity':'slots_with_actions','historical_coverage':'history_known_complete',
        'revision_alignment':'revision_aligned','financial_comparability':'financial_authorized','evidence_provenance':'provenance_slots',
        'reproducibility':'replay_consistent_slots','human_review_usability':'review_traceable'}
    dimensions=[]
    for name in DIMENSIONS:
        n,d,complete=measurement(cohorts,map_names[name]) if name in map_names else (None,None,False)
        state=full(n,d,complete)
        rule='all_observed_applicable_requirements_nonzero_denominator'
        rationale='Measured bounded evidence; missing observations remain unknown'
        if name=='query_precision':
            outside,_,_=measurement(cohorts,'scope_out')
            if outside: state=R.FAIL;rationale='Known returned native context conflicts with requested context; upstream cause unproven'
            elif state is R.FAIL: state=R.UNKNOWN
        if name=='record_identity' and state is R.FAIL: state=R.UNKNOWN
        if name=='record_identity': rationale='Selected slots with at least one complete verified native action; not independent cross-source corroboration'
        if name=='source_access_api_stability':
            if holdouts:
                fn,fd,fc=measurement(tuple(c for c in cohorts if c.role=='frozen_pilot'),'source_http_success')
                aux=[m for c in holdouts for m in c.auxiliary_measurements if m.name=='all_holdout_HTTP_success']
                n=(fn or 0)+sum(m.numerator or 0 for m in aux);d=(fd or 0)+sum(m.denominator or 0 for m in aux)
                state=full(n,d,fc and len(aux)==len(holdouts) and all(m.complete for m in aux))
            if state is R.PASS and not distinct: state=R.CONDITIONAL
            rationale='Observed HTTP success is not a general API stability guarantee; distinct holdout required for PASS'
        if name in ('historical_coverage','revision_alignment','financial_comparability') and (not n or not complete): state=R.UNKNOWN
        if name=='historical_coverage':
            fresh,fd,fc=measurement(cohorts,'freshness_supported')
            if state is R.PASS and full(fresh,fd,fc) is not R.PASS: state=R.UNKNOWN
            rule='positive_history_coverage_and_content_freshness_criteria_required'
        if name=='human_review_usability':
            state=R.CONDITIONAL if state is R.PASS else R.UNKNOWN
            rule='traceability_is_not_human_acceptance_or_review_throughput'
            rationale='Automated citation traceability measured; human usability benchmark not performed'
        if name=='security_bounded_collection':
            n=sum(g.result is R.PASS for g in hard);d=len(hard)
            state=R.FAIL if any(g.result is R.FAIL for g in hard) else R.PASS if n==d else R.UNKNOWN
            rule='all_non_negotiable_controls_must_pass'
        if name=='source_modernization':
            state=R.UNKNOWN;n=d=None;rule='authorized_SAM_schema_identity_paging_revision_financial_and_scale_validation_required'
            rationale='Documentation reviewed; no authenticated SAM observation or supported full migration available'
        if name=='reproducibility' and any(s.replay_first_sha256!=s.replay_second_sha256 for s in slots if s.processed): state=R.FAIL
        dimensions.append(GateResult(name=name,result=state,numerator=n,denominator=d,unit='frozen_verification_and_all_holdout_HTTP_requests' if name=='source_access_api_stability' else 'non_negotiable_controls' if name=='security_bounded_collection' else 'not_measured' if name=='source_modernization' else next((m.unit for c in cohorts for s in c.slots for m in s.measurements if m.name==map_names[name]),'unknown'),
            rule=rule,rationale=rationale,evidence_ids=refs,limitations=('bounded_convenience_cohorts_not_population_estimates','technical_success_is_not_evidentiary_reliability')))
    dimensions=tuple(dimensions)
    return dimensions,hard,mode_decisions(dimensions,hard,distinct_holdout=distinct)


FEASIBILITY={'query_imprecision':'medium','identifier_mismatch':'medium','parent_context_ambiguity':'medium',
    'missing_source_counterpart':'medium','partial_source_coverage':'high','unsupported_schema':'high',
    'revision_relationship_unknown':'low','incompatible_financial_basis':'medium','source_access_failure':'medium',
    'stale_or_unverified_update_status':'low','unverified_historical_completeness':'low','evidence_integrity_failure':'high'}
EVIDENCE_QUALITY={c:('observed_validation_or_native_context_failure' if c in ('query_imprecision','identifier_mismatch','unsupported_schema','source_access_failure','evidence_integrity_failure')
    else 'missing_authoritative_criteria' if c in ('revision_relationship_unknown','stale_or_unverified_update_status','unverified_historical_completeness') else 'observed_missing_prerequisite') for c in CAUSES}


def remediation(cohorts):
    rows=[]
    for code in CAUSES:
        slots={(c.role,s.slot) for c in cohorts for s in c.slots if any(code in a.codes for a in s.causes)}
        subjects={(c.role,s.slot,a.unit,a.subject_key) for c in cohorts for s in c.slots for a in s.causes if code in a.codes}
        subjects.update((c.role,None,a.unit,a.subject_key) for c in cohorts for a in c.auxiliary_causes if code in a.codes)
        by_unit={unit:sum(a[2]==unit for a in subjects) for unit in ('record_content','source_task','artifact','slot')}
        if not subjects: continue
        blocked_discovery=code=='source_access_failure' and any(a.subject_key=='frame-response.json' and code in a.codes for c in cohorts for a in c.auxiliary_causes)
        rows.append({'code':code,'affected_selected_slots':len(slots),'slot_denominator':sum(c.selected_count for c in cohorts),
            'blocks_new_cohort_discovery':blocked_discovery,
            'distinct_subject_counts_by_unit':by_unit,'estimated_feasibility':FEASIBILITY[code],
            'feasibility_basis':'engineering_assumption_not_measured_delivery_estimate','evidence_quality':EVIDENCE_QUALITY[code],
            'causality_limit':'observed_contributor_not_certified_upstream_root_cause',
            'evidence_ids':sorted({r for c in cohorts for s in c.slots for a in s.causes if code in a.codes for r in a.evidence_ids}|{r for c in cohorts for a in c.auxiliary_causes if code in a.codes for r in a.evidence_ids})})
    return sorted(rows,key=lambda r:(-int(r['blocks_new_cohort_discovery']),-r['affected_selected_slots'],-{'high':3,'medium':2,'low':1}[r['estimated_feasibility']],
        -{'observed_validation_or_native_context_failure':3,'observed_missing_prerequisite':2,'missing_authoritative_criteria':1}[r['evidence_quality']],r['code']))
