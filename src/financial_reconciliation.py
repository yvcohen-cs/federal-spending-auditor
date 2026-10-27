"""Conservative C5 Decimal rules over verified C4 action associations."""
from __future__ import annotations

from .evidence import ComparisonStatus as Status
from .evidence_io import EvidenceError
from .financial_models import (AmountBasis, Compatibility, DateBasis, ExplanationCheck,
                               FinancialComparison, FinancialLimits, FinancialRun,
                               FinancialScope, FPDS_ACTION, Measure, USA_ACTION)
from .financial_values import NumericState, exact_difference, has_cent_precision
from .matching_models import Relation, ordered


def compatibility(left, right):
    """One supported pair, never label-based amount/obligation equivalence."""
    if not left or not right:
        return Compatibility.UNKNOWN, ("missing_observed_counterpart_or_monetary_field",)
    values = left + right
    if any(not o.semantics.documented for o in values):
        return Compatibility.UNKNOWN, ("unsupported_or_unknown_field_semantics",)
    if any(o.semantics.measure is not Measure.OBLIGATION or o.semantics.basis is not AmountBasis.INCREMENTAL
           or o.semantics.scope is not FinancialScope.ACTION for o in values):
        return Compatibility.INCOMPATIBLE, ("monetary_measure_basis_or_scope_mismatch",)
    if any((o.source, o.original_field) != ("usaspending", USA_ACTION) for o in left) or any((o.source, o.original_field) != ("fpds", FPDS_ACTION) for o in right):
        return Compatibility.UNKNOWN, ("unsupported_cross_source_field_pair",)
    if any(o.currency != "USD" for o in values):
        return Compatibility.UNKNOWN, ("missing_or_conflicting_currency_no_conversion",)
    if any(o.value.state is not NumericState.VALID for o in values):
        return Compatibility.UNKNOWN, ("missing_invalid_or_unsupported_amount",)
    if any(not has_cent_precision(o.value) for o in values):
        return Compatibility.UNKNOWN, ("nonzero_subcent_precision_no_documented_rounding_rule",)
    if any(o.date_basis is not DateBasis.SIGNED or o.action_date is None for o in values):
        return Compatibility.UNKNOWN, ("signed_action_date_basis_or_value_unknown",)
    if len({o.action_date for o in values}) != 1:
        return Compatibility.INCOMPATIBLE, ("different_signed_action_dates_or_fiscal_years",)
    if len({o.value.normalized for o in left}) != 1 or len({o.value.normalized for o in right}) != 1:
        return Compatibility.UNKNOWN, ("conflicting_values_across_retained_occurrences",)
    return Compatibility.COMPATIBLE, ("documented_same_action_incremental_usd_obligations",)


def _result(identity, left, right):
    field_compatibility, reasons = compatibility(left, right)
    status = Status.INSUFFICIENT_EVIDENCE
    a = b = difference = None
    if identity.status is Status.AMBIGUOUS_MATCH:
        status, reasons = Status.AMBIGUOUS_MATCH, ("multiple_plausible_action_identities",) + reasons
    elif identity.status is not Status.VERIFIED_MATCH:
        reasons = ("specific_action_identity_not_verified",) + reasons
    elif field_compatibility is Compatibility.COMPATIBLE:
        a, b = left[0].value.normalized, right[0].value.normalized
        difference = exact_difference(a, b)
        if difference == "0":
            status, reasons = Status.VERIFIED_MATCH, ("exact_observed_action_obligation_equality",)
        else:
            reasons = ("observed_value_difference_not_established_discrepancy",
                       "source_revision_alignment_and_refresh_unknown")
    evidence = ordered(identity.evidence + tuple(o.evidence for o in left + right))
    checks = ordered((
        ExplanationCheck(code="identity_context", assessment="checked" if identity.status is Status.VERIFIED_MATCH else "unknown"),
        ExplanationCheck(code="incremental_vs_cumulative", assessment="checked" if field_compatibility is Compatibility.COMPATIBLE else "possible"),
        ExplanationCheck(code="signed_vs_effective_or_publication", assessment="checked" if field_compatibility is Compatibility.COMPATIBLE else "possible"),
        ExplanationCheck(code="fiscal_year_scope", assessment="checked" if field_compatibility is Compatibility.COMPATIBLE else "possible"),
        ExplanationCheck(code="rounding_precision", assessment="checked" if field_compatibility is Compatibility.COMPATIBLE else "unknown"),
        ExplanationCheck(code="duplicate_retrievals", assessment="checked"),
        ExplanationCheck(code="missing_modifications_or_corrections", assessment="unknown"),
        ExplanationCheck(code="source_refresh_or_reporting_lag", assessment="unknown"),
    ))
    next_step = ("No numerical follow-up for this observed equality; check source coverage before any broader financial claim."
                 if status is Status.VERIFIED_MATCH else
                 "Verify the official action, signed date, field definition and current source revision/refresh; obtain missing evidence before classifying a discrepancy.")
    return FinancialComparison(identity_claim_id=identity.claim_id, subject_record_id=identity.subject_record_id,
                                status=status, compatibility=field_compatibility, reasons=reasons,
                                left_observation_ids=tuple(sorted(o.financial_observation_id for o in left)),
                                right_observation_ids=tuple(sorted(o.financial_observation_id for o in right)),
                                evidence=evidence, explanations=checks, next_step=next_step,
                                left_normalized=a, right_normalized=b, difference_usa_minus_fpds=difference)


def evaluate_finances(identity_run, observations, limits):
    if len(observations) > limits.max_observations:
        raise EvidenceError("financial_observation_limit")
    by_record = {}
    for observation in observations:
        by_record.setdefault((observation.record_id, observation.original_field), []).append(observation)
    work = 0
    results = []
    for identity in identity_run.decisions:
        if identity.claim != "action_equivalence":
            continue
        left = ordered(by_record.get((identity.subject_record_id, USA_ACTION), ()))
        candidates = [c for c in identity.action_candidates if c.relation is not Relation.CONFLICT]
        right = ordered(o for c in candidates for rid in c.record_ids for o in by_record.get((rid, FPDS_ACTION), ()))
        # Two evaluations (engine and schema readback) plus bounded check passes.
        work += 16 * (1 + len(left) + len(right))
        if work > limits.max_comparison_work:
            raise EvidenceError("financial_comparison_work_limit")
        results.append(_result(identity, left, right))
    return ordered(results)


def reconcile_observations(identity_run, observations, *, limits=None):
    limits = limits or FinancialLimits()
    if len(observations) > limits.max_observations:
        raise EvidenceError("financial_observation_limit")
    observations = ordered(observations)
    return FinancialRun(identity_run=identity_run, observations=observations,
                         results=evaluate_finances(identity_run, observations, limits), limits=limits)
