"""Schema contracts: no collection, matching, money comparison, or pipeline calls."""
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from src.evidence import (
    ActionIdentity, AwardIdentity, ComparisonResult, ComparisonStatus, Completeness,
    CoverageAssessment, Dimension, EvidenceArtifact, EvidenceRecordRef, ParseStatus,
    Representation, ReviewState, SourceIdentifier, Support, ValueKind,
    VerificationRun,
)
from tests.evidence_fixtures import artifacts, comparison, contracts, coverage, native, refs


@pytest.mark.parametrize("value", [0, 1, True, None, "", "  ", "a\n", "a\x00", "a\x7f"])
def test_invalid_native_identifiers_are_not_coerced(value):
    with pytest.raises(ValueError):
        native(value=value)


def test_original_identifiers_are_preserved_and_namespaced():
    value = " 00001.a-A/0 "
    identity = native(value=value)
    assert identity.value == value
    assert SourceIdentifier.from_json(identity.to_json()).value == value
    assert identity != native("fpds", value=value)
    assert identity.value != refs()[0].artifact_id
    with pytest.raises(FrozenInstanceError):
        identity.value = "different"


@pytest.mark.parametrize("contract", contracts(), ids=lambda x: type(x).__name__)
def test_all_nine_contracts_roundtrip_stably(contract):
    wire = contract.to_dict()
    assert wire["schema_version"] == 1
    assert type(contract).from_dict(wire) == contract
    assert type(contract).from_json(contract.to_json()).to_json() == contract.to_json()
    assert json.loads(contract.to_json()) == wire


@pytest.mark.parametrize("contract", contracts(), ids=lambda x: type(x).__name__)
@pytest.mark.parametrize("damage", ["missing_version", "future_version", "boolean_version", "unknown_field", "wrong_type"])
def test_strict_version_and_shape(contract, damage):
    wire = contract.to_dict()
    if damage == "missing_version":
        del wire["schema_version"]
    elif damage == "future_version":
        wire["schema_version"] = 2
    elif damage == "boolean_version":
        wire["schema_version"] = True
    elif damage == "unknown_field":
        wire["fraud_probability"] = 0.5
    else:
        wire["schema_type"] = "Other"
    with pytest.raises(ValueError):
        type(contract).from_dict(wire)


def test_duplicate_json_keys_and_nested_invalid_types_rejected():
    with pytest.raises(ValueError, match="duplicate JSON key"):
        SourceIdentifier.from_json('{"schema_version":1,"schema_version":1}')
    wire = contracts()[2].to_dict()
    wire["identifiers"][0]["value"] = 1
    with pytest.raises(ValueError):
        AwardIdentity.from_dict(wire)
    with pytest.raises(ValueError):
        replace(native(), schema_version=2)


@pytest.mark.parametrize("change", [
    {"source": ""}, {"sha256": "ABC"}, {"relative_path": "../raw.json"},
    {"relative_path": "/raw.json"}, {"relative_path": "C:/raw.json"},
    {"hash_basis": "original_bytes"}, {"endpoint": "http://example.invalid"},
    {"endpoint": "https://user:password@example.invalid"}, {"method": "PUT"},
    {"http_status": 0}, {"retrieved_at_utc": "2025-01-01"},
    {"retrieved_at_utc": "2025-01-01T00:00:00+01:00"},
    {"request_json": '{"page": 1}'}, {"request_json": "[]"},
    {"request_json": '{"page":NaN}'}, {"retrieved_at_utc": None},
])
def test_missing_or_contradictory_artifact_provenance(change):
    with pytest.raises(ValueError):
        replace(artifacts()[0], **change)


def test_historical_unknowns_remain_unknown_and_representation_is_honest():
    old = replace(artifacts()[0], retrieved_at_utc=None, endpoint=None, method=None,
                  limitations=("Historical parsed JSON has no collection timestamp or request metadata.",))
    assert EvidenceArtifact.from_json(old.to_json()).retrieved_at_utc is None
    assert old.representation is Representation.PARSED_JSON
    assert old.http_status is None
    with pytest.raises(ValueError, match="representation"):
        replace(artifacts()[1], hash_basis="original_bytes")
    raw = replace(artifacts()[0], representation=Representation.RESPONSE_BYTES, hash_basis="original_bytes")
    assert raw.representation is Representation.RESPONSE_BYTES


@pytest.mark.parametrize("change", [{"locator": ""}, {"artifact_id": "00001"},
                                    {"native_id": native("fpds")},
                                    {"record_url_constructed": True}])
def test_record_refs_need_provenance_and_do_not_confuse_native_ids(change):
    with pytest.raises(ValueError):
        replace(refs()[0], **change)


def test_identity_objects_need_identifiers_and_source_provenance():
    award, action = contracts()[2:4]
    for obj in (award, action):
        for change in ({"identifiers": ()}, {"evidence": ()}, {"identifiers": (native("other"),)}):
            with pytest.raises(ValueError):
                replace(obj, **change)
    with pytest.raises(ValueError):
        replace(award, identifiers=(native(value="0001"), native(value="0002")))
    with pytest.raises(ValueError):
        replace(action, modification=native("other"))


def test_pagination_history_and_source_wide_completeness_are_independent():
    unknown = CoverageAssessment(scope="synthetic")
    assert unknown.pagination is unknown.transaction_history is unknown.source_wide is Completeness.UNKNOWN
    paged = replace(coverage(), pagination=Completeness.COMPLETE, rationale=("All query pages observed.",))
    assert paged.transaction_history is Completeness.UNKNOWN
    assert paged.source_wide is Completeness.UNKNOWN
    for change in ({"evidence": ()}, {"rationale": ()}, {"limited": True}, {"retrieval_failed": True}):
        with pytest.raises(ValueError):
            replace(paged, **change)
    assert replace(coverage(), limited=True).pagination is Completeness.UNKNOWN


@pytest.mark.parametrize("status", [ComparisonStatus.VERIFIED_MATCH,
                                   ComparisonStatus.EXPLAINABLE_DIFFERENCE,
                                   ComparisonStatus.UNRESOLVED_DISCREPANCY])
def test_decisive_status_requires_supported_prerequisites_and_two_sources(status):
    base = replace(comparison(), status=status,
                   explanation_evidence=refs() if status is ComparisonStatus.EXPLAINABLE_DIFFERENCE else ())
    for name in ("identity_support", "comparability_support", "sufficiency_support"):
        for support in (Support.UNKNOWN, Support.UNSUPPORTED):
            with pytest.raises(ValueError):
                replace(base, **{name: support})
    with pytest.raises(ValueError):
        replace(base, evidence=(refs()[0],), explanation_evidence=())
    with pytest.raises(ValueError):
        replace(base, evidence=(refs()[0], replace(refs()[0], locator="/results/1")), explanation_evidence=())


def test_ambiguous_candidates_cannot_be_marked_verified():
    ambiguous = replace(comparison(), status=ComparisonStatus.AMBIGUOUS_MATCH,
                        identity_support=Support.UNKNOWN, candidates=refs())
    assert ComparisonResult.from_json(ambiguous.to_json()) == ambiguous
    for change in ({"candidates": ()}, {"candidates": (refs()[0], refs()[0])},
                   {"identity_support": Support.SUPPORTED},
                   {"status": ComparisonStatus.VERIFIED_MATCH}):
        with pytest.raises(ValueError):
            replace(ambiguous, **change)


def test_contradictory_statuses_and_uncited_explanations_rejected():
    with pytest.raises(ValueError):
        replace(comparison(), status=ComparisonStatus.INSUFFICIENT_EVIDENCE)
    with pytest.raises(ValueError):
        replace(comparison(), status=ComparisonStatus.EXPLAINABLE_DIFFERENCE)
    with pytest.raises(ValueError):
        replace(comparison(), explanation_evidence=(replace(refs()[0], locator="/unknown"),))
    with pytest.raises(ValueError):
        replace(comparison(), scope="other")


@pytest.mark.parametrize("history", [Completeness.UNKNOWN, Completeness.PARTIAL, Completeness.NOT_APPLICABLE])
def test_incomplete_history_blocks_history_dependent_outcomes(history):
    cov = replace(coverage(), transaction_history=history,
                  rationale=("Synthetic history limit.",))
    with pytest.raises(ValueError, match="complete transaction history"):
        replace(comparison(), requires_complete_history=True, coverage=cov)
    result = replace(comparison(), status=ComparisonStatus.INSUFFICIENT_EVIDENCE,
                     sufficiency_support=Support.UNKNOWN, requires_complete_history=True, coverage=cov)
    assert result.coverage.transaction_history is history


def test_complete_history_does_not_change_other_dimensions():
    result = replace(comparison(), requires_complete_history=True, coverage=coverage(True))
    assert result.coverage.pagination is Completeness.UNKNOWN
    assert result.coverage.source_wide is Completeness.UNKNOWN
    ids = {replace(result, dimension=dimension).claim_id for dimension in Dimension}
    assert len(ids) == 5


@pytest.mark.parametrize("change", [
    {"parsed": None}, {"parsed": "NaN"}, {"parsed": "Infinity"}, {"parsed": "bad"},
    {"original_json": "null"}, {"original_json": "NaN"}, {"currency": "usd"},
    {"parse_status": ParseStatus.MISSING}, {"parse_status": ParseStatus.INVALID},
    {"kind": ValueKind.DATE},
    {"parsed": "101.00"}, {"original_json": "true"},
])
def test_typed_value_invalid_or_unsupported_states(change):
    with pytest.raises(ValueError):
        replace(contracts()[4], **change)


def test_typed_value_missing_and_invalid_are_not_zero():
    base = contracts()[4]
    missing = replace(base, original_json="null", parsed=None, parse_status=ParseStatus.MISSING)
    invalid = replace(base, original_json='"bad"', parsed=None, parse_status=ParseStatus.INVALID)
    assert missing.parsed is invalid.parsed is None


def test_typed_dates_and_strings_keep_original_values():
    base = contracts()[4]
    for kind, value in ((ValueKind.DATE, "2025-01-01"), (ValueKind.STRING, "00001.A/0")):
        typed = replace(base, kind=kind, original_json=json.dumps(value), parsed=value, currency=None)
        assert type(typed).from_json(typed.to_json()) == typed
        with pytest.raises(ValueError):
            replace(typed, original_json='"different"')


def test_claim_ids_describe_questions_and_remain_stable_across_outcomes():
    base = comparison()
    unknown = replace(base, status=ComparisonStatus.INSUFFICIENT_EVIDENCE,
                      sufficiency_support=Support.UNKNOWN, evidence=(), rationale="Awaiting evidence.")
    assert base.claim_id == unknown.claim_id
    assert base.claim_id.startswith("claim:v1:")
    assert base.claim_id != replace(base, subject=native(value="00002")).claim_id
    assert base.claim_id != replace(base, claim_type="different_question").claim_id
    # Golden wire contract protects accidental changes to canonicalization and IDs.
    golden = json.loads((Path(__file__).parent / "fixtures" / "evidence_v1.json").read_text())
    assert base.claim_id == golden["claim_id"]
    assert [item.to_dict() for item in contracts()] == golden["contracts"]


def test_execution_timestamp_does_not_change_substantive_serialization():
    run = contracts()[-1]
    later = replace(run, executed_at_utc="2025-10-03T00:00:00Z")
    assert run.to_json() != later.to_json()
    assert run.to_json(substantive=True) == later.to_json(substantive=True)
    assert run.substantive_sha256 == later.substantive_sha256
    assert run.substantive_sha256 != replace(run, rule_version="v2").substantive_sha256
    assert "retrieved_at_utc" in run.to_json(substantive=True)


def test_review_workflow_does_not_rewrite_comparison_outcomes():
    event = contracts()[-2]
    for state in ReviewState:
        assert replace(event, state=state).claim_id == comparison().claim_id
    assert comparison().status is ComparisonStatus.VERIFIED_MATCH
    with pytest.raises(ValueError):
        replace(event, evidence=())
    with pytest.raises(ValueError):
        replace(event, reviewed_at_utc="unknown")


def test_run_manifest_references_and_claim_uniqueness():
    run = contracts()[-1]
    for change in ({"artifacts": ()}, {"artifacts": artifacts() + artifacts()},
                   {"results": run.results + run.results},
                   {"artifacts": (replace(artifacts()[0], source="other"), artifacts()[1])}):
        with pytest.raises(ValueError):
            replace(run, **change)


def test_new_schemas_do_not_change_legacy_reconciliation_contract():
    from unittest.mock import Mock
    from src.reconciliation import reconcile_awards
    client = Mock(page_delay_seconds=0)
    client.search_award.return_value = [{"piid": "00001", "contracting_agency_id": "8600",
                                        "action_date": "2025-01-01", "total_obligated_amount": "100.00"}]
    result = reconcile_awards([{"award_id": "00001", "awarding_sub_agency_code": "8600",
                                "award_amount": "105.00"}], client)[0]
    assert result["verification_status"] == "unverified"
    assert result["fpds_status"] == "matched_identifiers"
    assert result["amount_difference_usa_minus_fpds"] == "5.00"
    assert "claim_id" not in result
