"""Actual saved C3 bytes, C4 revalidation, secure C5 output; strictly offline."""
from unittest.mock import Mock

import pytest

from src.evidence import ComparisonStatus as S, Completeness
from src.evidence_io import EvidenceError, canonical, strict_json
from src.financial_ingestion import reconcile_collection
from src.financial_models import FPDS_ACTION
from src.match_evidence import main as match_main
from src.matching_ingestion import match_collection
from src.reconcile_evidence import main
from tests.financial_fixtures import financial_scenario
from tests.test_matching_ingestion import collection, snapshot


def test_exact_source_tokens_and_signed_date_not_effective_date(tmp_path, monkeypatch):
    import requests
    path = collection(tmp_path, financial_scenario("1.2300e+2", "00123.00"))
    before = snapshot(path)
    monkeypatch.setattr(requests.Session, "request", Mock(side_effect=AssertionError("no network")))
    report = reconcile_collection(path)
    assert report.results[0].status is S.VERIFIED_MATCH
    values = {o.source: o for o in report.observations}
    assert values["usaspending"].value.raw_text == "1.2300e+2"
    assert values["fpds"].value.raw_text == "00123.00"
    assert all(o.action_date == "2025-01-01" for o in values.values())
    assert snapshot(path) == before


@pytest.mark.parametrize("left,right,status,diff", [("-20.00", "-20", S.VERIFIED_MATCH, "0"), ("0.00", "0", S.VERIFIED_MATCH, "0"),
    ("100.01", "100.00", S.INSUFFICIENT_EVIDENCE, "0.01"),
    ("9007199254740992.01", "9007199254740992.00", S.INSUFFICIENT_EVIDENCE, "0.01")])
def test_exact_decimals_from_real_saved_formats(tmp_path, left, right, status, diff):
    report = reconcile_collection(collection(tmp_path, financial_scenario(left, right)))
    assert report.results[0].status is status
    assert report.results[0].difference_usa_minus_fpds == diff


def test_c4_float_content_collision_cannot_hide_two_different_source_values(tmp_path):
    data = financial_scenario("9007199254740992.00", "9007199254740992.00")
    # Two source JSON rows differ by one cent, beyond binary float precision.
    usa = data["responses"][0]["text"]
    first = usa[usa.index('"results":[') + len('"results":['):-2]
    # Build the second row by literal substitution, never through parsed money.
    data["responses"][0]["text"] = usa[:-2] + "," + first.replace("9007199254740992.00", "9007199254740992.01") + "]}"
    path = collection(tmp_path, data)
    identity = match_collection(path)
    assert len([r for r in identity.records if r.source == "usaspending"]) == 1
    report = reconcile_collection(path)
    result = report.results[0]
    assert result.status is S.INSUFFICIENT_EVIDENCE and result.difference_usa_minus_fpds is None
    assert "conflicting_values_across_retained_occurrences" in result.reasons
    assert len(result.left_observation_ids) == 2


def test_cumulative_correct_path_inventories_but_legacy_alias_not_compared(tmp_path):
    data = financial_scenario()
    xml = data["responses"][1]["text"]
    xml = xml.replace("</f:award>", "<f:totalDollarValues><f:obligatedAmount>999.00</f:obligatedAmount><f:totalObligatedAmount>777.00</f:totalObligatedAmount><f:totalBaseAndAllOptionsValue>1000.00</f:totalBaseAndAllOptionsValue></f:totalDollarValues></f:award>")
    data["responses"][1]["text"] = xml
    report = reconcile_collection(collection(tmp_path, data))
    assert report.results[0].status is S.VERIFIED_MATCH
    values = {o.original_field: o for o in report.observations}
    assert values["totalDollarValues/obligatedAmount"].semantics.documented
    assert not values["totalDollarValues/totalObligatedAmount"].semantics.documented
    assert report.results[0].right_observation_ids == (values[FPDS_ACTION].financial_observation_id,)


def test_missing_signed_date_does_not_fall_back_to_effective_date(tmp_path):
    report = reconcile_collection(collection(tmp_path, financial_scenario(signed=None, effective="2025-01-01")))
    assert report.results[0].status is S.INSUFFICIENT_EVIDENCE
    assert report.results[0].difference_usa_minus_fpds is None


def test_missing_action_obligation_does_not_substitute_cumulative(tmp_path):
    data = financial_scenario()
    data["responses"][1]["text"] = data["responses"][1]["text"].replace("<f:dollarValues>", "<f:totalDollarValues>").replace("</f:dollarValues>", "</f:totalDollarValues>")
    report = reconcile_collection(collection(tmp_path, data))
    assert report.results[0].status is S.INSUFFICIENT_EVIDENCE
    assert report.results[0].difference_usa_minus_fpds is None


def test_incomplete_history_and_pagination_never_becomes_complete(tmp_path):
    from tests.test_collection_c3 import limits
    report = reconcile_collection(collection(tmp_path, financial_scenario(more=True), limits=limits(max_pages=1)))
    assert report.results[0].status is S.VERIFIED_MATCH
    assert any(c.pagination is Completeness.PARTIAL for c in report.identity_run.coverage)
    assert all(c.transaction_history is Completeness.UNKNOWN for c in report.identity_run.coverage)


def test_stale_retrieval_time_not_proof_of_refresh_alignment(tmp_path):
    data = financial_scenario("100.01", "100.00")
    data["responses"][0]["retrieved_at_utc"] = "2020-01-01T00:00:00Z"
    data["responses"][1]["retrieved_at_utc"] = "2026-10-27T00:00:00Z"
    report = reconcile_collection(collection(tmp_path, data))
    assert report.results[0].status is S.INSUFFICIENT_EVIDENCE
    assert all(c.freshness is Completeness.UNKNOWN for c in report.identity_run.coverage)


def test_retrieval_duplicates_not_summed(tmp_path):
    data = financial_scenario("10.00", "10.00")
    text = data["responses"][0]["text"]
    first = text[text.index('"results":[') + len('"results":['):-2]
    data["responses"][0]["text"] = text[:-2] + "," + first + "]}"
    report = reconcile_collection(collection(tmp_path, data))
    result = report.results[0]
    assert result.left_normalized == result.right_normalized == "10"
    assert len(result.left_observation_ids) == 2 and result.status is S.VERIFIED_MATCH


@pytest.mark.parametrize("mutation", ["amount", "signed_date", "container", "foreign", "nested"])
def test_ambiguous_financial_xml_never_uses_first_value(tmp_path, mutation):
    data = financial_scenario()
    xml = data["responses"][1]["text"]
    if mutation == "amount":
        xml = xml.replace("</f:obligatedAmount>", "</f:obligatedAmount><f:obligatedAmount>101</f:obligatedAmount>")
    elif mutation == "signed_date":
        xml = xml.replace("</f:signedDate>", "</f:signedDate><f:signedDate>2025-01-02</f:signedDate>")
    elif mutation == "container":
        xml = xml.replace("</f:dollarValues>", "</f:dollarValues><f:dollarValues/>")
    elif mutation == "foreign":
        xml = xml.replace("<f:obligatedAmount>", '<x:obligatedAmount xmlns:x="https://example.invalid">').replace("</f:obligatedAmount>", "</x:obligatedAmount>")
    else:
        xml = xml.replace("100.00</f:obligatedAmount>", "100<f:unit>EUR</f:unit></f:obligatedAmount>")
    data["responses"][1]["text"] = xml
    path = collection(tmp_path, data)
    before = snapshot(path)
    with pytest.raises(EvidenceError):
        reconcile_collection(path)
    assert snapshot(path) == before


@pytest.mark.parametrize("attribute", [' currency="EUR"', ' currencyCode="EUR"', ' currency=""'])
def test_unsupported_currency_metadata_not_ignored(tmp_path, attribute):
    data = financial_scenario()
    data["responses"][1]["text"] = data["responses"][1]["text"].replace("<f:obligatedAmount>", "<f:obligatedAmount" + attribute + ">")
    report = reconcile_collection(collection(tmp_path, data))
    assert report.results[0].status is S.INSUFFICIENT_EVIDENCE


def test_previously_saved_identity_report_revalidated(tmp_path, capsys):
    path = collection(tmp_path, financial_scenario())
    prior = tmp_path / "identity.json"
    assert match_main(["--root", str(path), "--output", str(prior)]) == 0
    report = reconcile_collection(path, identity_report_path=prior)
    assert report.results[0].status is S.VERIFIED_MATCH
    assert report.to_json() == reconcile_collection(path).to_json()


def test_stale_identity_report_rejected_even_if_own_schema_valid(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    old = collection(first, financial_scenario("100.00", "100.00"))
    new = collection(second, financial_scenario("100.01", "100.00"))
    prior = tmp_path / "identity.json"
    prior.write_text(match_collection(old).to_json())
    with pytest.raises(EvidenceError, match="stale_or_conflicting_identity_report"):
        reconcile_collection(new, identity_report_path=prior)


def test_identity_report_forged_status_or_wrapper_rejected(tmp_path, capsys):
    path = collection(tmp_path, financial_scenario())
    prior = tmp_path / "identity.json"
    match_main(["--root", str(path), "--output", str(prior)])
    doc = strict_json(prior.read_bytes())
    doc["exit_code"] = False  # Python False == 0 must not bypass wrapper checks.
    prior.write_text(canonical(doc))
    with pytest.raises(EvidenceError, match="invalid_identity_report_wrapper"):
        reconcile_collection(path, identity_report_path=prior)


@pytest.mark.parametrize("name", ["c3_attempt_000000.body", "c3_attempt_000001.json", "c3_checkpoint.json"])
def test_tampered_source_evidence_never_compared(tmp_path, name):
    path = collection(tmp_path, financial_scenario())
    (path / name).write_bytes(b"{}")
    with pytest.raises(EvidenceError):
        reconcile_collection(path)


def test_changes_during_financial_processing_fail_final_check(tmp_path, monkeypatch):
    import src.financial_ingestion as module
    path = collection(tmp_path, financial_scenario())
    original = module.reconcile_observations
    def mutate(*args, **kw):
        report = original(*args, **kw)
        (path / "c3_attempt_000000.body").write_bytes(b"changed")
        return report
    monkeypatch.setattr(module, "reconcile_observations", mutate)
    with pytest.raises(EvidenceError, match="financial_evidence_changed"):
        reconcile_collection(path)


def test_cli_determinism_timestamps_and_output_safety(tmp_path, capsys):
    path = collection(tmp_path, financial_scenario())
    before = snapshot(path)
    assert main(["--root", str(path)]) == 0
    out = capsys.readouterr()
    regular = strict_json(out.out.encode())
    assert "misconduct inference" in out.err
    assert main(["--root", str(path), "--execution-time"]) == 0
    timed = strict_json(capsys.readouterr().out.encode())
    assert timed["substantive_sha256"] == regular["substantive_sha256"]
    assert main(["--root", str(path), "--output", str(path / "forbidden.json")]) == 2
    output = tmp_path / "report.json"
    assert main(["--root", str(path), "--output", str(output)]) == 0
    assert main(["--root", str(path), "--output", str(output)]) == 2
    assert snapshot(path) == before


def test_cli_limits_and_interruptions(tmp_path, monkeypatch):
    import src.reconcile_evidence as module
    path = collection(tmp_path, financial_scenario())
    assert main(["--root", str(path), "--max-observations", "1"]) == 2
    assert main(["--root", str(path), "--max-comparison-work", "1"]) == 2
    monkeypatch.setattr(module, "reconcile_collection", Mock(side_effect=KeyboardInterrupt))
    assert main(["--root", str(path)]) == 130


def test_linked_identity_report_or_source_root_rejected(tmp_path):
    path = collection(tmp_path, financial_scenario())
    prior = tmp_path / "identity.json"
    prior.write_text(match_collection(path).to_json())
    link = tmp_path / "identity-link.json"
    link.symlink_to(prior)
    with pytest.raises(EvidenceError):
        reconcile_collection(path, identity_report_path=link)
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(path, target_is_directory=True)
    with pytest.raises(EvidenceError):
        reconcile_collection(linked_root)


def test_currency_child_extension_cannot_silently_become_usd(tmp_path):
    data = financial_scenario()
    data["responses"][1]["text"] = data["responses"][1]["text"].replace("</f:dollarValues>", "<f:currencyCode>EUR</f:currencyCode></f:dollarValues>")
    result = reconcile_collection(collection(tmp_path, data)).results[0]
    assert result.status is S.INSUFFICIENT_EVIDENCE and result.difference_usa_minus_fpds is None


def test_repeated_observations_preserved_not_double_counted(tmp_path):
    data = financial_scenario("10.00", "10.00")
    first = data["responses"][0]
    second = {**first, "text": first["text"].replace('"page":1', '"page":2'), "retrieved_at_utc": "2025-01-02T00:00:00Z"}
    first["text"] = first["text"].replace('"hasNext":false', '"hasNext":true')
    data["responses"].insert(1, second)
    report = reconcile_collection(collection(tmp_path, data))
    assert report.results[0].status is S.VERIFIED_MATCH
    assert report.results[0].left_normalized == "10" and len(report.results[0].left_observation_ids) == 2


def test_empty_feed_and_unavailable_api_keep_uncertainty(tmp_path):
    data = financial_scenario()
    data["responses"][1]["text"] = '<feed xmlns="http://www.w3.org/2005/Atom"/>'
    report = reconcile_collection(collection(tmp_path, data))
    assert report.results[0].status is S.INSUFFICIENT_EVIDENCE
    assert report.identity_run.excluded_artifacts


def test_changes_between_c4_and_financial_scan_rejected(tmp_path, monkeypatch):
    import src.financial_ingestion as module
    path = collection(tmp_path, financial_scenario())
    original = module.match_collection
    def mutate(*args, **kw):
        result = original(*args, **kw)
        (path / "c3_attempt_000000.body").write_text("changed")
        return result
    monkeypatch.setattr(module, "match_collection", mutate)
    with pytest.raises(EvidenceError, match="financial_evidence_changed"):
        reconcile_collection(path)


def test_authored_c5_fixture_command(tmp_path, capsys):
    from src.collect_evidence import main as collect_main
    path = tmp_path / "static"
    assert collect_main(["--selection", "tests/fixtures/c4_selection.json", "--fixture", "tests/fixtures/c5_scenario.json",
                         "--run-dir", str(path), "--retries", "0"]) == 1
    capsys.readouterr()
    assert main(["--root", str(path)]) == 0
    wire = strict_json(capsys.readouterr().out.encode())
    assert wire["counts"]["verified_match"] == 1
    usa = next(o for o in wire["report"]["observations"] if o["source"] == "usaspending")
    assert usa["value"]["raw_text"] == "100.0100"


def test_multiple_modifications_remain_individual_obligations_not_award_total(tmp_path):
    from tests.matching_fixtures import entry, fpds_row, scenario, usa_row
    rows = [usa_row(mod="P00001", federal_action_obligation=-20), usa_row(mod="P00002", federal_action_obligation=0)]
    data = scenario(rows)
    entries = []
    for mod, amount in (("P00001", "-20.00"), ("P00002", "0.00")):
        text = entry(fpds_row(mod=mod))
        text = text.replace("</f:award>", "<f:dollarValues><f:obligatedAmount>" + amount + "</f:obligatedAmount></f:dollarValues><f:relevantContractDates><f:signedDate>2025-01-01</f:signedDate></f:relevantContractDates></f:award>")
        entries.append(text)
    data["responses"][1]["text"] = '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:f="https://www.fpds.gov/FPDS">' + "".join(entries) + "</feed>"
    report = reconcile_collection(collection(tmp_path, data))
    assert len(report.results) == 2 and all(r.status is S.VERIFIED_MATCH for r in report.results)
    assert {r.left_normalized for r in report.results} == {"-20", "0"}
    assert all(c.transaction_history is Completeness.UNKNOWN for c in report.identity_run.coverage)
