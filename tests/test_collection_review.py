"""Targeted PR #6 review regressions; authored synthetic evidence only."""
from dataclasses import replace
from unittest.mock import Mock

import pytest
import requests

from src.collect_evidence import main
from src.collection import collect_selected, make_plan
from src.collection_sources import FixtureTransport, HTTPTransport, fpds_query, parse_page, request_for, safe_next
from src.collection_store import CollectionStore
from src.evidence_ingestion import inspect_directory
from src.evidence_io import EvidenceError, canonical, digest, strict_json
from tests.test_collection_c3 import AWARD, fpds, limits, run, scenario, tx, usa, xml


def snapshot(path):
    return {p.name: p.read_bytes() for p in path.iterdir()}


def test_empty_fpds_feed_is_inconclusive_everywhere(tmp_path, capsys):
    empty = '<feed xmlns="http://www.w3.org/2005/Atom"/>'
    path = tmp_path / "run"
    result = run(path, scenario(fpds(empty)), sources=("fpds",))
    task = result["tasks"][0]
    assert task["status"] == "inconclusive_empty_feed"
    assert task["pagination"] == "complete" and task["query_scope"] == "unknown"
    assert task["history"] == task["freshness"] == "unknown"
    manifest = inspect_directory(path)
    observed = [e for e in manifest.entries if e.observation]
    assert len(observed) == 1 and observed[0].status.value == "incomplete"
    assert "inconclusive_empty_feed" in observed[0].observation.artifact.limitations
    selected = tmp_path / "selection.json"
    selected.write_text(canonical({"awards": [{"piid": "00001", "agency_id": "8600"}]}))
    fixture = tmp_path / "fixture.json"
    fixture.write_text(canonical(scenario(fpds(empty))))
    assert main(["--selection", str(selected), "--fixture", str(fixture), "--run-dir", str(tmp_path / "cli"), "--sources", "fpds"]) == 1
    assert strict_json(capsys.readouterr().out.encode())["tasks"][0]["status"] == "inconclusive_empty_feed"


def test_nonempty_candidates_do_not_prove_fpds_query_coverage(tmp_path):
    result = run(tmp_path / "run", scenario(fpds()), sources=("fpds",))
    assert result["tasks"][0]["pagination"] == "complete"
    assert result["tasks"][0]["status"] == "scope_unverified"
    assert result["tasks"][0]["query_scope"] == "unknown"


def test_nested_vendor_identifiers_cannot_supply_award_identity(tmp_path):
    text = xml().replace("<fpds:awardID>", "<fpds:vendor><fpds:awardID>").replace("</fpds:awardID>", "</fpds:awardID></fpds:vendor>")
    result = run(tmp_path / "run", scenario(fpds(text)), sources=("fpds",))
    assert result["tasks"][0]["action_context_counts"] == {"missing_award_context": 1}


def parent_xml(piid="PARENT-0001", agency="8600", mod="P00001", duplicate=""):
    parent = f"<fpds:referencedIDVID><fpds:agencyID>{agency}</fpds:agencyID>{duplicate}<fpds:PIID>{piid}</fpds:PIID><fpds:modNumber>{mod}</fpds:modNumber></fpds:referencedIDVID>"
    return xml().replace("</fpds:awardID>", parent + "</fpds:awardID>")


def test_duplicate_parent_identifier_never_uses_last_value(tmp_path):
    text = parent_xml(duplicate="<fpds:PIID>OTHER-PARENT</fpds:PIID>")
    selected = replace(AWARD, parent_piid="PARENT-0001", parent_agency_id="8600")
    result = collect_selected(tmp_path / "run", [selected], limits=limits(), sources=("fpds",),
                              profile="fixture:parent", transport=FixtureTransport(scenario(fpds(text))))
    assert result["tasks"][0]["error_code"] == "conflicting_fpds_identifiers"
    assert (tmp_path / "run" / "c3_attempt_000000.body").read_bytes() == text.encode()


def test_parent_agency_mismatch_is_not_associated():
    award = replace(AWARD, parent_piid="PARENT-0001", parent_agency_id="8600").to_dict()
    parsed = parse_page("fpds", parent_xml(agency="9999").encode(), request_for("fpds", award, 1, 10), award)
    assert parsed["contexts"] == ["nonmatching_or_missing_parent_context"]


def test_parent_modification_change_does_not_invent_another_parent(tmp_path):
    first = parent_xml(mod="P00001")
    second_entry = parent_xml(mod="P00002").split("<entry>")[1].split("</entry>")[0]
    text = first.replace("</feed>", "<entry>" + second_entry + "</entry></feed>")
    result = run(tmp_path / "run", scenario(fpds(text)), sources=("fpds",))
    assert result["tasks"][0]["returned_rows"] == 2
    assert result["tasks"][0]["status"] == "scope_unverified"


def test_foreign_namespace_identifier_is_not_a_native_identifier(tmp_path):
    text = xml().replace("<fpds:PIID>", '<other:PIID xmlns:other="https://example.invalid/spoof">').replace("</fpds:PIID>", "</other:PIID>")
    result = run(tmp_path / "run", scenario(fpds(text)), sources=("fpds",))
    assert result["tasks"][0]["error_code"] == "unsupported_fpds_identifier_namespace"


@pytest.mark.parametrize("href", ["\n?start=10", "\t?start=10", "?start=10 ", "?start=0", "?start=20", "?index=99999999", "?start=10\\evil", "https://www.fpds.gov\r/ezsearch/FEEDS/ATOM?start=10"])
def test_next_links_cannot_hide_controls_skip_or_repeat_offsets(href):
    with pytest.raises(EvidenceError):
        safe_next(href, request_for("fpds", AWARD.to_dict(), 1, 10))


def test_offset_sequence_and_protocol_remain_fixed():
    request = request_for("fpds", AWARD.to_dict(), 2, 10, {"start": 10})
    assert safe_next("?start=20", request) == {"start": 20}
    with pytest.raises(EvidenceError, match="protocol_changed"):
        safe_next("?index=20", request)


def interrupted_run(path):
    data = scenario(usa())
    with pytest.raises(KeyboardInterrupt):
        collect_selected(path, [AWARD], limits=limits(), sources=("usaspending",),
                         profile="fixture:" + digest(data), transport=Mock(side_effect=KeyboardInterrupt))
    return data


@pytest.mark.parametrize("corruption", ["foreign_award", "valid_but_unexpected_page"])
def test_bad_pending_reservation_rejected_before_recovery_writes(tmp_path, corruption):
    path = tmp_path / "run"
    data = interrupted_run(path)
    cp_path = path / "c3_checkpoint.json"
    checkpoint = strict_json(cp_path.read_bytes())
    request = checkpoint["pending"]["request"]
    if corruption == "foreign_award":
        request["parameters"]["award_id"] = "OTHER-AWARD"
    else:
        request["parameters"]["page"] = request["page_index"] = 2
    cp_path.write_text(canonical(checkpoint))
    before = snapshot(path)
    with pytest.raises(EvidenceError, match="scope_conflict|replay_request_conflict"):
        run(path, data, sources=("usaspending",), resume=True)
    assert snapshot(path) == before


def test_metadata_mutation_after_initial_validation_cannot_be_replayed(tmp_path, monkeypatch):
    path, data = tmp_path / "run", scenario(usa())
    run(path, data, sources=("usaspending",))
    original = CollectionStore.saved
    def mutate(self, request):
        meta_path = path / "c3_attempt_000000.json"
        meta = strict_json(meta_path.read_bytes())
        meta["status"] = 503
        meta_path.write_text(canonical(meta))
        return original(self, request)
    monkeypatch.setattr(CollectionStore, "saved", mutate)
    cp_before = (path / "c3_checkpoint.json").read_bytes()
    with pytest.raises(EvidenceError, match="metadata_hash_mismatch"):
        run(path, data, sources=("usaspending",), resume=True)
    assert (path / "c3_checkpoint.json").read_bytes() == cp_before


def test_changed_checkpoint_is_never_blindly_replaced(tmp_path, monkeypatch):
    original = CollectionStore.reserve
    def mutate(self, request):
        cp_path = self.path / "c3_checkpoint.json"
        cp = strict_json(cp_path.read_bytes())
        cp["unexpected"] = True
        cp_path.write_text(canonical(cp))
        return original(self, request)
    monkeypatch.setattr(CollectionStore, "reserve", mutate)
    with pytest.raises(EvidenceError, match="collection_checkpoint_changed"):
        run(tmp_path / "run", scenario(usa()), sources=("usaspending",))
    assert not list((tmp_path / "run").glob("*.body"))
    assert strict_json((tmp_path / "run" / "c3_checkpoint.json").read_bytes())["unexpected"] is True


def test_final_integrity_pass_catches_already_processed_body_changes(tmp_path):
    path = tmp_path / "run"
    def mutate(_):
        (path / "c3_attempt_000000.body").write_bytes(b"changed after parsing")
    with pytest.raises(EvidenceError, match="body_hash_mismatch"):
        run(path, scenario(usa()), sources=("usaspending",), progress=mutate)
    assert not (path / "c3_summary.json").exists()


@pytest.mark.parametrize("boundary", ["before_replace", "after_replace"])
def test_checkpoint_commit_interruption_recovers_without_second_request(tmp_path, monkeypatch, boundary):
    path, data = tmp_path / "run", scenario(usa())
    original = CollectionStore._replace_json
    def interrupt(self, name, value):
        if name == "c3_checkpoint.json" and value["events"]:
            if boundary == "after_replace":
                original(self, name, value)
            raise KeyboardInterrupt
        return original(self, name, value)
    monkeypatch.setattr(CollectionStore, "_replace_json", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run(path, data, sources=("usaspending",))
    bodies = {p.name: p.read_bytes() for p in path.glob("*.body")}
    monkeypatch.setattr(CollectionStore, "_replace_json", original)
    transport = Mock(side_effect=AssertionError("no duplicate retrieval"))
    result = collect_selected(path, [AWARD], limits=limits(), sources=("usaspending",),
                              profile="fixture:" + digest(data), transport=transport, resume=True)
    assert result["requests_reserved"] == result["returned_rows"] == 1
    assert {p.name: p.read_bytes() for p in path.glob("*.body")} == bodies
    transport.assert_not_called()


def test_partial_checkpoint_temporary_is_preserved_and_blocks_resume(tmp_path, monkeypatch):
    path, data = tmp_path / "run", scenario(usa())
    original = CollectionStore._replace_json
    def interrupt(self, name, value):
        if name == "c3_checkpoint.json" and value["events"]:
            self._write_temp(name + ".next", b'{"incomplete":')
            raise KeyboardInterrupt
        return original(self, name, value)
    monkeypatch.setattr(CollectionStore, "_replace_json", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run(path, data, sources=("usaspending",))
    monkeypatch.setattr(CollectionStore, "_replace_json", original)
    before = snapshot(path)
    with pytest.raises(EvidenceError, match="partial_collection_files"):
        run(path, data, sources=("usaspending",), resume=True)
    assert snapshot(path) == before


def test_permanent_error_does_not_become_retry_after_error(tmp_path):
    result = run(tmp_path / "run", scenario(usa(status=403, retry_after="999999")), sources=("usaspending",), limits=limits(retries=2))
    assert result["tasks"][0]["error_code"] == "http_403"
    assert result["requests_reserved"] == 1


def test_incomplete_200_response_has_explicit_reason(tmp_path):
    result = run(tmp_path / "run", scenario(usa(body_complete=False)), sources=("usaspending",))
    assert result["tasks"][0]["error_code"] == "incomplete_response"


def test_partial_transport_read_is_preserved_with_timeout_metadata():
    def partial():
        yield b"available prefix"
        raise requests.Timeout
    response = Mock(status_code=200, headers={})
    response.iter_content.return_value = partial()
    session = Mock()
    session.request.return_value = response
    transport = HTTPTransport(replace(limits(), pace_seconds=0.5).to_dict(), session)
    meta, raw = transport(request_for("usaspending", AWARD.to_dict(), 1, 10), 0)
    assert raw == b"available prefix" and not meta["body_complete"]
    assert meta["error_code"] == "timeout" and meta["status"] == 200


def test_v1_c3_plan_remains_readable_but_is_not_silently_resumed(tmp_path):
    path, data = tmp_path / "run", scenario(usa())
    run(path, data, sources=("usaspending",))
    plan_path = path / "c3_plan.json"
    plan = strict_json(plan_path.read_bytes())
    plan["collector_version"] = 1
    plan_path.write_text(canonical(plan))
    fingerprint = digest(plan)
    cp_path, meta_path = path / "c3_checkpoint.json", path / "c3_attempt_000000.json"
    cp, meta = strict_json(cp_path.read_bytes()), strict_json(meta_path.read_bytes())
    cp["fingerprint"] = meta["fingerprint"] = fingerprint
    meta_path.write_text(canonical(meta))
    cp["events"][0]["metadata_sha256"] = digest(meta)
    cp_path.write_text(canonical(cp))
    assert inspect_directory(path).exit_code == 0
    before = snapshot(path)
    with pytest.raises(EvidenceError, match="incompatible_collection_plan"):
        run(path, data, sources=("usaspending",), resume=True)
    assert snapshot(path) == before


@pytest.mark.parametrize("status", [301, 403, 405])
def test_permanent_status_is_not_retried_when_reading_its_body_times_out(tmp_path, status):
    result = run(tmp_path / "run", scenario(usa(status=status, body_complete=False, error_code="timeout")),
                 sources=("usaspending",), limits=limits(retries=2))
    assert result["requests_reserved"] == 1
    assert result["tasks"][0]["error_code"] == f"http_{status}"


def test_deleted_checkpoint_is_not_recreated_during_reservation(tmp_path, monkeypatch):
    original = CollectionStore.reserve
    def delete(self, request):
        (self.path / "c3_checkpoint.json").unlink()
        return original(self, request)
    monkeypatch.setattr(CollectionStore, "reserve", delete)
    with pytest.raises(EvidenceError, match="collection_checkpoint_missing"):
        run(tmp_path / "run", scenario(usa()), sources=("usaspending",))
    assert not (tmp_path / "run" / "c3_checkpoint.json").exists()
    assert not list((tmp_path / "run").glob("*.body"))


def test_summary_task_shape_is_validated(tmp_path):
    path = tmp_path / "run"
    data = scenario(usa())
    run(path, data, sources=("usaspending",))
    summary_path = path / "c3_summary.json"
    summary = strict_json(summary_path.read_bytes())
    summary["tasks"] = ["unsupported task assertion"]
    summary_path.write_text(canonical(summary))
    before = snapshot(path)
    with pytest.raises(EvidenceError, match="unsupported_c3_completeness_claim"):
        run(path, data, sources=("usaspending",), resume=True)
    assert snapshot(path) == before


def test_capture_fields_cannot_override_reserved_request(tmp_path):
    plan = make_plan((AWARD,), limits(), ("usaspending",), "fixture:override")
    with CollectionStore(tmp_path / "run", plan) as store:
        req = {**request_for("usaspending", AWARD.to_dict(), 1, 10), "task_index": 0, "page_index": 1, "attempt_index": 0}
        store.reserve(req)
        fields = {"error_code": None, "status": 200, "retrieved_at_utc": "2025-01-01T00:00:00Z", "body_complete": True,
                  "retry_after": None, "source_update_raw": None, "request": {"endpoint": "https://example.invalid"}}
        with pytest.raises(EvidenceError, match="invalid_capture_fields"):
            store.finish(fields, b"available")
        assert not list((tmp_path / "run").glob("*.body"))


def test_body_hash_declarations_must_agree_for_metadata_as_well(tmp_path):
    path = tmp_path / "run"
    run(path, scenario(usa()), sources=("usaspending",))
    cp_path = path / "c3_checkpoint.json"
    cp = strict_json(cp_path.read_bytes())
    cp["events"][0]["body_sha256"] = "0" * 64
    cp_path.write_text(canonical(cp))
    report = inspect_directory(path)
    entry = next(e for e in report.entries if e.relative_path == "c3_attempt_000000.json")
    assert entry.error_code == "c3_body_hash_declaration_conflict"


@pytest.mark.parametrize("href", ["?" + "x" * 8192, "?" + "&".join(f"field{i}=value" for i in range(9)), "https://[invalid/ATOM?start=10"])
def test_next_link_resource_limits_and_parse_failures_are_sanitized(href):
    with pytest.raises(EvidenceError):
        safe_next(href, request_for("fpds", AWARD.to_dict(), 1, 10))


def test_query_escaping_preserves_opaque_native_identifiers():
    selected = replace(AWARD, piid='A"\\ OR *:*', agency_id="0001").to_dict()
    query = fpds_query(selected)
    assert query == 'PIID:"A\\"\\\\ OR *:*" AND CONTRACTING_AGENCY_ID:"0001"'
    assert selected["piid"] == 'A"\\ OR *:*'


def test_outgoing_request_validated_before_reserving_budget(tmp_path):
    plan = make_plan((AWARD,), limits(), ("usaspending",), "fixture:outgoing")
    with CollectionStore(tmp_path / "run", plan) as store:
        before = snapshot(store.path)
        req = {**request_for("usaspending", AWARD.to_dict(), 1, 10), "task_index": 0, "page_index": 1, "attempt_index": 0}
        req["parameters"]["award_id"] = "OTHER-AWARD"
        with pytest.raises(EvidenceError, match="scope_conflict"):
            store.reserve(req)
        assert snapshot(store.path) == before


def test_numeric_type_changes_do_not_compare_equal_in_plan_integrity(tmp_path):
    path, data = tmp_path / "run", scenario(usa())
    run(path, data, sources=("usaspending",))
    plan_path = path / "c3_plan.json"
    plan = strict_json(plan_path.read_bytes())
    plan["evidence_schema_version"] = True
    plan_path.write_text(canonical(plan))
    before = snapshot(path)
    with pytest.raises(EvidenceError, match="incompatible_collection_plan"):
        run(path, data, sources=("usaspending",), resume=True)
    assert snapshot(path) == before


def test_numeric_checkpoint_type_change_is_not_overwritten(tmp_path):
    path = tmp_path / "run"
    def mutate(_):
        cp_path = path / "c3_checkpoint.json"
        cp = strict_json(cp_path.read_bytes())
        cp["schema_version"] = 1.0
        cp_path.write_text(canonical(cp))
    with pytest.raises(EvidenceError, match="collection_checkpoint_changed"):
        run(path, scenario(usa(), fpds()), progress=mutate)
    assert len(list(path.glob("*.body"))) == 1
    assert type(strict_json((path / "c3_checkpoint.json").read_bytes())["schema_version"]) is float


def test_orphan_numeric_type_change_is_rejected_before_adoption(tmp_path, monkeypatch):
    original = CollectionStore._commit
    def interrupt(self, metadata):
        raise KeyboardInterrupt
    monkeypatch.setattr(CollectionStore, "_commit", interrupt)
    path, data = tmp_path / "run", scenario(usa())
    with pytest.raises(KeyboardInterrupt):
        run(path, data, sources=("usaspending",))
    monkeypatch.setattr(CollectionStore, "_commit", original)
    meta_path = path / "c3_attempt_000000.json"
    metadata = strict_json(meta_path.read_bytes())
    metadata["request"]["task_index"] = False
    meta_path.write_text(canonical(metadata))
    before = snapshot(path)
    with pytest.raises(EvidenceError, match="orphan_metadata_conflict"):
        run(path, data, sources=("usaspending",), resume=True)
    assert snapshot(path) == before
