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


def test_contract_fields_and_structured_codes_reach_analysis():
    from src.analysis import missingness_summary, _procurement_category
    c = client(body([award('contract', **{
        'Contract Award Type': 'DEFINITIVE CONTRACT',
        'NAICS': {'code': '541330', 'description': 'Engineering Services'},
        'PSC': {'code': 'R425', 'description': 'Engineering'},
        'Last Modified Date': '2026-10-01',
    })]))
    rows = fetch(c, max_records=1)
    fields = c._post.call_args.args[0]['fields']
    assert 'Contract Award Type' in fields and 'Award Type' not in fields
    assert {'generated_internal_id', 'Last Modified Date'} <= set(fields)
    cleaned = clean_awards(rows)[0]
    assert cleaned['award_type'] == 'DEFINITIVE CONTRACT'
    assert cleaned['naics_code'] == '541330'
    assert cleaned['psc_code'] == 'R425'
    assert _procurement_category(cleaned) == 'NAICS 54xx'
    null_codes = clean_awards([{'NAICS': {'code': None, 'description': 'Unknown'}, 'PSC': {'code': None}}])
    missing = {r['field']: r['missing_count'] for r in missingness_summary(null_codes)}
    assert missing['naics_code'] == missing['psc_code'] == 1


def test_complete_checkpoint_cannot_adopt_orphan_or_ignore_extra_evidence(tmp_path):
    fetch(client(body([award('a')])), tmp_path, max_records=1)
    # A completed run cannot legitimately have an uncommitted next page.
    (tmp_path / 'response_000001.json').write_text((tmp_path / 'response_000000.json').read_text())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='Unexpected raw evidence'):
        fetch(client(), tmp_path, max_records=1)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_truncated_complete_journal_cannot_re_adopt_saved_page(tmp_path):
    fetch(client(body([award('a')])), tmp_path, max_records=1)
    path = tmp_path / 'checkpoint.json'
    cp = json.loads(path.read_text()); cp['events'] = []
    path.write_text(json.dumps(cp))
    with pytest.raises(ValueError, match='Unexpected raw evidence'):
        fetch(client(), tmp_path, max_records=1)


def test_interrupted_initialization_resumes_matching_query_plan(tmp_path):
    c = client(body([award('a')]))
    original = c._write_json_atomic
    def stop_before_checkpoint(path, value):
        if path.name == 'checkpoint.json':
            raise KeyboardInterrupt()
        original(path, value)
    c._write_json_atomic = stop_before_checkpoint
    with pytest.raises(KeyboardInterrupt):
        fetch(c, tmp_path, max_records=1)
    assert (tmp_path / 'query_metadata.json').exists()
    assert not (tmp_path / 'checkpoint.json').exists()
    resumed = client(body([award('a')]))
    assert len(fetch(resumed, tmp_path, max_records=1)) == 1


def test_keyboard_interrupt_records_partial_coverage_and_resumes(tmp_path):
    c = client(body([award('a')], True), KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        fetch(c, tmp_path, max_records=2, award_types=('A',))
    summary = json.loads((tmp_path / 'sampling_coverage.json').read_text())
    assert summary['error'] == 'KeyboardInterrupt' and not summary['complete']
    assert summary['collected'] == 1
    assert summary['failed_request']['page'] == 2
    resumed = client(body([award('b')]))
    assert len(fetch(resumed, tmp_path, max_records=2, award_types=('A',))) == 2


def test_overlap_across_fiscal_periods_redistributes_and_replays(tmp_path):
    pages = [body([award('shared', **{'Award Amount': 1}), award('q1')]),
             body([award('shared', **{'Award Amount': 2}), award('q2')]),
             body(), body([award('q4')])]
    c = client(*pages)
    rows = fetch(c, tmp_path, period='quarter', award_types=('A',))
    assert [r['generated_internal_id'] for r in rows] == ['shared', 'q2', 'q4', 'q1']
    assert rows[0]['Award Amount'] == 1
    states = c.last_sampling_summary['strata']
    assert [s['collected'] for s in states] == [2, 1, 0, 1]
    assert states[1]['duplicates'] == 1
    assert len({call.args[0]['filters']['time_period'][0]['start_date'] for call in c._post.call_args_list}) == 4
    resumed = client()
    assert fetch(resumed, tmp_path, period='quarter', award_types=('A',)) == rows
    resumed._post.assert_not_called()


@pytest.mark.parametrize('complete', [True, False])
def test_wrong_mode_resume_preserves_stratified_evidence(tmp_path, complete):
    fetch(client(body([award('a')])), tmp_path, max_records=1)
    if not complete:
        # Metadata-only initialization is also protected from legacy overwrite.
        for path in tmp_path.iterdir():
            if path.name != 'query_metadata.json':
                path.unlink()
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='query differs'):
        USAspendingClient().fetch_contract_awards(max_records=1, raw_dir=tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_changed_legacy_query_preserves_metadata(tmp_path):
    from tests.test_collection import FakeResponse
    c = USAspendingClient(session=Mock(), page_delay_seconds=0)
    c.session.post.return_value = FakeResponse(body([award('a')]))
    c.fetch_contract_awards(max_records=1, raw_dir=tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match='query differs'):
        c.fetch_contract_awards(max_records=2, raw_dir=tmp_path)
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize('envelope', [[], {'request': {}, 'response': [], 'retrieved_at_utc': '2026-10-25'},
                                      {'request': {}, 'response': body()}])
def test_malformed_orphan_envelopes_fail_explicitly_without_overwrite(tmp_path, envelope):
    c = client(RuntimeError('interrupt before response'))
    with pytest.raises(RuntimeError):
        fetch(c, tmp_path, max_records=1)
    path = tmp_path / 'response_000000.json'
    path.write_text(json.dumps(envelope))
    before = path.read_bytes()
    resumed = client()
    with pytest.raises(ValueError, match='Corrupt response envelope'):
        fetch(resumed, tmp_path, max_records=1)
    assert path.read_bytes() == before
    resumed._post.assert_not_called()


def test_metadata_only_wrong_plan_is_rejected(tmp_path):
    fetch(client(body([award('a')])), tmp_path, max_records=1)
    for path in tmp_path.iterdir():
        if path.name != 'query_metadata.json':
            path.unlink()
    before = (tmp_path / 'query_metadata.json').read_bytes()
    with pytest.raises(ValueError, match='incompatible'):
        fetch(client(), tmp_path, max_records=2)
    assert (tmp_path / 'query_metadata.json').read_bytes() == before
    assert not (tmp_path / 'checkpoint.json').exists()


def test_contract_request_fields_match_documented_contract_and_source():
    # Official spending_by_award.md base + Contracts fields and source mapping.
    supported = {'Award ID', 'Recipient Name', 'Recipient UEI', 'Recipient DUNS Number',
                 'Start Date', 'End Date', 'Award Amount', 'Awarding Agency',
                 'Awarding Agency Code', 'Awarding Sub Agency', 'Awarding Sub Agency Code',
                 'NAICS', 'PSC', 'Contract Award Type', 'generated_internal_id', 'Last Modified Date'}
    c = client(body([award('a', **{'Last Modified Date': '2026-10-01'})]))
    fetch(c, max_records=1)
    request = c._post.call_args.args[0]
    assert set(request['fields']) == supported
    assert request['filters'] == {'time_period': [{'start_date': '2024-10-01', 'end_date': '2025-09-30'}], 'award_type_codes': ['A']}
    assert c.last_sampling_summary['strata'][0]['pages'][0]['source_last_modified_values'] == ['2026-10-01']


@pytest.mark.parametrize('status', [429, 500, 503])
def test_retry_real_requests_error_responses(status):
    import requests
    error_response = requests.Response()
    error_response.status_code = status
    error_response._content = b'{}'
    success = requests.Response()
    success.status_code = 200
    success._content = b'{"results": []}'
    session = Mock()
    session.post.side_effect = [error_response, success]
    c = USAspendingClient(session=session, retries=1, backoff_seconds=0)
    assert c._post({'page': 1}) == {'results': []}
    assert session.post.call_count == 2


def test_pipeline_recovers_initialized_plan_without_checkpoint(tmp_path):
    raw_dir = tmp_path / 'raw'
    c = client(body([award('a')]))
    original = c._write_json_atomic
    def stop(path, value):
        if path.name == 'checkpoint.json':
            raise KeyboardInterrupt()
        original(path, value)
    c._write_json_atomic = stop
    with pytest.raises(KeyboardInterrupt):
        collect(c, max_records=1, raw_dir=raw_dir)
    result = run_pipeline(root=tmp_path, resume_run_dir=raw_dir, max_records=1,
                          client=client(body([award('a')])), fpds_client=Mock(), page_delay_seconds=0,
                          lifecycle_award_limit=0, reconciliation_sample_size=0)
    assert result['records'] == 1
