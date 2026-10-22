import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from src.federal_spending_auditor import (
    API_URL,
    USAspendingClient,
    clean_awards,
    flag_awards,
    run_pipeline,
)


def api_record(
    award_id="W91ABC-25-C-0001",
    generated_id="CONT_AWD_W91ABC-25-C-0001_9700_NONE_NONE",
    amount=2500,
    internal_id=101,
    recipient_uei="TESTUEI00001",
):
    return {
        "internal_id": internal_id,
        "Award ID": award_id,
        "Recipient Name": "Example Supplier",
        "Recipient UEI": recipient_uei,
        "Recipient DUNS": None,
        "Start Date": "2024-10-01",
        "End Date": "2025-09-30",
        "Award Amount": amount,
        "Awarding Agency": "Department of Defense",
        "Awarding Sub Agency": "Example Agency",
        "Award Type": None,
        "generated_internal_id": generated_id,
    }


class FakeResponse:
    def __init__(self, body, status_code=200):
        self.body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self.body


def test_fetches_pages_and_saves_raw_responses(tmp_path):
    session = Mock()
    session.post.side_effect = [
        FakeResponse(
            {"results": [api_record()], "page_metadata": {"hasNext": True}}
        ),
        FakeResponse(
            {"results": [api_record(award_id="W91ABC-25-C-0002")], "page_metadata": {"hasNext": False}}
        ),
    ]
    raw_dir = tmp_path / "raw"
    client = USAspendingClient(session=session, backoff_seconds=0)

    records = client.fetch_contract_awards(max_records=2, page_size=1, raw_dir=raw_dir)

    assert len(records) == 2
    assert session.post.call_count == 2
    first_call = session.post.call_args_list[0]
    second_call = session.post.call_args_list[1]
    assert first_call.args[0] == API_URL
    assert first_call.kwargs["json"]["page"] == 1
    assert second_call.kwargs["json"]["page"] == 2
    assert first_call.kwargs["json"]["filters"]["time_period"] == [
        {"start_date": "2024-10-01", "end_date": "2025-09-30"}
    ]
    assert (raw_dir / "page_0001.json").is_file()
    assert json.loads((raw_dir / "page_0002.json").read_text(encoding="utf-8"))["results"]


def test_retries_timeout_then_succeeds(monkeypatch):
    session = Mock()
    session.post.side_effect = [requests.Timeout("slow"), FakeResponse({"results": []})]
    sleep = Mock()
    monkeypatch.setattr("src.federal_spending_auditor.time.sleep", sleep)
    client = USAspendingClient(session=session, retries=1, backoff_seconds=0.1)

    body = client._post({"page": 1})

    assert body == {"results": []}
    assert session.post.call_count == 2
    sleep.assert_called_once_with(0.1)


def test_flags_large_missing_and_exact_duplicates_but_not_shared_award_id():
    raw_records = [
        api_record(award_id="LARGE", amount=1_200_000_000),
        api_record(
            award_id=None,
            generated_id=None,
            recipient_uei=None,
            internal_id=102,
        ),
        api_record(award_id="DUP", generated_id="DUP-ID", internal_id=103),
        api_record(award_id="DUP", generated_id="DUP-ID", internal_id=104),
        api_record(award_id="MOD", generated_id="MOD-A", amount=100, internal_id=105),
        api_record(award_id="MOD", generated_id="MOD-B", amount=200, internal_id=106),
    ]

    flagged = flag_awards(clean_awards(raw_records), amount_threshold=1_000_000_000)
    reasons_by_id = {row["internal_id"]: row["flag_reasons"] for row in flagged}

    assert "screening threshold" in reasons_by_id[101]
    assert "Award ID is missing" in reasons_by_id[102]
    assert "Generated award identifier is missing" in reasons_by_id[102]
    assert "Recipient UEI and DUNS are both missing" in reasons_by_id[102]
    assert "Exact award-record signature repeats" in reasons_by_id[104]
    assert 105 not in reasons_by_id
    assert 106 not in reasons_by_id


def test_pipeline_writes_cleaned_flagged_and_summary_outputs(tmp_path):
    session = Mock()
    session.post.return_value = FakeResponse(
        {
            "results": [api_record(amount=2_000_000_000)],
            "page_metadata": {"hasNext": False},
        }
    )
    client = USAspendingClient(session=session, backoff_seconds=0)
    fpds_client = Mock()
    fpds_client.search_award.return_value = []

    result = run_pipeline(
        root=Path(tmp_path), max_records=1, client=client, fpds_client=fpds_client
    )

    assert result["records"] == 1
    assert result["flagged"] == 1
    assert Path(result["cleaned_path"]).is_file()
    assert Path(result["flagged_path"]).is_file()
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "not accusations or conclusions" in report
    assert "Source record:" in report
    assert "Amount comparison status counts" in report


@pytest.mark.parametrize("page_size", [0, 101])
def test_rejects_invalid_page_size(page_size):
    with pytest.raises(ValueError, match="page_size"):
        USAspendingClient().fetch_contract_awards(page_size=page_size)