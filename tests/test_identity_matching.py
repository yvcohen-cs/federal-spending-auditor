"""Deterministic C4 identity tests. No financial assertions or live APIs."""
from dataclasses import replace
from itertools import permutations

import pytest

from src.evidence import ComparisonStatus as S
from src.evidence_io import EvidenceError, canonical
from src.identity_matching import MatchLimits, component, decode_usa_id, match_records
from src.matching_models import IdentifierState, MatchRunSummary, Relation
from tests.matching_fixtures import evidence, fpds_row, record, usa_row


def match(*records, **kw):
    return match_records(records, input_manifest_sha256="0" * 64, **kw)


def status(report, claim="award_association"):
    return next(d.status for d in report.decisions if d.claim == claim)


def test_complete_exact_award_and_action_with_evidence():
    report = match(record(), record("fpds"))
    assert status(report) is status(report, "action_equivalence") is S.VERIFIED_MATCH
    assert report.exit_code == 0
    assert len(report.decisions) == 2
    assert all({e.reference.source for e in d.evidence} == {"usaspending", "fpds"} for d in report.decisions)
    assert report.counts["award_association"]["verified_match"] == 1
    assert all(d.claim_id.startswith("identity-claim:v1:") for d in report.decisions)


@pytest.mark.parametrize("change", [{"agency": "9999"}, {"parent": "OTHER"}, {"parent_agency": "9999"}])
def test_known_context_conflicts_never_match(change):
    report = match(record(), record("fpds", fpds_row(**change)))
    assert status(report) is S.UNRESOLVED_DISCREPANCY
    assert status(report, "action_equivalence") is S.INSUFFICIENT_EVIDENCE
    assert report.decisions[0].evidence


def test_different_piid_outside_claim_remains_in_inventory():
    report = match(record(), record("fpds", fpds_row(piid="OTHER")))
    assert status(report) is S.INSUFFICIENT_EVIDENCE
    assert len(report.records) == 2


@pytest.mark.parametrize("change", [{"parent": None}, {"parent_agency": None}, {"agency": None}])
def test_missing_fields_are_not_wildcards(change):
    report = match(record(), record("fpds", fpds_row(**change)))
    assert status(report) is S.INSUFFICIENT_EVIDENCE


def test_blank_parent_is_not_known_parent_or_asserted_absence():
    r = record(row=usa_row(parent="-NONE-", parent_agency="-NONE-"))
    for parents in ([], [{"PIID": "", "agencyID": ""}], [{"PIID": "SYNTH-PARENT", "agencyID": "0002"}]):
        report = match(r, record("fpds", {**fpds_row(), "parent_context": parents}))
        assert status(report) is S.INSUFFICIENT_EVIDENCE


def test_multiple_parent_candidates_ambiguous_all_retained():
    report = match(record(row=usa_row(parent="-NONE-", parent_agency="-NONE-")),
                   record("fpds"), record("fpds", fpds_row(parent="OTHER")))
    decision = next(d for d in report.decisions if d.claim == "award_association")
    assert decision.status is S.AMBIGUOUS_MATCH
    assert len(decision.award_candidates) == 2 and all(c.relation is Relation.POSSIBLE for c in decision.award_candidates)


def test_complete_match_cannot_hide_incomplete_plausible_candidate():
    report = match(record(), record("fpds"), record("fpds", fpds_row(parent=None)))
    assert status(report) is S.AMBIGUOUS_MATCH


@pytest.mark.parametrize("raw", [None, 42, True, "", " ", "bad\nID", "x" * 257])
def test_invalid_native_id_is_explicit(raw):
    report = match(record(row=usa_row(id=raw)), record("fpds"))
    assert status(report) is S.INSUFFICIENT_EVIDENCE
    assert report.records and next(r for r in report.records if r.source == "usaspending").issues


@pytest.mark.parametrize("raw", ["ASST_TX_OTHER", "CONT_TX_a_b_c", "CONT_TX_0001_0002_PI_ID_P00001_PARENT_0"])
def test_unsupported_and_ambiguous_encodings_not_guessed(raw):
    parts, issues = decode_usa_id(raw)
    assert issues and all(c.value is None for c in parts.values())


def test_opaque_case_punctuation_zeros_and_spaces_preserved():
    row = usa_row(piid=" a.000-1/Case ", parent="Parent.00", mod="p00001")
    target = fpds_row(piid=" a.000-1/Case ", parent="Parent.00", mod="p00001")
    report = match(record(row=row), record("fpds", target))
    assert status(report, "action_equivalence") is S.VERIFIED_MATCH
    subject = next(r for r in report.records if r.source == "usaspending")
    assert subject.piid.value == " a.000-1/Case "
    assert subject.agency.value == "0001"
    assert status(match(record(row=row), record("fpds", {**target, "PIID": " A.000-1/CASE "}))) is S.INSUFFICIENT_EVIDENCE


def test_multiple_modifications_one_award_not_ambiguous_award():
    report = match(record(), record("fpds"), record("fpds", fpds_row(mod="P00002")))
    assert status(report) is status(report, "action_equivalence") is S.VERIFIED_MATCH
    assert len(next(d for d in report.decisions if d.claim == "award_association").award_candidates) == 1
    assert len(report.records) == 3


def test_parent_modification_not_part_of_award_key():
    report = match(record(), record("fpds"), record("fpds", fpds_row(mod="P00002", parent_mod="P00003")))
    assert status(report) is status(report, "action_equivalence") is S.VERIFIED_MATCH


def test_same_modification_on_different_awards_never_equivalent():
    report = match(record(), record("fpds", fpds_row(parent="OTHER")), record("fpds"))
    assert status(report, "action_equivalence") is S.VERIFIED_MATCH
    action = next(d for d in report.decisions if d.claim == "action_equivalence")
    assert len(action.action_candidates) == 1
    assert len(report.records) == 3


@pytest.mark.parametrize("change", [{"mod": None}, {"transaction": None}])
def test_award_association_survives_unresolved_action(change):
    report = match(record(), record("fpds", fpds_row(**change)))
    assert status(report) is S.VERIFIED_MATCH
    assert status(report, "action_equivalence") is S.INSUFFICIENT_EVIDENCE


def test_missing_usa_modification_field_blocks_action():
    report = match(record(row=usa_row(modification_number=None)), record("fpds"))
    assert status(report) is S.VERIFIED_MATCH
    assert status(report, "action_equivalence") is S.INSUFFICIENT_EVIDENCE


def test_conflicting_native_modification_field_not_explained_away():
    report = match(record(row=usa_row(modification_number="OTHER")), record("fpds"))
    assert status(report) is S.VERIFIED_MATCH
    assert status(report, "action_equivalence") is S.UNRESOLVED_DISCREPANCY


def test_same_mod_different_transaction_records_distinct():
    report = match(record(row=usa_row(transaction="-NONE-")), record("fpds"), record("fpds", fpds_row(transaction="1")))
    assert status(report) is S.VERIFIED_MATCH
    assert status(report, "action_equivalence") is S.AMBIGUOUS_MATCH


def test_known_action_transaction_conflict():
    report = match(record(), record("fpds", fpds_row(transaction="1")))
    assert status(report) is S.VERIFIED_MATCH
    assert status(report, "action_equivalence") is S.UNRESOLVED_DISCREPANCY


def test_same_date_different_action_is_insufficient_not_equivalent():
    report = match(record(), record("fpds", fpds_row(mod="P00002", effectiveDate="2025-01-01")))
    assert status(report) is S.VERIFIED_MATCH
    assert status(report, "action_equivalence") is S.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("amount", [-100, 0, 999999, "unsupported"])
def test_amounts_do_not_enter_identity_comparisons(amount):
    report = match(record(row=usa_row(federal_action_obligation=amount)), record("fpds", fpds_row(obligatedAmount="700")))
    assert status(report, "action_equivalence") is S.VERIFIED_MATCH


def test_correction_versions_no_winner_selected():
    report = match(record(), record("fpds"), record("fpds", fpds_row(updated="2025-01-02")))
    assert status(report) is S.VERIFIED_MATCH
    assert status(report, "action_equivalence") is S.UNRESOLVED_DISCREPANCY
    assert len(report.records) == 3


def test_same_native_atom_id_different_action_conflicts():
    report = match(record(), record("fpds", fpds_row(atom_id="opaque")),
                   record("fpds", fpds_row(atom_id="opaque", mod="P00002")))
    assert status(report, "action_equivalence") is S.UNRESOLVED_DISCREPANCY


def test_repeated_observations_merged_with_all_references():
    report = match(record(), record("fpds"), record("fpds", index=2, timestamp="2025-01-02T00:00:00Z"))
    assert len(report.records) == 2
    assert len(next(r for r in report.records if r.source == "fpds").evidence) == 2
    assert status(report, "action_equivalence") is S.VERIFIED_MATCH


def test_duplicate_retrieval_rows_never_financial_actions():
    report = match(record(), record(), record("fpds"), record("fpds"))
    assert len(report.records) == 2 and len(report.decisions) == 2


def test_order_independent_serialization_and_execution_separation():
    rows = (record(), record("fpds"), record("fpds", fpds_row(mod="P00002")))
    outputs = {match(*p).to_json() for p in permutations(rows)}
    assert len(outputs) == 1
    report = match(*rows)
    assert MatchRunSummary.from_json(report.to_json()) == report
    timed = replace(report, executed_at_utc="2026-01-01T00:00:00Z")
    assert timed.substantive_sha256 == report.substantive_sha256
    assert [d.claim_id for d in timed.decisions] == [d.claim_id for d in report.decisions]


@pytest.mark.parametrize("limits,rows,code", [
    (MatchLimits(max_records=1), [record(), record("fpds")], "record"),
    (MatchLimits(max_comparisons=1), [record(), record("fpds")], "comparison"),
    (MatchLimits(max_candidates=1), [record(row=usa_row(parent="-NONE-")), record("fpds"), record("fpds", fpds_row(parent="OTHER"))], "candidate")])
def test_resource_limits_fail_without_truncation(limits, rows, code):
    with pytest.raises(EvidenceError, match=code + "_limit"):
        match(*rows, limits=limits)


def test_large_candidate_group_bounded():
    rows = [record("fpds", fpds_row(parent=f"P{i:04}")) for i in range(101)]
    with pytest.raises(EvidenceError, match="candidate_limit"):
        match(record(row=usa_row(parent="-NONE-")), *rows)


@pytest.mark.parametrize("change", [{"max_records": True}, {"max_candidates": 0}, {"max_comparisons": 100001}])
def test_invalid_limits(change):
    with pytest.raises(ValueError):
        MatchLimits(**change)


def test_integrity_collision_rejected():
    a = record()
    b = replace(a, piid=component("DIFFERENT"))
    with pytest.raises(EvidenceError, match="integrity_metadata"):
        match(a, b)


@pytest.mark.parametrize("version", [0, 2, True, 1.0])
def test_invalid_schema_versions(version):
    value = match(record(), record("fpds")).to_dict()
    value["schema_version"] = version
    with pytest.raises(ValueError):
        MatchRunSummary.from_dict(value)


def test_missing_and_conflicting_provenance_rejected():
    e = evidence("usaspending", usa_row())
    for changes in ({"observation_id": None}, {"metadata_paths": ()},
                    {"artifact": replace(e.artifact, retrieved_at_utc=None)},
                    {"reference": replace(e.reference, artifact_id="artifact:sha256:" + "f" * 64)}):
        with pytest.raises(ValueError):
            replace(e, **changes)


def test_contradictory_status_and_claim_schema_rejected():
    report = match(record(), record("fpds"))
    d = report.decisions[0]
    for changes in ({"status": S.AMBIGUOUS_MATCH}, {"status": S.EXPLAINABLE_DIFFERENCE},
                    {"evidence": ()}, {"rule_version": "v99"}, {"claim": "financial_verification"}):
        with pytest.raises(ValueError):
            replace(d, **changes)
    with pytest.raises(ValueError):
        replace(report, records=())


def test_no_records_or_only_one_source_not_complete_match():
    assert match().exit_code == 1
    assert status(match(record())) is S.INSUFFICIENT_EVIDENCE
    assert not match(record("fpds")).decisions


def test_observation_hash_must_match_provenance():
    e = evidence("usaspending", usa_row())
    with pytest.raises(ValueError, match="observation ID contradicts"):
        replace(e, observation_id="observation:v1:" + "0" * 64)


def test_serialized_upgrade_of_unresolved_action_is_rejected():
    report = match(record(), record("fpds", fpds_row(transaction=None)))
    wire = report.to_dict()
    for d in wire["decisions"]:
        if d["claim"] == "action_equivalence":
            d["status"] = "verified_match"
            d["action_candidates"][0]["relation"] = "exact"
    with pytest.raises(ValueError, match="contradict deterministic"):
        MatchRunSummary.from_dict(wire)


def test_conflicting_parent_container_cannot_be_ignored_beside_exact_candidate():
    contradictory = {**fpds_row(), "parent_context": [{"PIID": "SYNTH-PARENT", "agencyID": "0002"}, {"PIID": "OTHER", "agencyID": "0002"}]}
    report = match(record(), record("fpds"), record("fpds", contradictory))
    assert status(report) is S.UNRESOLVED_DISCREPANCY


def test_native_atom_id_with_different_award_contexts_blocks_award_match():
    report = match(record(), record("fpds", fpds_row(atom_id="same-native-id")),
                   record("fpds", fpds_row(atom_id="same-native-id", parent="OTHER")))
    assert status(report) is S.UNRESOLVED_DISCREPANCY
    award = next(d for d in report.decisions if d.claim == "award_association")
    assert len(award.evidence) == 3


def test_conflicting_usa_versions_cite_both_observations():
    report = match(record(), record(row=usa_row(action_type="RAW-CORRECTION-CODE")), record("fpds"))
    assert all(d.status is S.UNRESOLVED_DISCREPANCY for d in report.decisions if d.claim == "action_equivalence")
    assert all(len(d.evidence) == 3 for d in report.decisions if d.claim == "action_equivalence")


@pytest.mark.parametrize("agency", ["1", " 001", "00001", "é001", "00/1"])
def test_malformed_agency_code_is_explicit_and_not_padded(agency):
    subject = record(row=usa_row(agency=agency))
    assert subject.agency.state is IdentifierState.MALFORMED
    assert subject.agency.original_json == canonical(agency)
    assert status(match(subject, record("fpds"))) is S.INSUFFICIENT_EVIDENCE


def test_unsupported_native_format_has_explicit_state_and_original():
    subject = record(row=usa_row(id="FUTURE-TX_opaque"))
    assert subject.native_action_id.state is IdentifierState.UNSUPPORTED
    assert subject.native_action_id.original_json == canonical("FUTURE-TX_opaque")


def test_conflict_expansion_is_bounded_even_without_cross_source_pairs():
    rows = [record("fpds", fpds_row(updated=f"2025-01-{i:02d}")) for i in range(1, 20)]
    with pytest.raises(EvidenceError, match="comparison_limit"):
        match(*rows, limits=MatchLimits(max_comparisons=100))


@pytest.mark.parametrize("member,key", [("records", "record_id"), ("decisions", "claim_id")])
def test_computed_link_ids_serialized_and_verified(member, key):
    wire = match(record(), record("fpds")).to_dict()
    assert wire[member][0][key]
    wire[member][0][key] = "forged"
    with pytest.raises(ValueError):
        MatchRunSummary.from_dict(wire)


def test_candidate_id_declarations_cannot_be_changed():
    wire = match(record(), record("fpds")).to_dict()
    decision = next(d for d in wire["decisions"] if d["claim"] == "award_association")
    assert decision["award_candidates"][0]["candidate_id"].startswith("candidate:v1:")
    decision["award_candidates"][0]["candidate_id"] = "forged"
    with pytest.raises(ValueError):
        MatchRunSummary.from_dict(wire)
