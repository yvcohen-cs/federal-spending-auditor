"""Deterministic synthetic artifacts emitted by the unchanged real collectors."""
import json
from datetime import datetime, timezone
from unittest.mock import Mock

from src.federal_spending_auditor import USAspendingClient
from src.reconciliation import FPDSClient
from src.sampling import collect
from tests.test_collection import FakeResponse
from tests.test_reconciliation import FPDS_XML, FakeResponse as XMLResponse


class FrozenClock:
    @staticmethod
    def now(tz=None):
        return datetime(2025, 10, 1, tzinfo=timezone.utc)


def freeze(monkeypatch):
    monkeypatch.setattr("src.sampling.now", lambda: "2025-10-01T00:00:00+00:00")
    monkeypatch.setattr("src.federal_spending_auditor.datetime", FrozenClock)
    monkeypatch.setattr("src.reconciliation.datetime", FrozenClock)


def body():
    return {"results": [{"generated_internal_id": "CONT_AWD_00001-A_08600",
                         "Award ID": "00001-A", "Awarding Sub Agency Code": "08600",
                         "Award Amount": "100.00", "Last Modified Date": "2025-09-30"}],
            "page_metadata": {"hasNext": False}}


def stratified(root, monkeypatch):
    freeze(monkeypatch)
    client = USAspendingClient(page_delay_seconds=0)
    client._post = Mock(return_value=body())
    collect(client, raw_dir=root, max_records=1, period="year", award_types=("A",))
    return root


def legacy(root, monkeypatch, transactions=False):
    freeze(monkeypatch)
    session = Mock()
    data = body() if not transactions else {
        "results": [{"id": "0002.A/0", "modification_number": "P00001",
                     "federal_action_obligation": "-20.00"}], "page_metadata": {"hasNext": False}}
    session.post.return_value = FakeResponse(data)
    client = USAspendingClient(session=session, page_delay_seconds=0)
    if transactions:
        client.fetch_transactions("CONT_AWD_00001-A_08600", raw_dir=root)
    else:
        client.fetch_contract_awards(max_records=1, raw_dir=root)
    return root


def fpds(root, monkeypatch):
    freeze(monkeypatch)
    session = Mock()
    session.get.return_value = XMLResponse(FPDS_XML)
    client = FPDSClient(session=session, page_delay_seconds=0)
    client.search_award("00001", "8600", max_results=1,
                        raw_path=root / "fpds_lookup_001.xml")
    return root


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
