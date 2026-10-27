"""Conservative observed-value claims and incompatible financial semantics."""
from dataclasses import replace
from itertools import permutations

import pytest

from src.evidence import ComparisonStatus as S
from src.evidence_io import EvidenceError
from src.financial_models import (Compatibility as C, DateBasis, FieldSemantics,
                                  FinancialLimits, FinancialRun, FinancialScope)
from src.financial_reconciliation import compatibility, reconcile_observations
from src.financial_values import RawKind
from src.identity_matching import match_records
from tests.financial_fixtures import observation, pair
from tests.matching_fixtures import fpds_row, record, usa_row


def run(left="100.00", right="100.00", **kw):
    identity, observations = pair(left, right, **kw)
    return reconcile_observations(identity, observations)


@pytest.mark.parametrize("amount", ["100.00", "0", "-100.00", "-0.00", "9007199254740992.01"])
def test_equal_action_obligations(amount):
    report = run(amount, amount)
    result = report.results[0]
    assert result.status is S.VERIFIED_MATCH and result.difference_usa_minus_fpds == "0"
    assert result.tolerance == "0" and report.exit_code == 0
    assert {e.reference.source for e in result.evidence} == {"usaspending", "fpds"}


@pytest.mark.parametrize("left,right,difference", [("100.01", "100.00", "0.01"), ("-20", "20", "-40"), ("0", "-0.01", "0.01")])
def test_compatible_unequal_values_not_auto_discrepancy(left, right, difference):
    result = run(left, right).results[0]
    assert result.compatibility is C.COMPATIBLE and result.difference_usa_minus_fpds == difference
    assert result.status is S.INSUFFICIENT_EVIDENCE
    assert "source_revision_alignment_and_refresh_unknown" in result.reasons
    assert any(c.code == "source_refresh_or_reporting_lag" and c.assessment == "unknown" for c in result.explanations)


@pytest.mark.parametrize("field", ["totalDollarValues/obligatedAmount", "totalDollarValues/totalBaseAndAllOptionsValue", "totalDollarValues/totalBaseAndExercisedOptionsValue"])
def test_cumulative_or_contract_value_not_action_obligation(field):
    _, values = pair(right_kw={"field": field})
    result, reasons = compatibility(values[:1], values[1:])
    assert result is C.INCOMPATIBLE and reasons


@pytest.mark.parametrize("field", ["fy_federal_action_obligation", "award_amount", "total_outlays", "lifetime_obligations", "face_value_loan_guarantee"])
def test_unsupported_measures_fiscal_and_lifetime_totals_unknown(field):
    _, values = pair(left_kw={"field": field})
    assert compatibility(values[:1], values[1:])[0] is C.UNKNOWN


@pytest.mark.parametrize("currency", ["EUR", "", "usd", "JPY"])
def test_currency_missing_or_conflicting_never_converted(currency):
    report = run(right_kw={"currency": currency})
    assert report.results[0].status is S.INSUFFICIENT_EVIDENCE
    assert report.results[0].difference_usa_minus_fpds is None


def test_field_unit_distinct_from_explicit_currency_metadata():
    _, values = pair()
    assert all(o.currency == "USD" and o.declared_currency_raw is None for o in values)
    assert values[0].semantics.documented


@pytest.mark.parametrize("date", [None, "not-a-date", "2024-09-30", "2025-10-01", "2025-01-01T00:00:00Z"])
def test_missing_or_different_signed_dates_withhold_number(date):
    result = run(right_kw={"date": date}).results[0]
    assert result.status is S.INSUFFICIENT_EVIDENCE and result.difference_usa_minus_fpds is None


def test_midnight_representation_and_fiscal_boundary_not_lifetime_total():
    _, values = pair(left_kw={"date": "2024-10-01"}, right_kw={"date": "2024-10-01 00:00:00"})
    assert values[0].action_fiscal_year == values[1].action_fiscal_year == 2025
    assert values[0].semantics.scope is FinancialScope.ACTION
    assert compatibility(values[:1], values[1:])[0] is C.COMPATIBLE


@pytest.mark.parametrize("date_basis", [DateBasis.EFFECTIVE, DateBasis.PUBLICATION, DateBasis.RETRIEVAL, DateBasis.UNKNOWN])
def test_other_date_basis_never_becomes_action_date(date_basis):
    identity, values = pair()
    other = replace(values[1], date_basis=date_basis, action_date=None)
    assert reconcile_observations(identity, (values[0], other)).results[0].difference_usa_minus_fpds is None


def test_precision_normalization_not_financial_difference():
    result = run("1.2300", "001.23").results[0]
    assert result.status is S.VERIFIED_MATCH and result.left_normalized == result.right_normalized == "1.23"


@pytest.mark.parametrize("amount", ["1.001", "-0.001"])
def test_subcent_not_rounded_into_equality(amount):
    result = run(amount, "1.00").results[0]
    assert result.status is S.INSUFFICIENT_EVIDENCE and result.difference_usa_minus_fpds is None


def test_missing_value_not_zero():
    result = run(left=None, left_kw={"kind": RawKind.MISSING}, right="0").results[0]
    assert result.status is S.INSUFFICIENT_EVIDENCE and result.difference_usa_minus_fpds is None


def test_award_match_alone_insufficient_for_financial_claim():
    a, b = record(), record("fpds", fpds_row(transaction=None))
    identity = match_records((a, b), input_manifest_sha256="0" * 64)
    report = reconcile_observations(identity, (observation(a), observation(b)))
    assert report.results[0].status is S.INSUFFICIENT_EVIDENCE
    assert report.results[0].difference_usa_minus_fpds is None


def test_multiple_action_candidates_ambiguous_no_arithmetic():
    a, b, c = record(row=usa_row(transaction="-NONE-")), record("fpds"), record("fpds", fpds_row(transaction="1"))
    identity = match_records((a, b, c), input_manifest_sha256="0" * 64)
    report = reconcile_observations(identity, tuple(observation(r) for r in (a, b, c)))
    result = report.results[0]
    assert result.status is S.AMBIGUOUS_MATCH and len(result.right_observation_ids) == 2
    assert result.difference_usa_minus_fpds is None


def test_changed_revision_blocks_arithmetic():
    a, b, c = record(), record("fpds"), record("fpds", fpds_row(updated="later"))
    identity = match_records((a, b, c), input_manifest_sha256="0" * 64)
    report = reconcile_observations(identity, tuple(observation(r) for r in (a, b, c)))
    assert report.results[0].status is S.INSUFFICIENT_EVIDENCE and report.results[0].difference_usa_minus_fpds is None


def test_serialization_order_claim_ids_execution_time():
    identity, values = pair()
    outputs = {reconcile_observations(identity, p).to_json() for p in permutations(values)}
    assert len(outputs) == 1
    report = reconcile_observations(identity, values)
    assert FinancialRun.from_json(report.to_json()) == report
    timed = replace(report, executed_at_utc="2026-10-27T00:00:00Z")
    assert timed.substantive_sha256 == report.substantive_sha256
    assert timed.results[0].claim_id == report.results[0].claim_id


@pytest.mark.parametrize("version", [0, 2, True, 1.0])
def test_schema_version_rejection(version):
    doc = run().to_dict()
    doc["schema_version"] = version
    with pytest.raises(ValueError):
        FinancialRun.from_dict(doc)


def test_tolerance_status_and_numeric_forgery_rejected():
    report = run()
    for changes in ({"tolerance": "0.01"}, {"difference_usa_minus_fpds": "1"},
                    {"status": S.UNRESOLVED_DISCREPANCY}, {"status": S.EXPLAINABLE_DIFFERENCE}):
        with pytest.raises(ValueError):
            replace(report.results[0], **changes)
    wire = run("1", "2").to_dict()
    wire["results"][0]["status"] = "verified_match"
    with pytest.raises(ValueError):
        FinancialRun.from_dict(wire)


def test_semantics_cannot_be_relabelled_or_currency_converted():
    _, values = pair()
    with pytest.raises(ValueError):
        replace(values[0], semantics=FieldSemantics())
    with pytest.raises(ValueError):
        FieldSemantics(currency="EUR")


def test_resource_bounds_before_duplicate_consolidation():
    identity, values = pair()
    with pytest.raises(EvidenceError, match="observation_limit"):
        reconcile_observations(identity, values * 2, limits=FinancialLimits(max_observations=3))
    with pytest.raises(EvidenceError, match="comparison_work_limit"):
        reconcile_observations(identity, values, limits=FinancialLimits(max_comparison_work=1))


def test_unknown_history_never_summed_or_promoted():
    report = run()
    assert "no_history_totals_or_currency_conversions" in report.limitations
    assert "history_total" not in report.to_dict()
    assert any(c.code == "missing_modifications_or_corrections" and c.assessment == "unknown" for c in report.results[0].explanations)


def test_required_limitations_and_interpretations_not_overridable():
    report = run()
    with pytest.raises(ValueError):
        replace(report, limitations=())
    wire = report.to_dict()
    wire["observations"][0]["effective_currency"] = "EUR"
    with pytest.raises(ValueError):
        FinancialRun.from_dict(wire)


@pytest.mark.parametrize("values", [{"max_observations": True}, {"max_observations": 0}, {"max_comparison_work": 100001}])
def test_invalid_financial_limits(values):
    with pytest.raises(ValueError):
        FinancialLimits(**values)


def test_standalone_comparison_rejects_broken_identity_and_evidence_links():
    report = run()
    result = report.results[0]
    for change in ({"identity_claim_id": "invented"}, {"subject_record_id": "invented"},
                   {"left_observation_ids": ()}, {"right_observation_ids": ("invented",)},
                   {"evidence": (result.evidence[0],)}):
        with pytest.raises(ValueError):
            replace(result, **change)


def test_historical_fiscal_calendar_not_guessed():
    _, values = pair(left_kw={"date": "1976-09-30"})
    assert values[0].action_fiscal_year is None
