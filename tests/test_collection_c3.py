"""Synthetic C3 contracts. No real API access; original pipeline tests remain."""
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
import requests

from src.collect_evidence import main
from src.collection import CollectionLimits, SelectedAward, collect_selected, retry_delay
from src.collection_sources import FixtureTransport, HTTPTransport, fpds_query, parse_page, request_for, safe_next
from src.collection_store import CollectionStore
from src.evidence_ingestion import inspect_directory
from src.evidence_io import EvidenceError, canonical, digest, strict_json
from tests.test_reconciliation import FPDS_XML


AWARD = SelectedAward(generated_id="CONT_AWD_00001_8600_-NONE-_-NONE-", piid="00001", agency_id="8600")


def limits(**kw):
    return replace(CollectionLimits(pace_seconds=0.0, backoff_seconds=0.0, retries=0,
                                     max_records_per_source_award=20, max_records_total=100), **kw)


def tx(ids=("0001.A",), more=False, page=1):
    return {"results": [{"id": value, "action_date": "2025-01-01", "modification_number": f"P{index:05d}",
                          "federal_action_obligation": [-20, 0, 125][index % 3]} for index, value in enumerate(ids)],
            "page_metadata": {"page": page, "hasNext": more}}


def xml(more=False, **changes):
    text = FPDS_XML
    if not more:
        text = text.replace('<link rel="next" href="https://www.fpds.gov/ezsearch/FEEDS/ATOM?start=10" />', "")
    for old, new in changes.items():
        text = text.replace(old, new)
    return text


def scenario(*responses):
    return {"schema_version": 1, "responses": list(responses)}


def usa(body=None, **kw):
    return {"source": "usaspending", "json": tx() if body is None else body, **kw}


def fpds(text=None, **kw):
    return {"source": "fpds", "text": xml() if text is None else text, **kw}


def run(path, responses, **kw):
    return collect_selected(path, [AWARD], limits=kw.pop("limits", limits()),
                            profile="fixture:" + digest(responses), transport=FixtureTransport(responses),
                            sleep=lambda _: None, **kw)


def test_both_sources_preserve_actions_and_ingest_without_legacy_changes(tmp_path):
    path = tmp_path / "run"
    summary = run(path, scenario(usa(tx(("0001.A", "0002-B", "0003/0"))), fpds()))
    assert summary["returned_rows"] == 4
    assert summary["responses_preserved"] == 2
    assert all(t["pagination"] == "complete" and t["history"] == t["freshness"] == "unknown" for t in summary["tasks"])
    assert strict_json((path / "c3_attempt_000000.body").read_bytes())["results"][0]["federal_action_obligation"] == -20
    for i in range(2):
        meta = json.loads((path / f"c3_attempt_{i:06d}.json").read_text())
        assert meta["status"] == 200 and meta["body_processing"] == "application_body_bytes_not_wire_capture"
        assert meta["body_sha256"] == hashlib.sha256((path / f"c3_attempt_{i:06d}.body").read_bytes()).hexdigest()
    report = inspect_directory(path)
    assert report.exit_code == 0, report.to_json()
    observations = [e.observation for e in report.entries if e.observation]
    assert len(observations) == 2
    assert observations[0].artifact.representation.value == "response_bytes"
    assert "synthetic_fixture_only" in observations[0].artifact.limitations
    assert any(i.value == "0001.A" for i in observations[0].records[0].identifiers)


def test_resume_is_offline_and_summary_identical(tmp_path):
    path = tmp_path / "run"
    data = scenario(usa(), fpds())
    original = run(path, data)
    before = {p.name: p.read_bytes() for p in path.glob("c3_attempt_*")}
    transport = Mock(side_effect=AssertionError("no repeated network"))
    resumed = collect_selected(path, [AWARD], limits=limits(), profile="fixture:" + digest(data),
                               transport=transport, resume=True, sleep=lambda _: None)
    assert resumed == original
    assert {p.name: p.read_bytes() for p in path.glob("c3_attempt_*")} == before
    transport.assert_not_called()


def test_fixed_transaction_limits_and_global_page_bounds(tmp_path):
    data = scenario(usa(tx(("1", "2"), True)), usa(tx(("3", "4"), False, 2)))
    summary = run(tmp_path / "run", data, sources=("usaspending",),
                  limits=limits(page_size=2, max_records_per_source_award=3))
    assert summary["tasks"][0]["error_code"] == "record_limit"
    assert summary["returned_rows"] == 2
    assert summary["requests_reserved"] == 1
    data = scenario(usa(tx(("1", "2"), True)), usa(tx(("3", "4"), True, 2)))
    summary = run(tmp_path / "pages", data, sources=("usaspending",), limits=limits(page_size=2))
    assert summary["tasks"][0]["error_code"] == "page_limit"
    for i in range(2):
        metadata = json.loads((tmp_path / "pages" / f"c3_attempt_{i:06d}.json").read_text())
        assert metadata["request"]["parameters"]["limit"] == 2


def test_repeated_pages_and_retrieval_duplicate_rows_are_not_payments(tmp_path):
    data = scenario(usa(tx(("1", "2"), True)), usa(tx(("1", "2"), False, 2)))
    summary = run(tmp_path / "repeat", data, sources=("usaspending",), limits=limits(page_size=2))
    task = summary["tasks"][0]
    assert task["error_code"] == "repeated_page_content"
    assert task["returned_rows"] == 4 and task["unique_retrieval_rows"] == task["duplicate_retrieval_rows"] == 2
    assert len(list((tmp_path / "repeat").glob("*.body"))) == 2
    data = scenario(usa(tx(("same", "same"))))
    # Different modification/amount fields remain distinct raw retrieval rows.
    result = run(tmp_path / "amended", data, sources=("usaspending",))
    assert result["tasks"][0]["unique_retrieval_rows"] == 2


def test_fpds_modifications_agency_and_parent_context(tmp_path):
    first = xml()
    entry = first.split("<entry>")[1].split("</entry>")[0]
    multi = first.replace("</feed>", "<entry>" + entry.replace("P00001", "P00002").replace("25.00", "0.00") + "</entry></feed>")
    result = run(tmp_path / "multi", scenario(fpds(multi)), sources=("fpds",))
    assert result["returned_rows"] == 2
    assert result["tasks"][0]["action_context_counts"] == {"query_bound_candidate": 2}
    result = run(tmp_path / "mismatch", scenario(fpds(xml(**{"8600": "9999"}))), sources=("fpds",))
    assert result["tasks"][0]["status"] == "context_unresolved"
    assert result["tasks"][0]["pagination"] == "complete"
    parent = replace(AWARD, parent_piid="PARENT-0001", parent_agency_id="8600")
    result = collect_selected(tmp_path / "parent", [parent], sources=("fpds",), limits=limits(),
                              transport=FixtureTransport(scenario(fpds())), profile="fixture:parent", sleep=lambda _: None)
    assert result["tasks"][0]["query_scope"] == "partial"


def test_missing_and_ambiguous_selections_do_not_infer_mapping(tmp_path):
    transport = Mock(side_effect=AssertionError("no request"))
    selection = [SelectedAward(piid="00001")]
    summary = collect_selected(tmp_path / "missing", selection, limits=limits(), profile="fixture:missing", transport=transport)
    assert all(t["status"] == "unresolved_identifiers" for t in summary["tasks"])
    selected = [AWARD, replace(AWARD, generated_id="DIFFERENT")]
    summary = collect_selected(tmp_path / "ambiguous", selected, sources=("fpds",), limits=limits(), profile="fixture:ambiguous", transport=transport)
    assert all(t["status"] == "ambiguous_selection" for t in summary["tasks"])
    transport.assert_not_called()


@pytest.mark.parametrize("bad", ["", "  ", "bad\nvalue", 123, True])
def test_invalid_native_selection(bad):
    with pytest.raises(ValueError):
        SelectedAward(generated_id=bad)


@pytest.mark.parametrize("status", [403, 405, 404, 301])
def test_permanent_errors_and_redirects_not_retried(tmp_path, status):
    summary = run(tmp_path / "run", scenario(usa(status=status)), sources=("usaspending",), limits=limits(retries=2))
    assert summary["requests_reserved"] == 1
    assert summary["tasks"][0]["error_code"] == f"http_{status}"
    assert len(list((tmp_path / "run").glob("*.body"))) == 1


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retry_status_observations_preserved_and_request_budget(tmp_path, status):
    data = scenario(usa(status=status, retry_after="0"), usa())
    result = run(tmp_path / "retry", data, sources=("usaspending",), limits=limits(retries=1))
    assert result["requests_reserved"] == result["responses_preserved"] == 2
    assert result["tasks"][0]["pagination"] == "complete"
    report = inspect_directory(tmp_path / "retry")
    assert report.exit_code == 1 and report.summary["incomplete"] == 1
    result = run(tmp_path / "budget", data, sources=("usaspending",), limits=limits(retries=1, max_requests=1))
    assert result["tasks"][0]["error_code"] == "request_limit"


def test_retry_after_dates_and_excessive_wait_are_bounded(tmp_path):
    cfg = limits(backoff_seconds=1.0)
    meta = {"retry_after": "Wed, 01 Jan 2025 00:00:05 GMT", "retrieved_at_utc": "2025-01-01T00:00:00Z"}
    assert retry_delay(meta, 0, cfg) == 5
    assert retry_delay({"retry_after": "9999"}, 0, cfg) is None
    assert retry_delay({"retry_after": "NaN"}, 0, cfg) is None
    result = run(tmp_path / "run", scenario(usa(status=429, retry_after="9999")), sources=("usaspending",), limits=limits(retries=1))
    assert result["tasks"][0]["error_code"] == "retry_after_exceeds_bound"


@pytest.mark.parametrize("body", [{}, {"results": []}, tx(page=2), {"results": [], "page_metadata": {"hasNext": "yes", "page": 1}}])
def test_schema_changes_malformed_pagination_preserved(tmp_path, body):
    result = run(tmp_path / "run", scenario(usa(body)), sources=("usaspending",))
    assert result["tasks"][0]["status"] == "source_error"
    assert result["responses_preserved"] == 1
    assert (tmp_path / "run" / "c3_attempt_000000.body").is_file()


@pytest.mark.parametrize("next_url", ["http://www.fpds.gov/ezsearch/FEEDS/ATOM?start=10", "https://evil.invalid/ATOM?start=10", "https://www.fpds.gov/other?start=10", "?start=10&q=WRONG", "?start=10&token=SECRET", "?start=10&index=10", "?start=10&start=20"])
def test_unsafe_or_unsupported_next_links_never_fetch(next_url):
    with pytest.raises((EvidenceError, ValueError)):
        safe_next(next_url, request_for("fpds", AWARD.to_dict(), 1, 10))


def test_fpds_next_requests_keep_scope_and_bounded_pages(tmp_path):
    data = scenario(fpds(xml(True)), fpds(xml(False, **{"P00001": "P00002"})))
    result = run(tmp_path / "run", data, sources=("fpds",))
    assert result["returned_rows"] == 2
    second = json.loads((tmp_path / "run" / "c3_attempt_000001.json").read_text())
    assert second["request"]["parameters"]["start"] == 10
    assert second["request"]["parameters"]["q"] == fpds_query(AWARD.to_dict())


def test_plan_changes_and_corrupt_artifacts_refused_without_overwrite(tmp_path):
    path = tmp_path / "run"
    data = scenario(usa())
    run(path, data, sources=("usaspending",))
    before = {p.name: p.read_bytes() for p in path.iterdir()}
    with pytest.raises(EvidenceError, match="incompatible_collection_plan"):
        run(path, data, sources=("usaspending",), resume=True, limits=limits(max_pages=3))
    assert before == {p.name: p.read_bytes() for p in path.iterdir()}
    (path / "c3_attempt_000000.body").write_bytes(b"changed")
    with pytest.raises(EvidenceError, match="hash_mismatch"):
        run(path, data, sources=("usaspending",), resume=True)
    assert inspect_directory(path).exit_code == 2


def test_completed_orphan_recovered_after_journal_interruption(tmp_path, monkeypatch):
    path, data = tmp_path / "run", scenario(usa())
    commit = CollectionStore._commit
    def interrupted(self, metadata):
        raise KeyboardInterrupt
    monkeypatch.setattr(CollectionStore, "_commit", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run(path, data, sources=("usaspending",))
    monkeypatch.setattr(CollectionStore, "_commit", commit)
    mock = Mock(side_effect=AssertionError("orphan must not be re-requested"))
    result = collect_selected(path, [AWARD], limits=limits(), sources=("usaspending",),
                              profile="fixture:" + digest(data), transport=mock, resume=True, sleep=lambda _: None)
    assert result["returned_rows"] == 1
    mock.assert_not_called()


def test_reserved_unknown_attempt_is_not_silently_reissued(tmp_path):
    path = tmp_path / "run"
    data = scenario(usa())
    transport = Mock(side_effect=KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        collect_selected(path, [AWARD], limits=limits(), sources=("usaspending",),
                         profile="fixture:" + digest(data), transport=transport)
    result = run(path, data, sources=("usaspending",), resume=True)
    assert result["requests_reserved"] == 1 and result["responses_preserved"] == 0
    assert result["tasks"][0]["error_code"] == "interrupted_request_outcome_unknown"


def test_partial_write_refused_preserving_previous_evidence(tmp_path, monkeypatch):
    path = tmp_path / "run"
    create = CollectionStore._create
    def partial(self, name, raw):
        if name.endswith(".body"):
            self._write_temp(name + ".partial", raw[:2])
            raise KeyboardInterrupt
        return create(self, name, raw)
    monkeypatch.setattr(CollectionStore, "_create", partial)
    with pytest.raises(KeyboardInterrupt):
        run(path, scenario(usa()), sources=("usaspending",))
    before = (path / "c3_attempt_000000.body.partial").read_bytes()
    monkeypatch.setattr(CollectionStore, "_create", create)
    with pytest.raises(EvidenceError, match="partial_collection_files"):
        run(path, scenario(usa()), sources=("usaspending",), resume=True)
    assert (path / "c3_attempt_000000.body.partial").read_bytes() == before


def test_transport_real_response_truthiness_timeout_and_tls(tmp_path):
    session = Mock()
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "2"
    response.iter_content = Mock(return_value=iter([b"rate limit"]))
    response.close = Mock()
    session.request.return_value = response
    transport = HTTPTransport(CollectionLimits().to_dict(), session)
    request = request_for("usaspending", AWARD.to_dict(), 1, 10)
    meta, raw = transport(request, 0)
    assert meta["status"] == 429 and meta["retry_after"] == "2" and raw == b"rate limit"
    assert session.request.call_args.kwargs["allow_redirects"] is False
    assert "verify" not in session.request.call_args.kwargs
    for exception, code in ((requests.Timeout(), "timeout"), (requests.ConnectionError(), "connection_error"), (requests.exceptions.SSLError(), "tls_error")):
        session.request.side_effect = exception
        meta, raw = transport(request, 0)
        assert meta["error_code"] == code and raw is None


def test_transport_size_limit_keeps_partial_application_body():
    response = Mock(status_code=200, headers={})
    response.iter_content.return_value = iter([b"123456"])
    session = Mock()
    session.request.return_value = response
    transport = HTTPTransport(replace(CollectionLimits(), max_response_bytes=4).to_dict(), session)
    meta, raw = transport(request_for("usaspending", AWARD.to_dict(), 1, 10), 0)
    assert raw == b"1234" and meta["body_complete"] is False
    assert meta["error_code"] == "response_size_limit"


def test_cli_fixture_resume_and_unknown_filters(tmp_path, capsys):
    selected = tmp_path / "selection.json"
    selected.write_text(canonical({"awards": [{"generated_id": AWARD.generated_id}]}))
    fixture = tmp_path / "fixture.json"
    fixture.write_text(canonical(scenario(usa())))
    args = ["--selection", str(selected), "--run-dir", str(tmp_path / "run"), "--fixture", str(fixture), "--sources", "usaspending", "--retries", "0"]
    assert main(args) == 0
    original = json.loads(capsys.readouterr().out)
    assert main(args + ["--resume"]) == 0
    assert json.loads(capsys.readouterr().out) == original
    assert main(args) == 2
    capsys.readouterr()
    selected.write_text(canonical({"awards": [{"generated_id": AWARD.generated_id, "filters": {"unsupported": True}}]}))
    assert main(args) == 2
    assert "unsupported" not in capsys.readouterr().err


def test_secure_run_root_symlink_and_extra_evidence(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "linked").symlink_to(real, target_is_directory=True)
    with pytest.raises((EvidenceError, OSError)):
        run(tmp_path / "linked" / "run", scenario(usa()), sources=("usaspending",))
    path = tmp_path / "run"
    data = scenario(usa())
    run(path, data, sources=("usaspending",))
    (path / "unexpected.json").write_text("{}")
    with pytest.raises(EvidenceError, match="unexpected"):
        run(path, data, sources=("usaspending",), resume=True)


def test_identical_content_different_retrieval_times_preserved(tmp_path):
    data = scenario(usa(status=503, retrieved_at_utc="2025-01-01T00:00:00Z"),
                    usa(status=200, retrieved_at_utc="2025-01-01T00:00:01Z"))
    run(tmp_path / "run", data, sources=("usaspending",), limits=limits(retries=1))
    observed = [e.observation for e in inspect_directory(tmp_path / "run").entries if e.observation]
    assert len(observed) == 2
    assert observed[0].artifact.artifact_id == observed[1].artifact.artifact_id
    assert observed[0].observation_id != observed[1].observation_id
    assert all(o.artifact.source_updated_at_utc is None for o in observed)


def test_unknown_and_negative_zero_obligation_fields_are_not_compared(tmp_path):
    payload = tx(("a", "b", "c"))
    result = run(tmp_path / "run", scenario(usa(payload)), sources=("usaspending",))
    saved = strict_json((tmp_path / "run" / "c3_attempt_000000.body").read_bytes())
    assert [r["federal_action_obligation"] for r in saved["results"]] == [-20, 0, 125]
    assert result["historical_completeness"] == "unknown"
    assert "amount_difference" not in canonical(result)


def test_exact_retrieval_duplicates_within_page_retained(tmp_path):
    payload = tx()
    payload["results"] *= 2
    result = run(tmp_path / "run", scenario(usa(payload)), sources=("usaspending",))
    assert result["returned_rows"] == 2
    assert result["tasks"][0]["duplicate_retrieval_rows"] == 1
    assert len(strict_json((tmp_path / "run" / "c3_attempt_000000.body").read_bytes())["results"]) == 2


def test_failed_attempts_consume_record_slots_before_retry(tmp_path):
    result = run(tmp_path / "run", scenario(usa(status=429), usa()), sources=("usaspending",),
                 limits=limits(retries=1, max_records_total=10))
    assert result["record_slots_requested"] == 10
    assert result["requests_reserved"] == 1
    assert result["tasks"][0]["error_code"] == "record_request_budget"


@pytest.mark.parametrize("error", ["timeout", "connection_error", "tls_error"])
def test_network_failures_journaled_and_retried_only_when_appropriate(tmp_path, error):
    data = scenario(usa(status=None, error_code=error, body_complete=False), usa())
    result = run(tmp_path / "run", data, sources=("usaspending",), limits=limits(retries=1))
    assert result["requests_reserved"] == (1 if error == "tls_error" else 2)
    assert result["responses_preserved"] == (0 if error == "tls_error" else 1)
    report = inspect_directory(tmp_path / "run")
    assert report.exit_code == 0, report.to_json()


def test_malformed_json_and_xml_dtd_preserved_but_not_interpreted(tmp_path):
    data = scenario({"source":"usaspending", "text":'{"results":[],"results":[]}'},
                    fpds('<!DOCTYPE feed [<!ENTITY x SYSTEM "file:///etc/passwd">]><feed/>'))
    result = run(tmp_path / "run", data)
    assert [t["error_code"] for t in result["tasks"]] == ["duplicate_json_key", "forbidden_xml_declaration"]
    assert result["responses_preserved"] == 2
    assert inspect_directory(tmp_path / "run").exit_code == 2


def test_missing_identifiers_and_multiple_award_contexts_reported(tmp_path):
    payload = tx()
    del payload["results"][0]["id"]
    ambiguous = xml().replace('</fpds:awardContractID>', '</fpds:awardContractID><fpds:awardContractID><fpds:PIID>00002</fpds:PIID></fpds:awardContractID>')
    result = run(tmp_path / "run", scenario(usa(payload), fpds(ambiguous)))
    assert result["tasks"][0]["action_context_counts"] == {"missing_action_identifier":1}
    assert result["tasks"][1]["action_context_counts"] == {"ambiguous_award_context":1}
    assert all(t["query_scope"] == "partial" for t in result["tasks"])


def test_plan_only_initialization_recovers_without_overwrite(tmp_path, monkeypatch):
    path = tmp_path / "run"
    replace_json = CollectionStore._replace_json
    def stop(self, name, value):
        if name == "c3_checkpoint.json":
            raise KeyboardInterrupt
        return replace_json(self, name, value)
    monkeypatch.setattr(CollectionStore, "_replace_json", stop)
    with pytest.raises(KeyboardInterrupt):
        run(path, scenario(usa()), sources=("usaspending",))
    before = (path / "c3_plan.json").read_bytes()
    monkeypatch.setattr(CollectionStore, "_replace_json", replace_json)
    result = run(path, scenario(usa()), sources=("usaspending",), resume=True)
    assert result["returned_rows"] == 1 and (path / "c3_plan.json").read_bytes() == before


def test_body_without_metadata_fails_closed_on_resume(tmp_path, monkeypatch):
    path = tmp_path / "run"
    create_json = CollectionStore._create_json
    def stop(self, name, value):
        if name.startswith("c3_attempt_"):
            raise KeyboardInterrupt
        return create_json(self, name, value)
    monkeypatch.setattr(CollectionStore, "_create_json", stop)
    with pytest.raises(KeyboardInterrupt):
        run(path, scenario(usa()), sources=("usaspending",))
    monkeypatch.setattr(CollectionStore, "_create_json", create_json)
    with pytest.raises(EvidenceError, match="incomplete_preserved_observation"):
        run(path, scenario(usa()), sources=("usaspending",), resume=True)
    assert (path / "c3_attempt_000000.body").is_file()


def test_missing_body_and_changed_request_context_invalidate_ingestion(tmp_path):
    path = tmp_path / "run"
    run(path, scenario(usa()), sources=("usaspending",))
    (path / "c3_attempt_000000.body").unlink()
    report = inspect_directory(path)
    assert next(e for e in report.entries if e.relative_path.endswith(".body")).error_code == "missing_file"


def test_checkpoint_corruption_and_linked_summary_are_refused(tmp_path):
    path = tmp_path / "run"
    data = scenario(usa())
    run(path, data, sources=("usaspending",))
    checkpoint = path / "c3_checkpoint.json"
    original = checkpoint.read_bytes()
    value = strict_json(original)
    value["events"][0]["sequence"] = True
    checkpoint.write_text(canonical(value))
    with pytest.raises(EvidenceError, match="invalid_collection_checkpoint"):
        run(path, data, sources=("usaspending",), resume=True)
    checkpoint.write_bytes(original)
    outside = tmp_path / "outside"
    outside.write_text("must remain")
    (path / "c3_summary.json").unlink()
    (path / "c3_summary.json").symlink_to(outside)
    with pytest.raises(EvidenceError):
        run(path, data, sources=("usaspending",), resume=True)
    assert outside.read_text() == "must remain"


def test_parallel_writer_lock_and_immutable_names(tmp_path):
    from src.collection import make_plan
    path = tmp_path / "run"
    plan = make_plan((AWARD,), limits(), ("usaspending",), "fixture:lock")
    with CollectionStore(path, plan) as store:
        with pytest.raises(BlockingIOError):
            with CollectionStore(path, plan, resume=True):
                pass
        with pytest.raises(FileExistsError):
            store._create_json("c3_plan.json", plan)


@pytest.mark.parametrize("change", [{"page_size":101}, {"timeout_seconds":0.0}, {"pace_seconds":float('nan')}, {"max_requests":0}, {"max_awards":101}])
def test_invalid_limits_rejected(change):
    with pytest.raises(ValueError):
        limits(**change)


def test_official_transaction_shape_missing_id_does_not_create_identity():
    request = request_for("usaspending", AWARD.to_dict(), 1, 10)
    payload = tx()
    payload["results"][0]["award_id"] = "DIFFERENT-GENERATED-ID"
    result = parse_page("usaspending", canonical(payload).encode(), request, AWARD.to_dict())
    assert result["contexts"] == ["nonmatching_award_identifier"]


def test_public_static_fixtures_work_through_cli(tmp_path, capsys):
    assert main(["--selection","tests/fixtures/c3_selection.json","--fixture","tests/fixtures/c3_scenario.json",
                 "--run-dir",str(tmp_path / "fixture"),"--retries","0"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["returned_rows"] == 3 and payload["profile"].startswith("fixture:")
    assert payload["tasks"][1]["query_scope"] == "unknown"


def test_newly_written_body_verified_before_journal_commit(tmp_path, monkeypatch):
    create = CollectionStore._create
    def tampered(self, name, raw):
        create(self, name, raw)
        if name.endswith(".body"):
            (self.path / name).write_bytes(b"mutation")
    monkeypatch.setattr(CollectionStore, "_create", tampered)
    with pytest.raises(EvidenceError, match="collection_body_hash_mismatch"):
        run(tmp_path / "run", scenario(usa()), sources=("usaspending",))
    checkpoint = strict_json((tmp_path / "run" / "c3_checkpoint.json").read_bytes())
    assert checkpoint["events"] == [] and checkpoint["pending"] is not None
    assert (tmp_path / "run" / "c3_attempt_000000.json").is_file()


def test_future_clock_on_resume_stops_without_long_wait_or_early_retry(tmp_path, monkeypatch):
    import src.collection as module
    path = tmp_path / "run"
    data = scenario(usa(status=429, retry_after="1"), usa())
    cfg = limits(retries=1)
    with pytest.raises(KeyboardInterrupt):
        collect_selected(path,[AWARD],sources=("usaspending",),limits=cfg,
                         profile="fixture:" + digest(data),transport=FixtureTransport(data),
                         sleep=Mock(side_effect=KeyboardInterrupt))
    class EarlierClock:
        fromisoformat = staticmethod(datetime.fromisoformat)
        @staticmethod
        def now(tz=None):
            return datetime(2024,1,1,tzinfo=timezone.utc)
    monkeypatch.setattr(module, "datetime", EarlierClock)
    transport, sleep = Mock(side_effect=AssertionError("no request")), Mock(side_effect=AssertionError("no long wait"))
    result = collect_selected(path,[AWARD],sources=("usaspending",),limits=cfg,resume=True,
                              profile="fixture:" + digest(data),transport=transport,sleep=sleep)
    assert result["tasks"][0]["error_code"] == "clock_skew_wait_exceeds_bound"
    transport.assert_not_called()
    sleep.assert_not_called()


def test_new_capture_size_budget_applies_to_fixture_transport(tmp_path):
    result = run(tmp_path / "run", scenario(usa()), sources=("usaspending",), limits=limits(max_response_bytes=4))
    assert result["tasks"][0]["error_code"] == "response_size_limit"
    assert (tmp_path / "run" / "c3_attempt_000000.body").read_bytes() == b'{"pa'


def test_global_record_and_award_bounds_apply_across_sources(tmp_path):
    result = run(tmp_path / "run", scenario(usa()), limits=limits(max_records_total=10))
    assert result["requests_reserved"] == 1 and result["record_slots_requested"] == 10
    assert result["tasks"][1]["status"] == "truncated"
    from src.collection import make_plan
    with pytest.raises(EvidenceError, match="selection"):
        make_plan((AWARD, replace(AWARD, generated_id="OTHER")), limits(max_awards=1), ("usaspending",), "fixture:bounds")


def test_malicious_declared_query_cannot_be_used_for_resume(tmp_path):
    path = tmp_path / "run"
    data = scenario(usa())
    run(path,data,sources=("usaspending",))
    metadata_path = path / "c3_attempt_000000.json"
    metadata = strict_json(metadata_path.read_bytes())
    metadata["request"]["endpoint"] = "https://evil.invalid/steal"
    metadata_path.write_text(canonical(metadata))
    checkpoint_path = path / "c3_checkpoint.json"
    checkpoint = strict_json(checkpoint_path.read_bytes())
    checkpoint["events"][0]["metadata_sha256"] = digest(metadata)
    checkpoint_path.write_text(canonical(checkpoint))
    with pytest.raises(EvidenceError, match="invalid_c3_request"):
        run(path,data,sources=("usaspending",),resume=True)
    assert inspect_directory(path).exit_code == 2


def test_incomplete_action_fields_are_retained_with_unresolved_context(tmp_path):
    payload = tx()
    del payload["results"][0]["action_date"]
    result = run(tmp_path / "run", scenario(usa(payload)), sources=("usaspending",))
    task = result["tasks"][0]
    assert task["pagination"] == "complete" and task["query_scope"] == "partial"
    assert task["action_context_counts"] == {"incomplete_transaction_record":1}
    assert strict_json((tmp_path / "run" / "c3_attempt_000000.body").read_bytes()) == payload


def test_unsupported_obligation_type_not_silently_coerced(tmp_path):
    payload = tx()
    payload["results"][0]["federal_action_obligation"] = "-20.00"
    result = run(tmp_path / "run", scenario(usa(payload)), sources=("usaspending",))
    assert result["tasks"][0]["action_context_counts"] == {"unsupported_action_field_type":1}
    assert result["tasks"][0]["query_scope"] == "partial"
