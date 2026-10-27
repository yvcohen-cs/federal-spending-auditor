"""Synthetic offline C6 projection, provenance and compatibility contracts."""
from dataclasses import replace
from itertools import permutations
from unittest.mock import Mock

import pytest

from src.evidence import ComparisonStatus as S
from src.evidence_io import EvidenceError, canonical, strict_json
from src.financial_ingestion import reconcile_collection
from src.match_evidence import main as identity_cli
from src.reconcile_evidence import main as finance_cli
from src.review_packet_builder import build_packets
from src.review_packet_models import (AlternativeExplanation, ExplanationState,
                                     ReviewPacketManifest)
from tests.financial_fixtures import financial_scenario
from tests.test_matching_ingestion import collection, snapshot


def test_exact_claims_source_evidence_and_no_network(tmp_path, monkeypatch):
    import requests
    root = collection(tmp_path, financial_scenario())
    before = snapshot(root)
    monkeypatch.setattr(requests.Session, "request", Mock(side_effect=AssertionError("network forbidden")))
    m = build_packets(root)
    assert len(m.packets) == m.total_available_claims == 3
    assert all(p.claim.status is S.VERIFIED_MATCH for p in m.packets)
    assert m.exit_code == 0
    assert ReviewPacketManifest.from_json(m.to_json()) == m
    assert snapshot(root) == before
    for p in m.packets:
        assert p.citations and p.sources and p.limitations and p.recommended_actions
        assert {c.evidence.reference.source for c in p.citations} == {"usaspending", "fpds"}
        assert all(c.evidence.observation_id != c.evidence.artifact.artifact_id for c in p.citations)


@pytest.mark.parametrize("data", [financial_scenario("100.01", "100.00"), financial_scenario(signed=None), financial_scenario("0", "0"), financial_scenario("-20", "-20")])
def test_c5_status_never_upgraded_or_financial_values_changed(tmp_path, data):
    root = collection(tmp_path, data)
    m = build_packets(root)
    result = m.financial_run.results[0]
    packet = next(p for p in m.packets if p.claim.financial_result)
    assert packet.claim.financial_result == result
    assert packet.claim.status is result.status
    assert packet.comparison.difference_usa_minus_fpds == result.difference_usa_minus_fpds
    if result.difference_usa_minus_fpds != "0":
        assert packet.claim.status is S.INSUFFICIENT_EVIDENCE


def test_ambiguity_missing_context_and_incomplete_history(tmp_path):
    data = financial_scenario()
    data["responses"][0]["text"] = data["responses"][0]["text"].replace("_P00001_SYNTH-PARENT_0", "_P00001_SYNTH-PARENT_-NONE-")
    xml = data["responses"][1]["text"]
    entry = xml[xml.index("<entry>"):xml.index("</entry>")+8]
    data["responses"][1]["text"] = xml.replace("</feed>", entry.replace("<f:transactionNumber>0", "<f:transactionNumber>1") + "</feed>")
    m = build_packets(collection(tmp_path, data))
    assert any(p.claim.status is S.AMBIGUOUS_MATCH for p in m.packets)
    assert any("history=unknown" in l.detail for p in m.packets for l in p.limitations)
    assert all(a.state is not ExplanationState.SUPPORTED for p in m.packets for a in p.alternatives)


def test_missing_urls_and_empty_feed_are_unknown_not_absence(tmp_path):
    data = financial_scenario()
    data["responses"][1]["text"] = '<feed xmlns="http://www.w3.org/2005/Atom"/>'
    m = build_packets(collection(tmp_path, data))
    assert all(p.claim.status is S.INSUFFICIENT_EVIDENCE for p in m.packets)
    assert any(l.code.startswith("excluded_response:") for p in m.packets for l in p.limitations)
    assert all(c.evidence.reference.source_record_url is None for p in m.packets for c in p.citations)


def test_prior_c4_c5_reports_revalidated(tmp_path, capsys):
    root = collection(tmp_path, financial_scenario())
    identity, financial = tmp_path / "identity.json", tmp_path / "financial.json"
    assert identity_cli(["--root", str(root), "--output", str(identity)]) == 0
    assert finance_cli(["--root", str(root), "--output", str(financial)]) == 0
    a = build_packets(root, identity_report=identity, financial_report=financial)
    assert a == build_packets(root)
    doc = strict_json(financial.read_bytes())
    doc["exit_code"] = False
    financial.write_text(canonical(doc))
    with pytest.raises(EvidenceError, match="wrapper"):
        build_packets(root, financial_report=financial)


def test_stale_but_self_consistent_c5_report_rejected(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    first = collection(a, financial_scenario())
    second = collection(b, financial_scenario("100.01", "100.00"))
    saved = tmp_path / "prior.json"
    saved.write_text(reconcile_collection(first).to_json())
    with pytest.raises(EvidenceError, match="stale_or_conflicting_financial_report"):
        build_packets(second, financial_report=saved)


@pytest.mark.parametrize("name", ["c3_attempt_000000.body", "c3_attempt_000001.json", "c3_checkpoint.json"])
def test_tampered_evidence_never_projects(tmp_path, name):
    root = collection(tmp_path, financial_scenario())
    (root/name).write_bytes(b"{}")
    before = snapshot(root)
    with pytest.raises(EvidenceError):
        build_packets(root)
    assert snapshot(root) == before


def test_selection_order_stable_packet_ids_and_execution_separation(tmp_path):
    root = collection(tmp_path, financial_scenario())
    m = build_packets(root)
    ids = m.selected_claim_ids
    assert len({build_packets(root, claim_ids=p).to_json() for p in permutations(ids)}) == 1
    timed = replace(m, generated_at_utc="2026-10-27T00:00:00Z")
    assert timed.substantive_sha256 == m.substantive_sha256
    assert [p.packet_id for p in timed.packets] == [p.packet_id for p in m.packets]
    selected = build_packets(root, claim_ids=[ids[0]], max_claims=1)
    assert selected.packets[0].packet_id == next(p.packet_id for p in m.packets if p.claim.claim_id == ids[0])


def test_claim_bounds_never_silently_truncate(tmp_path):
    root = collection(tmp_path, financial_scenario())
    with pytest.raises(EvidenceError, match="claim_limit"):
        build_packets(root, max_claims=1)
    m = build_packets(root)
    with pytest.raises(EvidenceError, match="duplicate"):
        build_packets(root, claim_ids=[m.selected_claim_ids[0]]*2)
    with pytest.raises(EvidenceError, match="unknown_selected"):
        build_packets(root, claim_ids=["unknown"])


@pytest.mark.parametrize("version", [0, 2, True, 1.0])
def test_schema_version_rejection(tmp_path, version):
    doc = build_packets(collection(tmp_path, financial_scenario())).to_dict()
    doc["schema_version"] = version
    with pytest.raises(ValueError):
        ReviewPacketManifest.from_dict(doc)


def test_unsupported_explanations_and_claim_forgery_rejected(tmp_path):
    m = build_packets(collection(tmp_path, financial_scenario("1", "2")))
    for state in (ExplanationState.SUPPORTED, ExplanationState.RULED_OUT):
        with pytest.raises(ValueError):
            AlternativeExplanation(code="reporting_publication_delay", state=state, rationale="Plausible only")
    doc = m.to_dict()
    doc["packets"][0]["comparison"]["agreement"] = "All finances verified."
    with pytest.raises(ValueError, match="exact conservative"):
        ReviewPacketManifest.from_dict(doc)
    with pytest.raises(ValueError):
        replace(m.packets[0].citations[0], kind="reviewer_comment")


def test_retrieval_duplicates_preserve_locators_without_new_claims(tmp_path):
    data = financial_scenario()
    text = data["responses"][0]["text"]
    row = text[text.index('"results":[')+len('"results":['):-2]
    data["responses"][0]["text"] = text[:-2] + "," + row + "]}"
    m = build_packets(collection(tmp_path, data))
    assert len(m.packets) == 3
    for p in m.packets:
        assert len({c.evidence.reference.locator for c in p.citations if c.evidence.reference.source == "usaspending"}) == 2


def test_no_response_timestamp_is_not_fabricated(tmp_path):
    data = financial_scenario()
    data["responses"][1].update(status=None,body_complete=False,error_code="connection_error")
    m = build_packets(collection(tmp_path,data))
    assert all(p.claim.status is S.INSUFFICIENT_EVIDENCE for p in m.packets)
    assert any(l.detail == "no_response_body" for p in m.packets for l in p.limitations)
    assert all(c.evidence.artifact.source == "usaspending" for p in m.packets for c in p.citations)
