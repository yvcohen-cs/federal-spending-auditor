"""End-to-end offline C3/C4 boundaries and immutable evidence regression tests."""
from unittest.mock import Mock

import pytest

from src.collection import SelectedAward, collect_selected
from src.collection_sources import FixtureTransport
from src.evidence import ComparisonStatus as S, Completeness
from src.evidence_io import EvidenceError, canonical, digest, strict_json
from src.match_evidence import main
from src.matching_ingestion import match_collection
from tests.matching_fixtures import fpds_row, scenario, usa_row
from tests.test_collection_c3 import limits


SELECTED = SelectedAward(generated_id="CONT_AWD_SYNTH-00001_0001_SYNTH-PARENT_0002", piid="SYNTH-00001", agency_id="0001",
                         parent_piid="SYNTH-PARENT", parent_agency_id="0002")


def collection(tmp_path, data=None, **kw):
    path = tmp_path / "collection"
    data = data or scenario()
    collect_selected(path, [SELECTED], limits=kw.pop("limits", limits()), profile="fixture:" + digest(data),
                     transport=FixtureTransport(data), sleep=lambda _: None, **kw)
    return path


def snapshot(path):
    return {p.name: p.read_bytes() for p in path.iterdir()}


def test_c3_workflow_exact_match_readonly_no_network(tmp_path, monkeypatch):
    import requests
    path = collection(tmp_path)
    before = snapshot(path)
    monkeypatch.setattr(requests.Session, "request", Mock(side_effect=AssertionError("network prohibited")))
    report = match_collection(path)
    assert all(d.status is S.VERIFIED_MATCH for d in report.decisions)
    assert snapshot(path) == before
    assert report.to_json() == match_collection(path).to_json()
    assert all(e.observation_id and e.reference.locator for d in report.decisions for e in d.evidence)
    assert all("synthetic_fixture_only" in e.artifact.limitations for d in report.decisions for e in d.evidence)


def test_duplicate_rows_preserve_all_locators(tmp_path):
    path = collection(tmp_path, scenario([usa_row(), usa_row()], [fpds_row(), fpds_row()]))
    report = match_collection(path)
    assert len(report.records) == 2
    assert all(len(r.evidence) == 2 for r in report.records)
    assert all(d.status is S.VERIFIED_MATCH for d in report.decisions)


def test_incomplete_pagination_and_unknown_histories_retained(tmp_path):
    path = collection(tmp_path, scenario(more=True), limits=limits(max_pages=1))
    report = match_collection(path)
    assert any(c.pagination is Completeness.PARTIAL for c in report.coverage)
    assert all(c.transaction_history is c.source_wide is c.freshness is c.query_scope is Completeness.UNKNOWN for c in report.coverage)
    assert all(c.pagination is not Completeness.COMPLETE for c in report.coverage)
    assert all(d.status is S.VERIFIED_MATCH for d in report.decisions)


@pytest.mark.parametrize("status", [403, 503, None])
def test_failed_responses_excluded_explicitly(tmp_path, status):
    data = scenario()
    data["responses"][1].update(status=status, body_complete=False, error_code="timeout" if status is None else None)
    path = collection(tmp_path, data)
    report = match_collection(path)
    assert len(report.records) == 1 and report.excluded_artifacts
    assert all(d.status is S.INSUFFICIENT_EVIDENCE for d in report.decisions)
    assert report.exit_code == 1


def test_empty_feed_inconclusive_not_absence(tmp_path):
    report = match_collection(collection(tmp_path, scenario(fpds_rows=[])))
    assert report.excluded_artifacts
    assert all(d.status is S.INSUFFICIENT_EVIDENCE for d in report.decisions)


@pytest.mark.parametrize("name", ["c3_attempt_000000.body", "c3_attempt_000000.json", "c3_checkpoint.json", "c3_plan.json"])
def test_changed_integrity_metadata_or_bytes_rejected(tmp_path, name):
    path = collection(tmp_path)
    (path / name).write_bytes(b"{}")
    before = snapshot(path)
    with pytest.raises(EvidenceError, match="invalid_matching_evidence"):
        match_collection(path)
    assert snapshot(path) == before


def test_extra_nonvalidated_artifact_rejected(tmp_path):
    path = collection(tmp_path)
    (path / "untrusted.json").write_text("{}")
    with pytest.raises(EvidenceError):
        match_collection(path)


def test_missing_native_identifiers_not_replaced_from_selection(tmp_path):
    row = usa_row(id="UNKNOWN-SYNTHETIC-ID")
    report = match_collection(collection(tmp_path, scenario([row])))
    assert all(d.status is S.INSUFFICIENT_EVIDENCE for d in report.decisions)
    subject = next(r for r in report.records if r.source == "usaspending")
    assert subject.piid.value is None


def test_source_identifiers_override_unverified_user_selection(tmp_path):
    # Matching never substitutes selection strings for actual native components.
    report = match_collection(collection(tmp_path, scenario([usa_row(agency="9999")])))
    award = next(d for d in report.decisions if d.claim == "award_association")
    assert award.status is S.UNRESOLVED_DISCREPANCY


def test_mutation_between_validation_and_use_is_rejected(tmp_path, monkeypatch):
    import src.matching_ingestion as module
    path = collection(tmp_path)
    original = module.inspect_directory
    def mutate(*args, **kw):
        report = original(*args, **kw)
        (path / "c3_attempt_000000.body").write_text("changed")
        return report
    monkeypatch.setattr(module, "inspect_directory", mutate)
    with pytest.raises(EvidenceError, match="matching_evidence_changed"):
        match_collection(path)


def test_final_mutation_check_includes_metadata(tmp_path, monkeypatch):
    import src.matching_ingestion as module
    path = collection(tmp_path)
    original = module.match_records
    def mutate(*args, **kw):
        report = original(*args, **kw)
        (path / "c3_plan.json").write_text("changed")
        return report
    monkeypatch.setattr(module, "match_records", mutate)
    with pytest.raises(EvidenceError, match="matching_evidence_changed"):
        match_collection(path)


def test_cli_machine_report_human_summary_and_safe_output(tmp_path, capsys):
    path = collection(tmp_path)
    before = snapshot(path)
    assert main(["--root", str(path)]) == 0
    out = capsys.readouterr()
    report = strict_json(out.out.encode())
    assert report["counts"]["action_equivalence"]["verified_match"] == 1
    assert "no financial verification" in out.err
    output = tmp_path / "matching.json"
    assert main(["--root", str(path), "--output", str(output)]) == 0
    assert strict_json(output.read_bytes()) == report
    assert main(["--root", str(path), "--output", str(output)]) == 2
    assert main(["--root", str(path), "--output", str(path / "forbidden.json")]) == 2
    assert snapshot(path) == before


def test_cli_bounds_and_interruption(tmp_path, monkeypatch, capsys):
    import src.match_evidence as module
    path = collection(tmp_path)
    assert main(["--root", str(path), "--max-comparisons", "1"]) == 2
    assert "matching_comparison_limit" in capsys.readouterr().out
    assert main(["--root", str(path), "--max-records", "0"]) == 2
    monkeypatch.setattr(module, "match_collection", Mock(side_effect=KeyboardInterrupt))
    assert main(["--root", str(path)]) == 130


def test_v1_c3_collection_remains_readable(tmp_path):
    path = collection(tmp_path)
    plan = strict_json((path / "c3_plan.json").read_bytes())
    plan["collector_version"] = 1
    (path / "c3_plan.json").write_text(canonical(plan))
    cp = strict_json((path / "c3_checkpoint.json").read_bytes())
    cp["fingerprint"] = digest(plan)
    for event in cp["events"]:
        p = path / f"c3_attempt_{event['sequence']:06d}.json"
        meta = strict_json(p.read_bytes())
        meta["fingerprint"] = digest(plan)
        p.write_text(canonical(meta))
        event["metadata_sha256"] = digest(meta)
    (path / "c3_checkpoint.json").write_text(canonical(cp))
    assert all(d.status is S.VERIFIED_MATCH for d in match_collection(path).decisions)


def test_symlink_evidence_root_rejected(tmp_path):
    path = collection(tmp_path)
    link = tmp_path / "linked"
    link.symlink_to(path, target_is_directory=True)
    with pytest.raises(EvidenceError):
        match_collection(link)


@pytest.mark.parametrize("container", ["content", "award", "awardID", "awardContractID", "atom_id"])
def test_compound_fpds_identity_context_not_silently_selected(tmp_path, container):
    data = scenario()
    text = data["responses"][1]["text"]
    if container == "atom_id":
        text = text.replace("<entry>", "<entry><id>one</id><id>two</id>")
    else:
        tag = "content" if container == "content" else "f:" + container
        text = text.replace(f"</{tag}>", f"</{tag}><{tag}/>")
    data["responses"][1]["text"] = text
    path = collection(tmp_path, data)
    before = snapshot(path)
    with pytest.raises(EvidenceError, match="unsupported_matching_fpds_context"):
        match_collection(path)
    assert snapshot(path) == before


def test_cli_execution_timestamp_does_not_change_substantive_hash(tmp_path, capsys):
    path = collection(tmp_path)
    assert main(["--root", str(path)]) == 0
    normal = strict_json(capsys.readouterr().out.encode())
    assert main(["--root", str(path), "--execution-time"]) == 0
    timed = strict_json(capsys.readouterr().out.encode())
    assert timed["report"]["executed_at_utc"] is not None
    assert timed["substantive_sha256"] == normal["substantive_sha256"]


def test_authored_static_fixture_commands(tmp_path, capsys):
    from src.collect_evidence import main as collect_main
    path = tmp_path / "static"
    assert collect_main(["--selection", "tests/fixtures/c4_selection.json", "--fixture", "tests/fixtures/c4_scenario.json",
                         "--run-dir", str(path), "--retries", "0"]) == 1
    capsys.readouterr()
    assert main(["--root", str(path)]) == 0
    wire = strict_json(capsys.readouterr().out.encode())
    assert len(wire["report"]["records"]) == 2
    assert wire["counts"]["award_association"]["verified_match"] == 1


def test_global_xml_prefix_registration_does_not_change_matching_report(tmp_path, monkeypatch):
    import xml.etree.ElementTree as ET
    path = collection(tmp_path)
    before = match_collection(path).to_json()
    monkeypatch.setattr(ET, "_namespace_map", dict(ET._namespace_map))
    ET.register_namespace("alternative", "https://www.fpds.gov/FPDS")
    ET.register_namespace("feedprefix", "http://www.w3.org/2005/Atom")
    assert match_collection(path).to_json() == before
