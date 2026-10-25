"""Offline retrieval contracts: fixtures are synthetic, never production fallbacks."""
import json
from unittest.mock import Mock

import pytest

from src.federal_spending_auditor import USAspendingClient, clean_awards, run_pipeline
from src.sampling import allocate, collect, make_strata


def award(identity, **kw):
    return {"generated_internal_id": identity, "Award ID": "SHARED-PIID", **kw}


def body(rows=(), more=False, **kw):
    return {"results": list(rows), "page_metadata": {"hasNext": more, **kw}}


def client(*responses):
    c = USAspendingClient(page_delay_seconds=0)
    c._post = Mock(side_effect=responses)
    return c


def fetch(c, root=None, **kw):
    return collect(c, raw_dir=root, max_records=kw.pop("max_records", 4),
                   page_size=kw.pop("page_size", 2), period=kw.pop("period", "year"), **kw)


def test_allocation_and_calendar():
    assert allocate(19, 16) == [2, 2, 2] + [1] * 13
    assert allocate(2, 4) == [1, 1, 0, 0]
    strata = make_strata(2024, "month", ("B", "A", "B"))
    assert len(strata) == 24
    assert strata[8]["filters"]["time_period"][0] == {"start_date": "2024-02-01", "end_date": "2024-02-29"}
    assert make_strata(2025)[-1]["filters"]["time_period"][0]["end_date"] == "2025-09-30"


@pytest.mark.parametrize("types", [(), ("E",)])
def test_bad_categories(types):
    with pytest.raises(ValueError):
        make_strata(2025, award_types=types)


def test_small_empty_and_reallocation(tmp_path):
    c = client(body(), body([award("b1"), award("b2")], True),
               body([award("c1")]), body(), body([award("b3")]))
    result = fetch(c, tmp_path)
    assert [r["generated_internal_id"] for r in result] == ["b1", "c1", "b2", "b3"]
    assert [s["collected"] for s in c.last_sampling_summary["strata"]] == [0, 3, 1, 0]
    assert c.last_sampling_summary["target_met"]
    assert all(call.args[0]["limit"] == 2 for call in c._post.call_args_list)
    before = c._post.call_count
    assert fetch(c, tmp_path) == result
    assert c._post.call_count == before


def test_overlap_missing_identifiers_and_shared_piids(tmp_path):
    c = client(body([award("a"), award(None)]), body([award("a"), award("b")]),
               body([award("c")]), body([award("d")]))
    result = fetch(c, tmp_path)
    assert len(result) == 4
    assert len({r["Award ID"] for r in result}) == 1
    assert sum(s["duplicates"] for s in c.last_sampling_summary["strata"]) == 1
    assert sum(s["missing_identifiers"] for s in c.last_sampling_summary["strata"]) == 1
    assert json.loads((tmp_path / "response_000000.json").read_text())["response"]["results"][1]["generated_internal_id"] is None


def test_interrupted_resume_equals_uninterrupted(tmp_path):
    pages = [body([award("a"), award("b")], True), body([award("c")]), body([award("d")])]
    c = client(pages[0], RuntimeError("interrupted"))
    with pytest.raises(RuntimeError):
        fetch(c, tmp_path, max_records=4, award_types=("A", "B"))
    summary = json.loads((tmp_path / "sampling_coverage.json").read_text())
    assert not summary["complete"] and summary["collected"] == 2
    resumed = client(*pages[1:])
    actual = fetch(resumed, tmp_path, max_records=4, award_types=("A", "B"))
    expected = fetch(client(*pages), max_records=4, award_types=("A", "B"))
    assert actual == expected
    assert resumed._post.call_count == 2


def test_orphan_response_adopted_without_refetch(tmp_path):
    c = client(body([award("a")]))
    fetch(c, tmp_path, max_records=1, award_types=("A",))
    path = tmp_path / "checkpoint.json"
    cp = json.loads(path.read_text()); cp["events"] = []; cp["complete"] = False
    path.write_text(json.dumps(cp))
    resumed = client()
    assert len(fetch(resumed, tmp_path, max_records=1, award_types=("A",))) == 1
    resumed._post.assert_not_called()


@pytest.mark.parametrize("change", ["page_size", "period", "max_records", "award_types"])
def test_fingerprint_rejects_changed_config_without_overwriting(tmp_path, change):
    fetch(client(body([award("a")])), tmp_path, max_records=1)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    options = {"max_records": 1, change: {"page_size": 1, "period": "quarter", "max_records": 2, "award_types": ("A",)}[change]}
    with pytest.raises(ValueError, match="query differs"):
        fetch(client(), tmp_path, **options)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize("damage", ["raw", "missing", "order", "complete"])
def test_corruption_is_rejected(tmp_path, damage):
    fetch(client(body([award("a")])), tmp_path, max_records=1)
    path = tmp_path / "checkpoint.json"; cp = json.loads(path.read_text())
    raw = tmp_path / "response_000000.json"
    if damage == "raw":
        raw.write_text('{}')
    elif damage == "missing":
        raw.unlink()
    elif damage == "order":
        cp["events"][0]["step"] = 8
    else:
        cp["complete"] = "true"
    path.write_text(json.dumps(cp))
    with pytest.raises(ValueError):
        fetch(client(), tmp_path, max_records=1)


@pytest.mark.parametrize("bad", [body([], True), {"results": []}, body(["not a row"]),
                                      body([], page=2), body([], hasNext="yes")])
def test_bad_pagination_retains_raw_and_marks_incomplete(tmp_path, bad):
    c = client(bad)
    with pytest.raises(ValueError):
        fetch(c, tmp_path)
    assert (tmp_path / "response_000000.json").exists()
    assert c.last_sampling_summary["complete"] is False


def test_repeated_pages_fail_explicitly(tmp_path):
    page = body([award("a")], True)
    with pytest.raises(ValueError, match="Repeated page"):
        fetch(client(page, page), tmp_path, max_records=3, award_types=("A",))
    assert (tmp_path / "response_000001.json").exists()


def test_exhaustion_is_complete_but_not_target_met(tmp_path):
    c = client(*[body() for _ in range(4)])
    assert fetch(c, tmp_path) == []
    assert c.last_sampling_summary["complete"]
    assert not c.last_sampling_summary["target_met"]
    assert c.last_sampling_summary["population_total"] is None


def test_documented_field_aliases_cleaned():
    result = clean_awards([{"Recipient DUNS Number": "d", "NAICS": "11", "PSC": "p"}])[0]
    assert (result["recipient_duns"], result["naics_code"], result["psc_code"]) == ("d", "11", "p")


def test_legacy_pipeline_still_uses_old_fetch(tmp_path):
    c = USAspendingClient()
    c.fetch_contract_awards = Mock(return_value=[])
    fpds = Mock()
    result = run_pipeline(root=tmp_path, client=c, fpds_client=fpds, sampling_mode="legacy")
    c.fetch_contract_awards.assert_called_once()
    assert result["records"] == 0
    assert "sampling_coverage_path" not in result


def test_page_limit_is_explicit_and_resumable(tmp_path):
    c = client(body([award(None)], True))
    with pytest.raises(ValueError, match="safety limit"):
        fetch(c, tmp_path, award_types=("A",), max_pages_per_stratum=1)
    assert c.last_sampling_summary["complete"] is False
    assert c.last_sampling_summary["collected"] == 0
    assert c.last_sampling_summary["strata"][0]["missing_identifiers"] == 1


def test_fixed_page_size_avoids_offset_gaps_and_buffers_replay(tmp_path):
    c = client(body([award("a"), award("b")], True), body([award("c"), award("d")]))
    result = fetch(c, tmp_path, max_records=3, award_types=("A",))
    assert [r["generated_internal_id"] for r in result] == ["a", "b", "c"]
    assert [call.args[0]["limit"] for call in c._post.call_args_list] == [2, 2]
    assert c.last_sampling_summary["strata"][0]["truncated"]
    assert fetch(client(), tmp_path, max_records=3, award_types=("A",)) == result


def test_zero_quota_strata_are_explicitly_unqueried(tmp_path):
    c = client(body([award("a")], True))
    fetch(c, tmp_path, max_records=1)
    assert c._post.call_count == 1
    assert [s["initial_quota"] for s in c.last_sampling_summary["strata"]] == [1, 0, 0, 0]
    assert all(s["truncated"] for s in c.last_sampling_summary["strata"])


def test_bad_query_metadata_is_not_overwritten(tmp_path):
    fetch(client(body([award("a")])), tmp_path, max_records=1)
    p = tmp_path / "query_metadata.json"
    p.write_text('{}')
    with pytest.raises(ValueError, match="metadata is corrupt"):
        fetch(client(), tmp_path, max_records=1)
    assert p.read_text() == '{}'


def test_nonempty_uncheckpointed_directory_rejected(tmp_path):
    (tmp_path / "evidence.json").write_text('{}')
    with pytest.raises(ValueError, match="no checkpoint"):
        fetch(client(), tmp_path)


def test_resume_missing_directory_does_not_start_new_run(tmp_path):
    with pytest.raises(ValueError, match="existing checkpoint"):
        run_pipeline(root=tmp_path, resume_run_dir=tmp_path / "missing")
    assert not (tmp_path / "missing").exists()


def test_pipeline_stratified_report_and_legacy_outputs(tmp_path):
    c = client(body([award("a", **{"Award Amount": 100, "Awarding Agency": "Example"})]))
    fpds = Mock()
    result = run_pipeline(root=tmp_path, client=c, fpds_client=fpds, max_records=1,
                          lifecycle_award_limit=0, reconciliation_sample_size=0)
    assert result["records"] == 1
    assert result["sampling_coverage_path"].is_file()
    assert "population total: unknown" in result["sampling_coverage_path"].read_text()
    assert result["cleaned_path"].is_file()
    assert "stratified" in result["report_path"].read_text()
    metadata = json.loads(result["run_metadata_path"].read_text())
    assert metadata["sampling_mode"] == "stratified"
    assert (result["raw_dir"] / metadata["sampling_coverage"]).is_file()
