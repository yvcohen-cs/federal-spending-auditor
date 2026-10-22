import json
from unittest.mock import Mock

import requests

from src.federal_spending_auditor import USAspendingClient


class FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status_code = status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self.body


def award(index):
    return {
        "internal_id": index,
        "Award ID": f"PIID-{index:04d}",
        "Award Amount": index * 100,
        "generated_internal_id": f"CONT_AWD_PIID-{index:04d}",
    }


def test_query_metadata_and_complete_checkpoint_allow_offline_resume(tmp_path):
    session = Mock()
    session.post.side_effect = [
        FakeResponse({"results": [award(1)], "page_metadata": {"hasNext": True}}),
        FakeResponse({"results": [award(2)], "page_metadata": {"hasNext": False}}),
    ]
    client = USAspendingClient(session=session, backoff_seconds=0, page_delay_seconds=0)

    initial = client.fetch_contract_awards(max_records=2, page_size=1, raw_dir=tmp_path)
    metadata = json.loads((tmp_path / "query_metadata.json").read_text(encoding="utf-8"))
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8"))

    assert len(initial) == 2
    assert metadata["endpoint"].endswith("spending_by_award/")
    assert metadata["query_fingerprint"] == checkpoint["query_fingerprint"]
    assert checkpoint["completed_pages"] == [1, 2]
    assert checkpoint["complete"] is True

    resumed = client.fetch_contract_awards(max_records=2, page_size=1, raw_dir=tmp_path)

    assert resumed == initial
    assert session.post.call_count == 2


def test_checkpoint_rejects_different_query_parameters(tmp_path):
    session = Mock()
    session.post.return_value = FakeResponse(
        {"results": [award(1)], "page_metadata": {"hasNext": False}}
    )
    client = USAspendingClient(session=session, backoff_seconds=0, page_delay_seconds=0)
    client.fetch_contract_awards(max_records=1, raw_dir=tmp_path)

    try:
        client.fetch_contract_awards(fiscal_year=2024, max_records=1, raw_dir=tmp_path)
    except ValueError as exc:
        assert "query differs" in str(exc)
    else:
        raise AssertionError("changed query must not reuse an incompatible checkpoint")


def test_page_delay_is_applied_between_requests(monkeypatch):
    session = Mock()
    session.post.side_effect = [
        FakeResponse({"results": [award(1)], "page_metadata": {"hasNext": True}}),
        FakeResponse({"results": [award(2)], "page_metadata": {"hasNext": False}}),
    ]
    sleep = Mock()
    monkeypatch.setattr("src.federal_spending_auditor.time.sleep", sleep)
    client = USAspendingClient(session=session, backoff_seconds=0, page_delay_seconds=0.4)

    client.fetch_contract_awards(max_records=2, page_size=1)

    sleep.assert_called_once_with(0.4)
