from unittest.mock import Mock
from decimal import Decimal

import requests

from src.federal_spending_auditor import TRANSACTIONS_URL, USAspendingClient
from src.lifecycle import fetch_lifecycle_transactions


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


def test_lifecycle_sums_fy_action_obligations_separately_from_award_amount(tmp_path):
    session = Mock()
    session.post.return_value = FakeResponse(
        {
            "results": [
                {
                    "id": "TX-FY25-1",
                    "action_date": "2024-10-01",
                    "modification_number": "P00001",
                    "federal_action_obligation": 125.50,
                },
                {
                    "id": "TX-FY24",
                    "action_date": "2024-09-30",
                    "modification_number": "0",
                    "federal_action_obligation": 5000,
                },
                {
                    "id": "TX-FY25-2",
                    "action_date": "2025-09-30",
                    "modification_number": "P00002",
                    "federal_action_obligation": -25.50,
                },
            ],
            "page_metadata": {"hasNext": False},
        }
    )
    client = USAspendingClient(session=session, backoff_seconds=0, page_delay_seconds=0)
    awards = [
        {
            "internal_id": 77,
            "award_id": "TEST-PIID",
            "generated_internal_id": "CONT_AWD_TEST-PIID_8600_NONE_NONE",
            "award_amount": 999999999,
            "source_record_url": "https://www.usaspending.gov/award/CONT_AWD_TEST-PIID_8600_NONE_NONE",
        }
    ]

    transactions, summaries = fetch_lifecycle_transactions(
        awards, client, fiscal_year=2025, raw_root=tmp_path
    )

    assert session.post.call_args.args[0] == TRANSACTIONS_URL
    assert session.post.call_args.kwargs["json"]["award_id"] == awards[0]["generated_internal_id"]
    assert [row["modification_number"] for row in transactions] == ["P00001", "0", "P00002"]
    assert [row["is_fy_action"] for row in transactions] == [True, False, True]
    assert summaries[0]["fy_transaction_count"] == 2
    assert Decimal(summaries[0]["fy_federal_action_obligation"]) == Decimal("100")
    assert summaries[0]["fy_federal_action_obligation"] != str(awards[0]["award_amount"])
    assert (tmp_path / "award_77" / "page_0001.json").exists()


def test_lifecycle_records_api_failure_without_inventing_transactions():
    session = Mock()
    session.post.side_effect = requests.ConnectionError("offline fixture")
    client = USAspendingClient(session=session, retries=1, backoff_seconds=0, page_delay_seconds=0)
    awards = [{"internal_id": 88, "award_id": "TEST", "generated_internal_id": "CONT_AWD_TEST"}]

    transactions, summaries = fetch_lifecycle_transactions(awards, client)

    assert transactions == []
    assert summaries[0]["status"] == "api_error"
    assert summaries[0]["transaction_count"] == 0
    assert session.post.call_count == 2


def test_lifecycle_marks_transaction_history_truncated_at_limit():
    session = Mock()
    session.post.return_value = FakeResponse(
        {
            "results": [
                {
                    "id": "TX-1",
                    "action_date": "2025-01-01",
                    "modification_number": "1",
                    "federal_action_obligation": 10,
                }
            ],
            "page_metadata": {"hasNext": True},
        }
    )
    client = USAspendingClient(session=session, backoff_seconds=0, page_delay_seconds=0)

    _, summaries = fetch_lifecycle_transactions(
        [{"internal_id": 3, "generated_internal_id": "CONT_AWD_TEST"}],
        client,
        max_transactions_per_award=1,
    )

    assert summaries[0]["status"] == "retrieved_limit_reached"
    assert summaries[0]["transaction_history_truncated"] is True
