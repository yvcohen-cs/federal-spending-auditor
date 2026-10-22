"""Award transaction-level lifecycle analysis using USAspending's API."""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .federal_spending_auditor import API_DOCS_URL, TRANSACTIONS_URL, USAspendingClient


TRANSACTION_FIELDS = [
    "id",
    "type",
    "type_description",
    "action_date",
    "action_type",
    "action_type_description",
    "modification_number",
    "federal_action_obligation",
    "face_value_loan_guarantee",
    "original_loan_subsidy_cost",
]


def _is_fiscal_year_date(value: Any, fiscal_year: int) -> bool:
    try:
        action_date = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return date(fiscal_year - 1, 10, 1) <= action_date <= date(fiscal_year, 9, 30)


def fetch_lifecycle_transactions(
    awards: list[dict[str, Any]],
    client: USAspendingClient,
    fiscal_year: int = 2025,
    award_limit: int = 10,
    max_transactions_per_award: int = 500,
    raw_root: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch transactions for a deterministic bounded subset of awards.

    The award subset is for lifecycle coverage only; results are not a census.
    FY obligations are calculated from transaction federal action obligations,
    never from award-level Award Amount values.
    """
    if award_limit < 0:
        raise ValueError("award_limit cannot be negative")
    if max_transactions_per_award < 1:
        raise ValueError("max_transactions_per_award must be at least 1")

    transactions: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    selected = awards[:award_limit]
    for index, award in enumerate(selected):
        generated_id = award.get("generated_internal_id")
        internal_id = award.get("internal_id")
        award_reference = str(internal_id or generated_id or award.get("award_id") or "unknown")
        summary: dict[str, Any] = {
            "internal_id": internal_id,
            "award_id": award.get("award_id"),
            "generated_internal_id": generated_id,
            "source_record_url": award.get("source_record_url"),
            "transaction_count": 0,
            "fy_transaction_count": 0,
            "fy_federal_action_obligation": "0",
            "status": "not_requested",
            "source_api": TRANSACTIONS_URL,
            "api_documentation": API_DOCS_URL,
        }
        if not generated_id:
            summary["status"] = "missing_generated_award_identifier"
            summaries.append(summary)
            continue

        transaction_raw_dir = raw_root / f"award_{award_reference}" if raw_root else None
        try:
            award_transactions = client.fetch_transactions(
                str(generated_id),
                max_records=max_transactions_per_award,
                raw_dir=transaction_raw_dir,
            )
        except (RuntimeError, ValueError) as exc:
            summary["status"] = "api_error"
            summary["error"] = str(exc)
            summaries.append(summary)
            continue

        fy_obligation = Decimal("0")
        fy_count = 0
        for transaction in award_transactions:
            action_date = transaction.get("action_date")
            is_fy_action = _is_fiscal_year_date(action_date, fiscal_year)
            federal_action_obligation = transaction.get("federal_action_obligation")
            if is_fy_action and federal_action_obligation is not None:
                try:
                    fy_obligation += Decimal(str(federal_action_obligation))
                    fy_count += 1
                except (InvalidOperation, ValueError):
                    pass
            transactions.append(
                {
                    "internal_id": internal_id,
                    "award_id": award.get("award_id"),
                    "generated_internal_id": generated_id,
                    "award_source_url": award.get("source_record_url"),
                    "transaction_id": transaction.get("id"),
                    "transaction_type": transaction.get("type"),
                    "transaction_type_description": transaction.get("type_description"),
                    "action_date": action_date,
                    "action_type": transaction.get("action_type"),
                    "action_type_description": transaction.get("action_type_description"),
                    "modification_number": transaction.get("modification_number"),
                    "federal_action_obligation": federal_action_obligation,
                    "is_fy_action": is_fy_action,
                    "source_api_url": TRANSACTIONS_URL,
                    "source_documentation_url": API_DOCS_URL,
                    "verification_status": "unverified",
                }
            )
        summary["transaction_count"] = len(award_transactions)
        summary["fy_transaction_count"] = fy_count
        summary["fy_federal_action_obligation"] = str(fy_obligation)
        summary["transaction_history_truncated"] = client.last_transaction_fetch_truncated
        summary["status"] = (
            "retrieved_limit_reached"
            if client.last_transaction_fetch_truncated
            else "retrieved"
        )
        summaries.append(summary)
        if index < len(selected) - 1 and client.page_delay_seconds:
            time.sleep(client.page_delay_seconds)
    return transactions, summaries
