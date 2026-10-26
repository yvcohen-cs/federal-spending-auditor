import hashlib
import json
import os
from dataclasses import replace

import pytest

from src.evidence import Representation, VerificationRun
from src.evidence_ingestion import (
    EvidenceObservation, IngestionManifest, ValidationStatus,
    inspect_directory, read_manifest, validate_record_ref,
)
from src.evidence_io import EvidenceError, EvidenceRoot, canonical, digest, safe_xml, write_report
from src.verify_evidence import main
from tests.ingestion_fixtures import body, fpds, legacy, stratified, write_json


def find(manifest, name):
    return next(e for e in manifest.entries if e.relative_path == name)


def unchanged(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_actual_stratified_collector_artifacts_are_read_only(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    before = unchanged(tmp_path)
    report = inspect_directory(tmp_path)
    assert report.complete and report.exit_code == 0
    assert report.summary == {"verified": 4, "incomplete": 0, "invalid": 0, "unsupported": 0}
    entry = find(report, "response_000000.json")
    assert entry.integrity == "declared_match"
    observation = entry.observation
    assert observation.artifact.sha256 == digest(json.loads(before[entry.relative_path]))
    assert observation.artifact.representation is Representation.PARSED_JSON
    assert observation.artifact.http_status is None
    assert observation.observation_id.startswith("observation:v1:")
    assert observation.records[0].reference.locator == "/response/results/0"
    assert observation.records[0].identifiers[1].value == "00001-A"
    assert observation.records[0].source_update_raw == "2025-09-30"
    assert observation.artifact.source_updated_at_utc is None
    assert unchanged(tmp_path) == before
    assert inspect_directory(tmp_path).to_json() == report.to_json()
    assert IngestionManifest.from_json(report.to_json()) == report


@pytest.mark.parametrize("transactions", [False, True])
def test_actual_legacy_collectors_preserve_unknowns(tmp_path, monkeypatch, transactions):
    legacy(tmp_path, monkeypatch, transactions)
    before = unchanged(tmp_path)
    report = inspect_directory(tmp_path)
    entry = find(report, "page_0001.json")
    assert report.exit_code == 1
    assert entry.status is ValidationStatus.INCOMPLETE
    observation = entry.observation
    assert observation.observation_id is None
    assert observation.artifact.retrieved_at_utc is None
    assert observation.artifact.request_json is None
    assert observation.records[0].reference.locator == "/results/0"
    assert observation.records[0].identifiers[0].value.startswith("0002" if transactions else "CONT_AWD_00001")
    assert unchanged(tmp_path) == before


def test_actual_fpds_collector_text_not_http_bytes(tmp_path, monkeypatch):
    fpds(tmp_path, monkeypatch)
    before = unchanged(tmp_path)
    report = inspect_directory(tmp_path)
    entry = find(report, "fpds_lookup_001_page_001.xml")
    observation = entry.observation
    assert entry.status is ValidationStatus.INCOMPLETE
    assert observation.artifact.representation is Representation.DECODED_XML
    assert observation.artifact.hash_basis == "utf8_text"
    assert observation.artifact.sha256 == hashlib.sha256(before[entry.relative_path]).hexdigest()
    assert observation.artifact.retrieved_at_utc is None
    assert "retrieved_at_utc" in observation.context_json
    assert observation.observation_id is None
    assert observation.records[0].reference.locator == "/feed/entry[1]"
    assert observation.records[0].identifiers[0].value == "8600"
    assert any(i.value == "00001" for i in observation.records[0].identifiers)
    assert unchanged(tmp_path) == before


@pytest.mark.parametrize("raw,code", [
    (b"", "empty_file"), (b"{", "malformed_json"),
    (b'{"results":[],"results":[]}', "duplicate_json_key"),
    (b'{"x":NaN}', "nonfinite_json"), (b'{"x":Infinity}', "nonfinite_json"),
    (b'{"x":1e9999}', "nonfinite_json"), (b'\xff', "malformed_json"),
    (b'[]', "invalid_envelope"),
])
def test_bad_json_files_sanitized(tmp_path, raw, code):
    (tmp_path / "response_000000.json").write_bytes(raw)
    entry = inspect_directory(tmp_path).entries[0]
    assert entry.status is ValidationStatus.INVALID
    assert entry.error_code == code
    assert entry.observation is None
    assert raw == (tmp_path / entry.relative_path).read_bytes()


@pytest.mark.parametrize("xml,code", [
    (b"<feed>", "malformed_xml"),
    (b'<!DOCTYPE feed [<!ENTITY x "expand">]><feed>&x;</feed>', "forbidden_xml_declaration"),
    (b'<!DOCTYPE feed SYSTEM "https://example.invalid/external"><feed/>', "forbidden_xml_declaration"),
    (b'<!DOCTYPE feed [<!ENTITY % ext SYSTEM "file:///etc/passwd">%ext;]><feed/>', "forbidden_xml_declaration"),
    ('<!DOCTYPE feed><feed/>'.encode("utf-16"), "malformed_xml"),
    (b"<other/>", "unsupported_xml_format"),
])
def test_xml_malformed_dtd_entities_and_external_access_are_refused(tmp_path, xml, code):
    path = tmp_path / "fpds_lookup_001_page_001.xml"
    path.write_bytes(xml)
    report = inspect_directory(tmp_path)
    assert report.entries[0].error_code == code
    assert report.entries[0].observation is None
    assert path.read_bytes() == xml


def test_missing_oversized_unreadable_and_nonregular_files(tmp_path, monkeypatch):
    with EvidenceRoot(tmp_path, max_bytes=4) as root:
        with pytest.raises(EvidenceError, match="missing_file"):
            root.read("absent.json")
        (tmp_path / "large.json").write_bytes(b"12345")
        with pytest.raises(EvidenceError, match="oversized"):
            root.read("large.json")
        original = root._open
        monkeypatch.setattr(root, "_open", lambda p: (_ for _ in ()).throw(PermissionError("secret detail")))
        with pytest.raises(EvidenceError, match="^unreadable_file$"):
            root.read("large.json")
        monkeypatch.setattr(root, "_open", original)
        os.mkfifo(tmp_path / "fifo.json")
        with pytest.raises(EvidenceError, match="unsafe_file_type"):
            root.read("fifo.json")


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", "a/../../etc/passwd", "a//b", "a/./b", "C:/file", "a\\b", "\x00"])
def test_untrusted_relative_paths_cannot_escape(tmp_path, path):
    with EvidenceRoot(tmp_path) as root:
        with pytest.raises(EvidenceError, match="unsafe_path"):
            root.read(path)


def test_symlink_and_hardlink_files_and_parent_escapes(tmp_path):
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.json").write_text("secret")
    (trusted / "file.json").symlink_to(outside / "secret.json")
    (trusted / "linked").symlink_to(outside, target_is_directory=True)
    os.link(outside / "secret.json", trusted / "hard.json")
    with EvidenceRoot(trusted) as root:
        for path in ("file.json", "linked/secret.json", "hard.json"):
            with pytest.raises(EvidenceError):
                root.read(path)
    with pytest.raises(EvidenceError):
        with EvidenceRoot(trusted / "linked"):
            pass
    report = inspect_directory(trusted)
    assert report.exit_code == 2
    assert all(e.observation is None for e in report.entries)
    assert (outside / "secret.json").read_text() == "secret"


def test_mutation_during_read_and_replaced_paths_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "page_0001.json"
    write_json(path, body())
    with EvidenceRoot(tmp_path) as root:
        original = root._open
        calls = 0
        def open_changed(name):
            nonlocal calls
            calls += 1
            if calls == 2:
                path.unlink()
                write_json(path, body())
            return original(name)
        monkeypatch.setattr(root, "_open", open_changed)
        with pytest.raises(EvidenceError, match="changed_during_read"):
            root.read(path.name)


def test_metadata_mutation_invalidates_dependents(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    original = EvidenceRoot.read
    def changed(self, path, **kw):
        if kw.get("recheck") and path == "query_metadata.json":
            data = json.loads((tmp_path / path).read_text())
            data["new_field"] = True
            write_json(tmp_path / path, data)
        return original(self, path, **kw)
    monkeypatch.setattr(EvidenceRoot, "read", changed)
    report = inspect_directory(tmp_path)
    for path in ("query_metadata.json", "response_000000.json"):
        assert find(report, path).error_code == "changed_during_validation"
        assert find(report, path).observation is None


def test_checkpoint_hash_mismatch_and_missing_page(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    path = tmp_path / "response_000000.json"
    data = json.loads(path.read_text())
    data["response"]["results"][0]["Award Amount"] = "999.00"
    write_json(path, data)
    assert find(inspect_directory(tmp_path), path.name).error_code == "hash_mismatch"
    path.unlink()
    assert find(inspect_directory(tmp_path), path.name).error_code == "missing_file"


def test_distinct_observations_share_payload_identity_without_collapsing(tmp_path, monkeypatch):
    stratified(tmp_path / "a", monkeypatch)
    stratified(tmp_path / "b", monkeypatch)
    page = tmp_path / "b" / "response_000000.json"
    data = json.loads(page.read_text())
    data["retrieved_at_utc"] = "2025-10-02T00:00:00Z"
    write_json(page, data)
    cp = tmp_path / "b" / "checkpoint.json"
    journal = json.loads(cp.read_text())
    journal["events"][0]["sha256"] = digest(data)
    write_json(cp, journal)
    observations = [e.observation for e in inspect_directory(tmp_path).entries if e.observation]
    assert len(observations) == 2
    assert observations[0].content_id == observations[1].content_id
    assert observations[0].artifact.artifact_id != observations[1].artifact.artifact_id
    assert observations[0].observation_id != observations[1].observation_id


def test_identical_legacy_content_retains_ambiguous_observations(tmp_path, monkeypatch):
    legacy(tmp_path / "a", monkeypatch)
    legacy(tmp_path / "b", monkeypatch)
    observations = [e.observation for e in inspect_directory(tmp_path).entries if e.observation]
    assert len(observations) == 2
    assert observations[0].artifact.artifact_id == observations[1].artifact.artifact_id
    assert all(o.observation_id is None for o in observations)
    assert observations[0].artifact.relative_path != observations[1].artifact.relative_path


def test_declared_manifest_roundtrip_and_locator_validation(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    report = inspect_directory(tmp_path)
    verified = inspect_directory(tmp_path, declared=report)
    assert verified.exit_code == 0
    assert all(e.integrity == "declared_match" for e in verified.entries)
    observation = find(report, "response_000000.json").observation
    ref = observation.records[0].reference
    validate_record_ref(observation, ref)
    with pytest.raises(EvidenceError, match="invalid_record_locator"):
        validate_record_ref(observation, replace(ref, locator="/response/results/99"))
    bad_row = replace(observation.records[0], reference=replace(ref, locator="/response/results/99"))
    bad_obs = replace(observation, records=(bad_row,))
    bad_entries = tuple(replace(e, observation=bad_obs) if e.observation else e for e in report.entries)
    invalid = inspect_directory(tmp_path, declared=replace(report, entries=bad_entries))
    assert find(invalid, "response_000000.json").error_code == "invalid_record_locator"


def test_declared_manifest_hash_mismatch_and_added_missing_files(tmp_path, monkeypatch):
    legacy(tmp_path, monkeypatch)
    report = inspect_directory(tmp_path)
    write_json(tmp_path / "page_0001.json", {"results": []})
    assert find(inspect_directory(tmp_path, declared=report), "page_0001.json").error_code == "hash_mismatch"
    (tmp_path / "page_0001.json").unlink()
    assert find(inspect_directory(tmp_path, declared=report), "page_0001.json").error_code == "missing_file"
    (tmp_path / "new.bin").write_bytes(b"unsupported")
    assert find(inspect_directory(tmp_path), "new.bin").status is ValidationStatus.UNSUPPORTED


def test_manifest_rejects_versions_paths_and_unsupported_hash_basis(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    report = inspect_directory(tmp_path)
    for field, value in (("relative_path", "../outside"),):
        doc = report.to_dict()
        doc["entries"][0][field] = value
        with pytest.raises(ValueError):
            IngestionManifest.from_dict(doc)
    doc = report.to_dict()
    for e in doc["entries"]:
        if e["observation"]:
            e["observation"]["artifact"]["hash_basis"] = "original_bytes"
    with pytest.raises(ValueError):
        IngestionManifest.from_dict(doc)
    doc = report.to_dict()
    doc["schema_version"] = 2
    with pytest.raises(ValueError):
        IngestionManifest.from_dict(doc)


def test_missing_or_conflicting_metadata_no_fabrication(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    (tmp_path / "query_metadata.json").unlink()
    report = inspect_directory(tmp_path)
    o = find(report, "response_000000.json").observation
    assert o.artifact.endpoint is None
    assert o.observation_id is None
    legacy(tmp_path / "old", monkeypatch)
    metadata = tmp_path / "old" / "query_metadata.json"
    doc = json.loads(metadata.read_text())
    doc["endpoint"] = "https://example.invalid/wrong"
    write_json(metadata, doc)
    assert find(inspect_directory(tmp_path), "old/page_0001.json").status is ValidationStatus.INVALID


def test_sensitive_metadata_is_not_echoed(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    path = tmp_path / "response_000000.json"
    doc = json.loads(path.read_text())
    doc["request"]["authorization"] = "VERY_SECRET"
    write_json(path, doc)
    report = inspect_directory(tmp_path)
    assert find(report, path.name).error_code == "sensitive_metadata"
    assert "VERY_SECRET" not in report.to_json()


def test_limits_partial_failure_and_interruption(tmp_path, monkeypatch):
    legacy(tmp_path, monkeypatch)
    report = inspect_directory(tmp_path, max_total_bytes=10)
    assert report.exit_code == 2
    assert all(e.observation is None for e in report.entries)
    assert inspect_directory(tmp_path, max_files=1).complete is False
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert inspect_directory(tmp_path, max_depth=1).complete is False
    original = EvidenceRoot.read
    calls = 0
    def interrupted(self, path, **kw):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise KeyboardInterrupt
        return original(self, path, **kw)
    monkeypatch.setattr(EvidenceRoot, "read", interrupted)
    report = inspect_directory(tmp_path)
    assert not report.complete and report.errors == ("interrupted",)
    assert report.exit_code == 130
    assert all(e.observation is None for e in report.entries)


def test_output_destinations_refuse_evidence_overwrite_and_symlinks(tmp_path):
    root = tmp_path / "evidence"
    root.mkdir()
    with pytest.raises(EvidenceError, match="output_inside_evidence"):
        write_report(str(root / "report.json"), "{}", str(root))
    output = tmp_path / "report.json"
    write_report(str(output), "{}", str(root))
    with pytest.raises(EvidenceError):
        write_report(str(output), "new", str(root))
    assert output.read_text() == "{}\n"
    linked = tmp_path / "link"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(EvidenceError):
        write_report(str(linked / "report.json"), "{}", str(root))


def test_cli_report_codes_manifest_replay_and_execution_time(tmp_path, monkeypatch, capsys):
    root = tmp_path / "evidence"
    stratified(root, monkeypatch)
    assert main(["--root", str(root)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 0
    report = read_manifest(payload)
    assert payload["summary"] == report.summary
    write_json(root / "validation.json", payload)
    assert main(["--root", str(root), "--manifest", "validation.json"]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["substantive_sha256"] != payload["substantive_sha256"]  # integrity now declared for metadata too
    assert main(["--root", str(root), "--manifest", "validation.json", "--execution-time"]) == 0
    timed = json.loads(capsys.readouterr().out)
    assert timed["manifest"]["executed_at_utc"] is not None
    assert timed["substantive_sha256"] == replay["substantive_sha256"]
    assert main(["--root", str(root), "--manifest", "../outside"]) == 2
    assert json.loads(capsys.readouterr().out)["exit_code"] == 2
    assert main(["--root", str(root), "--output", str(root / "bad.json")]) == 2
    assert json.loads(capsys.readouterr().out)["exit_code"] == 2


def test_cli_incomplete_unsupported_empty_invalid_and_saved_report(tmp_path, monkeypatch, capsys):
    root = tmp_path / "evidence"
    root.mkdir()
    assert main(["--root", str(root)]) == 1
    capsys.readouterr()
    legacy(root, monkeypatch)
    output = tmp_path / "report.json"
    assert main(["--root", str(root), "--output", str(output)]) == 1
    assert read_manifest(json.loads(output.read_text())).exit_code == 1
    (root / "other.txt").write_text("data")
    assert main(["--root", str(root)]) == 1
    assert json.loads(capsys.readouterr().out)["summary"]["unsupported"] == 1
    (root / "page_0001.json").write_text("invalid")
    assert main(["--root", str(root)]) == 2
    assert json.loads(capsys.readouterr().out)["summary"]["invalid"] == 1


def test_c1_manifest_reader_preserves_hash_basis_and_golden_compatibility(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    observation = find(inspect_directory(tmp_path), "response_000000.json").observation
    old = VerificationRun(code_revision="synthetic", rule_version="v1", parser_version="v1",
                          config_sha256="1" * 64, artifacts=(observation.artifact,), results=())
    write_json(tmp_path / "v1-manifest.json", old.to_dict())
    assert read_manifest(old.to_dict()) == old
    report = inspect_directory(tmp_path, manifest_path="v1-manifest.json")
    assert report.exit_code == 0
    assert find(report, "response_000000.json").integrity == "declared_match"
    # Formatting changes preserve a declared canonical JSON hash, not byte hash.
    page = tmp_path / "response_000000.json"
    page.write_text(canonical(json.loads(page.read_text())))
    assert inspect_directory(tmp_path, manifest_path="v1-manifest.json").exit_code == 0
    bad = replace(old, artifacts=(replace(observation.artifact, sha256="9" * 64),))
    write_json(tmp_path / "v1-manifest.json", bad.to_dict())
    assert find(inspect_directory(tmp_path, manifest_path="v1-manifest.json"), page.name).error_code == "hash_or_representation_mismatch"


@pytest.mark.parametrize("changes", [
    {"version": True}, {"events": [{"step": False, "sha256": "1" * 64}]},
    {"events": [{"step": 1, "sha256": "1" * 64}]},
    {"complete": "yes"}, {"query_fingerprint": "bad"},
])
def test_invalid_checkpoint_cannot_support_dependent_observations(tmp_path, monkeypatch, changes):
    stratified(tmp_path, monkeypatch)
    path = tmp_path / "checkpoint.json"
    doc = json.loads(path.read_text())
    doc.update(changes)
    write_json(path, doc)
    report = inspect_directory(tmp_path)
    assert find(report, path.name).status is ValidationStatus.INVALID
    assert find(report, "response_000000.json").observation is None


def test_empty_metadata_and_bad_timestamp_do_not_become_missing(tmp_path, monkeypatch):
    legacy(tmp_path, monkeypatch)
    write_json(tmp_path / "query_metadata.json", {})
    report = inspect_directory(tmp_path)
    assert find(report, "page_0001.json").status is ValidationStatus.INVALID
    fpds(tmp_path / "fpds", monkeypatch)
    path = tmp_path / "fpds" / "fpds_lookup_001_query.json"
    doc = json.loads(path.read_text())
    doc["retrieved_at_utc"] = 123
    write_json(path, doc)
    report = inspect_directory(tmp_path)
    assert find(report, "fpds/fpds_lookup_001_page_001.xml").error_code == "invalid_timestamp"


def test_conflicting_event_payloads_never_choose_one(tmp_path, monkeypatch):
    stratified(tmp_path / "a", monkeypatch)
    stratified(tmp_path / "b", monkeypatch)
    path = tmp_path / "b" / "response_000000.json"
    doc = json.loads(path.read_text())
    doc["response"]["results"][0]["Award Amount"] = "110.00"
    write_json(path, doc)
    journal = tmp_path / "b" / "checkpoint.json"
    cp = json.loads(journal.read_text())
    cp["events"][0]["sha256"] = digest(doc)
    write_json(journal, cp)
    report = inspect_directory(tmp_path)
    for name in ("a/response_000000.json", "b/response_000000.json"):
        assert find(report, name).error_code == "conflicting_observation_payloads"


def test_duplicate_documented_observations_are_inventory_occurrences_not_payments(tmp_path, monkeypatch):
    stratified(tmp_path / "a", monkeypatch)
    stratified(tmp_path / "b", monkeypatch)
    observations = [e.observation for e in inspect_directory(tmp_path).entries if e.observation]
    assert len(observations) == 2
    assert observations[0].artifact.artifact_id == observations[1].artifact.artifact_id
    assert observations[0].observation_id == observations[1].observation_id


def test_invalid_record_ids_not_coerced_or_exposed_in_errors(tmp_path, monkeypatch):
    legacy(tmp_path, monkeypatch, transactions=True)
    path = tmp_path / "page_0001.json"
    doc = json.loads(path.read_text())
    doc["results"][0]["id"] = 123
    write_json(path, doc)
    report = inspect_directory(tmp_path)
    row = find(report, path.name).observation
    assert "nonstring_native_identifier_not_coerced" in row.artifact.limitations
    assert all(i.value != "123" for i in row.records[0].identifiers)
    doc["results"][0]["id"] = "BAD\nSECRET"
    write_json(path, doc)
    report = inspect_directory(tmp_path)
    assert find(report, path.name).error_code == "invalid_native_identifier"
    assert "SECRET" not in report.to_json()


def test_record_reference_identity_and_source_conflicts(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    obs = find(inspect_directory(tmp_path), "response_000000.json").observation
    ref = obs.records[0].reference
    with pytest.raises(EvidenceError, match="record_reference_conflict"):
        validate_record_ref(obs, replace(ref, artifact_id="artifact:sha256:" + "0" * 64))
    from src.evidence import SourceIdentifier
    other = SourceIdentifier(source="usaspending", namespace="generated_internal_id", value="000-other")
    with pytest.raises(EvidenceError, match="record_reference_conflict"):
        validate_record_ref(obs, replace(ref, native_id=other))


def test_manifest_ordering_wrapper_consistency_and_provenance_conflict(tmp_path, monkeypatch):
    legacy(tmp_path, monkeypatch)
    report = inspect_directory(tmp_path)
    with pytest.raises(ValueError):
        replace(report, entries=tuple(reversed(report.entries)))
    wrapper = {"manifest": report.to_dict(), "summary": {}, "substantive_sha256": report.substantive_sha256, "exit_code": report.exit_code}
    with pytest.raises(EvidenceError, match="invalid_manifest_summary"):
        read_manifest(wrapper)
    write_json(tmp_path / "manifest.json", {"schema_version": 99})
    assert inspect_directory(tmp_path, manifest_path="manifest.json").complete is False
    (tmp_path / "manifest.json").unlink()
    entries = tuple(replace(e, observation=replace(e.observation, context_json='{"changed":true}')) if e.observation else e for e in report.entries)
    assert find(inspect_directory(tmp_path, declared=replace(report, entries=entries)), "page_0001.json").error_code == "manifest_observation_conflict"


def test_directory_growth_and_scan_failure_invalidate_partial_success(tmp_path, monkeypatch):
    legacy(tmp_path, monkeypatch)
    original = EvidenceRoot.discover
    calls = 0
    def grow(self):
        nonlocal calls
        calls += 1
        if calls == 2:
            (tmp_path / "new.txt").write_text("new")
        return original(self)
    monkeypatch.setattr(EvidenceRoot, "discover", grow)
    report = inspect_directory(tmp_path)
    assert not report.complete and report.errors == ("directory_changed_during_validation",)
    assert all(e.observation is None for e in report.entries)


def test_binary_read_growth_and_root_replacement_detection(tmp_path, monkeypatch):
    write_json(tmp_path / "page_0001.json", body())
    original = os.fstat
    calls = 0
    def mutate(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            (tmp_path / "page_0001.json").write_text("changed")
        return original(fd)
    with EvidenceRoot(tmp_path) as root:
        monkeypatch.setattr(os, "fstat", mutate)
        with pytest.raises(EvidenceError, match="changed_during_read"):
            root.read("page_0001.json")


def test_output_existing_symlink_parent_and_invalid_limits(tmp_path, capsys):
    root = tmp_path / "evidence"
    root.mkdir()
    target = tmp_path / "target.json"
    target.write_text("preserve")
    linked = tmp_path / "output.json"
    linked.symlink_to(target)
    with pytest.raises(EvidenceError):
        write_report(str(linked), "overwrite", str(root))
    assert target.read_text() == "preserve"
    assert main(["--root", str(root), "--max-artifact-bytes", "0"]) == 2
    assert "invalid_limits" in capsys.readouterr().out


def test_cli_interrupt_code_and_no_network_dependency(tmp_path, monkeypatch, capsys):
    import src.verify_evidence as cli
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, "inspect_directory", interrupted)
    assert cli.main(["--root", str(tmp_path)]) == 130
    assert json.loads(capsys.readouterr().out)["error_code"] == "interrupted"


def test_xml_depth_node_limits_encoding_and_xinclude_do_not_fetch(monkeypatch):
    with pytest.raises(EvidenceError, match="xml_depth_limit"):
        safe_xml(("<a>" * 129 + "</a>" * 129).encode())
    with pytest.raises(EvidenceError, match="xml_node_limit"):
        safe_xml(("<root>" + "<a/>" * 100_000 + "</root>").encode())
    with pytest.raises(EvidenceError, match="unsupported_xml_encoding"):
        safe_xml(b'<?xml version="1.0" encoding="UTF-16"?><feed/>')
    import socket
    def forbidden(*args, **kwargs):
        raise AssertionError("network forbidden")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    text, tree = safe_xml(b'<root xmlns:xi="http://www.w3.org/2001/XInclude"><xi:include href="https://example.invalid/no-fetch"/></root>')
    assert len(tree) == 1 and "include" in tree[0].tag


def test_observation_computed_wire_ids_cannot_be_forged(tmp_path, monkeypatch):
    legacy(tmp_path, monkeypatch)
    observation = find(inspect_directory(tmp_path), "page_0001.json").observation
    doc = observation.to_dict()
    assert doc["observation_id"] is None and doc["observation_identity_status"] == "ambiguous"
    doc["content_id"] = "content:sha256:" + "9" * 64
    with pytest.raises(ValueError, match="conflicts"):
        EvidenceObservation.from_dict(doc)


def test_request_and_pagination_contradictions(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    path = tmp_path / "response_000000.json"
    original = json.loads(path.read_text())
    cp = tmp_path / "checkpoint.json"
    journal = json.loads(cp.read_text())
    for key, value in (("page", False), ("limit", -1)):
        doc = json.loads(json.dumps(original))
        doc["request"][key] = value
        write_json(path, doc)
        assert find(inspect_directory(tmp_path), path.name).error_code == "invalid_request"
    doc = json.loads(json.dumps(original))
    doc["response"]["page_metadata"]["hasNext"] = "yes"
    write_json(path, doc)
    journal["events"][0]["sha256"] = digest(doc)
    write_json(cp, journal)
    assert find(inspect_directory(tmp_path), path.name).error_code == "invalid_pagination_metadata"


def test_unjournaled_page_after_complete_checkpoint_is_invalid(tmp_path, monkeypatch):
    stratified(tmp_path, monkeypatch)
    (tmp_path / "response_000001.json").write_bytes((tmp_path / "response_000000.json").read_bytes())
    assert find(inspect_directory(tmp_path), "response_000001.json").error_code == "unexpected_response_after_complete_checkpoint"


def test_missing_declared_manifest_does_not_read_outside_root(tmp_path):
    report = inspect_directory(tmp_path, manifest_path="missing.json")
    assert not report.complete and report.exit_code == 2
    assert report.entries == ()
