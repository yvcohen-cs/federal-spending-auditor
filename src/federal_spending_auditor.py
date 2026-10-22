"""Fetch and screen a bounded sample of USAspending.gov contract awards."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


API_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
TRANSACTIONS_URL = "https://api.usaspending.gov/api/v2/transactions/"
API_DOCS_URL = "https://api.usaspending.gov/docs/endpoints"
AWARD_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
    "Recipient DUNS",
    "Start Date",
    "End Date",
    "Award Amount",
    "Awarding Agency",
    "Awarding Agency Code",
    "Awarding Sub Agency",
    "Awarding Sub Agency Code",
    "NAICS Code",
    "PSC Code",
    "Award Type",
]
OUTPUT_FIELDS = [
    "internal_id",
    "award_id",
    "recipient_name",
    "recipient_uei",
    "recipient_duns",
    "start_date",
    "end_date",
    "award_amount",
    "awarding_agency",
    "awarding_agency_code",
    "awarding_sub_agency",
    "awarding_sub_agency_code",
    "naics_code",
    "psc_code",
    "award_type",
    "generated_internal_id",
    "source_record_url",
]
FLAG_FIELDS = OUTPUT_FIELDS + ["flag_reasons", "duplicate_of"]


class USAspendingClient:
    """Small client for the documented Advanced Award Search endpoint."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 20.0,
        retries: int = 3,
        backoff_seconds: float = 0.5,
        page_delay_seconds: float = 0.25,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.page_delay_seconds = page_delay_seconds
        self.last_transaction_fetch_truncated = False

    def _post(
        self, payload: dict[str, Any], url: str = API_URL
    ) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            try:
                response = self.session.post(
                    url, json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise ValueError("USAspending API returned a non-object response")
                return body
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.retries:
                    raise RuntimeError(
                        f"USAspending API request failed after {attempt + 1} attempts"
                    ) from exc
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response else None
                if status_code not in (429,) and not (
                    status_code is not None and status_code >= 500
                ):
                    raise
                if attempt >= self.retries:
                    raise RuntimeError(
                        f"USAspending API returned HTTP {status_code} after "
                        f"{attempt + 1} attempts"
                    ) from exc
                retry_after = None
                if exc.response is not None:
                    retry_after = exc.response.headers.get("Retry-After")
                try:
                    wait_seconds = max(
                        self.backoff_seconds * (2**attempt), float(retry_after or 0)
                    )
                except ValueError:
                    wait_seconds = self.backoff_seconds * (2**attempt)
                if wait_seconds:
                    time.sleep(wait_seconds)
                continue
            if self.backoff_seconds:
                time.sleep(self.backoff_seconds * (2**attempt))
        raise RuntimeError("USAspending API request exhausted retries")

    def fetch_contract_awards(
        self,
        fiscal_year: int = 2025,
        max_records: int = 200,
        page_size: int = 100,
        raw_dir: Path | None = None,
        page_delay_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch at most max_records awards, saving each unmodified response."""
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if max_records < 1:
            raise ValueError("max_records must be at least 1")

        start_year = fiscal_year - 1
        start_date = f"{start_year}-10-01"
        end_date = f"{fiscal_year}-09-30"
        results: list[dict[str, Any]] = []
        query = {
            "filters": {
                "time_period": [{"start_date": start_date, "end_date": end_date}],
                "award_type_codes": ["A", "B", "C", "D"],
            },
            "fields": AWARD_FIELDS,
            "sort": "Award ID",
            "order": "asc",
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                {**query, "max_records": max_records, "page_size": page_size},
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        completed_pages: list[int] = []
        checkpoint_path = raw_dir / "checkpoint.json" if raw_dir else None
        query_path = raw_dir / "query_metadata.json" if raw_dir else None
        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            metadata = {
                "source": "USAspending.gov Advanced Award Search API",
                "endpoint": API_URL,
                "documentation": API_DOCS_URL,
                "method": "POST",
                "fiscal_year": fiscal_year,
                "date_filter": {"start_date": start_date, "end_date": end_date},
                "filters": query["filters"],
                "fields": AWARD_FIELDS,
                "sort": query["sort"],
                "order": query["order"],
                "target_records": max_records,
                "page_size": page_size,
                "query_fingerprint": fingerprint,
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            self._write_json_atomic(query_path, metadata)
            if checkpoint_path.exists():
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if checkpoint.get("query_fingerprint") != fingerprint:
                    raise ValueError(
                        "Checkpoint query differs; use a new raw directory or matching parameters"
                    )
                completed_pages = [int(page) for page in checkpoint.get("completed_pages", [])]
                for saved_page in completed_pages:
                    saved_path = raw_dir / f"page_{saved_page:04d}.json"
                    if not saved_path.exists():
                        raise ValueError(f"Checkpoint page is missing: {saved_path}")
                    saved_body = json.loads(saved_path.read_text(encoding="utf-8"))
                    saved_results = saved_body.get("results")
                    if not isinstance(saved_results, list):
                        raise ValueError(f"Checkpoint page has no results list: {saved_path}")
                    results.extend(item for item in saved_results if isinstance(item, dict))
                if checkpoint.get("complete"):
                    return results[:max_records]
        page = max(completed_pages, default=0) + 1
        delay = self.page_delay_seconds if page_delay_seconds is None else page_delay_seconds
        saw_terminal_page = False

        while len(results) < max_records:
            limit = min(page_size, max_records - len(results))
            payload = {
                **query,
                "page": page,
                "limit": limit,
            }
            body = self._post(payload)
            page_results = body.get("results")
            if not isinstance(page_results, list):
                raise ValueError("USAspending API response has no results list")
            if raw_dir is not None:
                raw_path = raw_dir / f"page_{page:04d}.json"
                self._write_json_atomic(raw_path, body)
            results.extend(item for item in page_results if isinstance(item, dict))
            page_metadata = body.get("page_metadata") or {}
            if not page_metadata.get("hasNext") or not page_results:
                saw_terminal_page = True
                if raw_dir is not None:
                    completed_pages.append(page)
                break
            if raw_dir is not None:
                completed_pages.append(page)
            if checkpoint_path is not None:
                self._write_json_atomic(
                    checkpoint_path,
                    {
                        "query_fingerprint": fingerprint,
                        "completed_pages": completed_pages,
                        "records_saved": len(results),
                        "target_records": max_records,
                        "complete": False,
                    },
                )
            if delay > 0:
                time.sleep(delay)
            page += 1

        if checkpoint_path is not None:
            self._write_json_atomic(
                checkpoint_path,
                {
                    "query_fingerprint": fingerprint,
                    "completed_pages": completed_pages,
                    "records_saved": len(results),
                    "target_records": max_records,
                    "complete": saw_terminal_page or len(results) >= max_records,
                },
            )

        return results[:max_records]

    def fetch_transactions(
        self,
        award_id: str,
        page_size: int = 100,
        max_records: int = 500,
        raw_dir: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch award transactions, including modification and action fields."""
        if not 1 <= page_size <= 100:
            raise ValueError("transaction page_size must be between 1 and 100")
        if max_records < 1:
            raise ValueError("max_records must be at least 1")
        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(
                raw_dir / "query_metadata.json",
                {
                    "source": "USAspending.gov award transaction endpoint",
                    "endpoint": TRANSACTIONS_URL,
                    "documentation": API_DOCS_URL,
                    "method": "POST",
                    "award_id": award_id,
                    "page_size": page_size,
                    "target_transactions": max_records,
                },
            )
        records: list[dict[str, Any]] = []
        page = 1
        has_more = False
        while len(records) < max_records:
            limit = min(page_size, max_records - len(records))
            body = self._post(
                {"award_id": award_id, "page": page, "limit": limit},
                url=TRANSACTIONS_URL,
            )
            page_results = body.get("results")
            if not isinstance(page_results, list):
                raise ValueError("USAspending transaction response has no results list")
            if raw_dir is not None:
                raw_dir.mkdir(parents=True, exist_ok=True)
                self._write_json_atomic(raw_dir / f"page_{page:04d}.json", body)
            records.extend(item for item in page_results if isinstance(item, dict))
            page_metadata = body.get("page_metadata") or {}
            has_more = bool(page_metadata.get("hasNext"))
            if not page_metadata.get("hasNext") or not page_results:
                break
            if self.page_delay_seconds:
                time.sleep(self.page_delay_seconds)
            page += 1
        self.last_transaction_fetch_truncated = has_more and len(records) >= max_records
        return records[:max_records]

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
        temporary_path.replace(path)


def _value(record: dict[str, Any], key: str) -> Any:
    value = record.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return value


def clean_awards(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for record in records:
        generated_id = _value(record, "generated_internal_id")
        award_id = _value(record, "Award ID")
        reference_id = generated_id or award_id
        source_url = (
            f"https://www.usaspending.gov/award/{quote(str(reference_id), safe='')}"
            if reference_id
            else ""
        )
        cleaned.append(
            {
                "internal_id": _value(record, "internal_id"),
                "award_id": award_id,
                "recipient_name": _value(record, "Recipient Name"),
                "recipient_uei": _value(record, "Recipient UEI"),
                "recipient_duns": _value(record, "Recipient DUNS"),
                "start_date": _value(record, "Start Date"),
                "end_date": _value(record, "End Date"),
                "award_amount": _value(record, "Award Amount"),
                "awarding_agency": _value(record, "Awarding Agency"),
                "awarding_agency_code": _value(record, "Awarding Agency Code"),
                "awarding_sub_agency": _value(record, "Awarding Sub Agency"),
                "awarding_sub_agency_code": _value(record, "Awarding Sub Agency Code"),
                "naics_code": _value(record, "NAICS Code"),
                "psc_code": _value(record, "PSC Code"),
                "award_type": _value(record, "Award Type"),
                "generated_internal_id": generated_id,
                "source_record_url": source_url,
            }
        )
    return cleaned


def _signature(record: dict[str, Any]) -> tuple[str, ...]:
    amount = record.get("award_amount")
    try:
        amount_key = str(Decimal(str(amount)).normalize()) if amount is not None else ""
    except (InvalidOperation, ValueError):
        amount_key = str(amount)
    fields = (
        "award_id",
        "generated_internal_id",
        "recipient_uei",
        "recipient_duns",
        "recipient_name",
        "start_date",
        "end_date",
        "awarding_agency",
        "awarding_sub_agency",
    )
    return tuple(str(record.get(field) or "") for field in fields) + (amount_key,)


def flag_awards(
    records: list[dict[str, Any]], amount_threshold: float = 1_000_000_000
) -> list[dict[str, Any]]:
    flagged = []
    first_by_signature: dict[tuple[str, ...], dict[str, Any]] = {}
    for record in records:
        reasons = []
        duplicate_of = ""
        try:
            amount = Decimal(str(record.get("award_amount")))
        except (InvalidOperation, ValueError, TypeError):
            amount = None
        if amount is not None and amount.is_finite() and amount > Decimal(str(amount_threshold)):
            reasons.append(
                f"Award amount exceeds the ${amount_threshold:,.2f} screening threshold"
            )

        if not record.get("award_id"):
            reasons.append("Award ID is missing")
        if not record.get("generated_internal_id"):
            reasons.append("Generated award identifier is missing")
        if not record.get("recipient_uei") and not record.get("recipient_duns"):
            reasons.append("Recipient UEI and DUNS are both missing")

        signature = _signature(record)
        previous = first_by_signature.get(signature)
        if previous is not None:
            reasons.append(
                "Exact award-record signature repeats; possible duplicate or reporting artifact"
            )
            duplicate_of = str(
                previous.get("internal_id")
                or previous.get("generated_internal_id")
                or previous.get("award_id")
                or "earlier matching row"
            )
        else:
            first_by_signature[signature] = record

        if reasons:
            flagged.append(
                {**record, "flag_reasons": "; ".join(reasons), "duplicate_of": duplicate_of}
            )
    return flagged


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _shared_award_id_groups(records: list[dict[str, Any]]) -> int:
    signatures_by_award: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    for record in records:
        award_id = record.get("award_id")
        if award_id:
            signatures_by_award[str(award_id)].add(_signature(record))
    return sum(len(signatures) > 1 for signatures in signatures_by_award.values())


def _write_report(
    path: Path,
    fiscal_year: int,
    records: list[dict[str, Any]],
    flagged: list[dict[str, Any]],
    amount_threshold: float,
    run_id: str,
) -> None:
    categories = {
        "Large award amount": sum("screening threshold" in row["flag_reasons"] for row in flagged),
        "Missing award identifier": sum(
            "Award ID is missing" in row["flag_reasons"]
            or "Generated award identifier is missing" in row["flag_reasons"]
            for row in flagged
        ),
        "Missing recipient identifiers": sum(
            "Recipient UEI and DUNS are both missing" in row["flag_reasons"]
            for row in flagged
        ),
        "Exact repeated signatures": sum(
            "Exact award-record signature repeats" in row["flag_reasons"]
            for row in flagged
        ),
    }
    lines = [
        f"# FY{fiscal_year} Federal Contract Award Screening",
        "",
        f"- Run ID (UTC): `{run_id}`",
        f"- Records analyzed: {len(records)}",
        f"- Records with one or more screening flags: {len(flagged)}",
        f"- Large-amount threshold: ${amount_threshold:,.2f}",
        "- Data source: USAspending.gov Advanced Award Search API",
        f"- Endpoint: [{API_URL}]({API_URL})",
        f"- API documentation: [{API_DOCS_URL}]({API_DOCS_URL})",
        "- FY2025 date filter: 2024-10-01 through 2025-09-30; contract type codes A-D.",
        "",
        "## Flag counts",
        "",
    ]
    lines.extend(f"- {name}: {count}" for name, count in categories.items())
    lines.extend(
        [
            "",
            "## Interpretation and limitations",
            "",
            "These are review cues, not findings of wrongdoing. No organization is labeled fraudulent.",
            "The endpoint returns award-level records. Its Award Amount is not necessarily the amount "
            "obligated during FY2025, so the configurable amount threshold is a triage rule rather "
            "than an FY2025 spending outlier test.",
            "The response does not expose transaction modification numbers. Records with the same "
            "Award ID but differing details are retained; they can represent modifications, task-order "
            "relationships, or reporting artifacts and are not labeled duplicates by that fact alone.",
            f"{_shared_award_id_groups(records)} Award ID group(s) contained multiple distinct "
            "record signatures and were retained for review.",
            "Only a repeated full signature across Award ID, generated identifier, recipient "
            "identifiers/name, dates, agencies, and amount is marked as a potential duplicate. "
            "Even an exact repeat can be a reporting artifact and should be checked against the source.",
            "This is a bounded sample sorted by Award ID, not a census. USAspending data can change "
            "over time, and records may be revised or reported late. Missing recipient UEI/DUNS "
            "values can reflect transition or reporting gaps rather than a problem with an award.",
            "",
            "## Flagged record source references",
            "",
        ]
    )
    if flagged:
        lines.extend(
            f"- Award ID `{row.get('award_id') or 'missing'}`; internal ID "
            f"`{row.get('internal_id') or 'missing'}`; reasons: {row['flag_reasons']}; "
            f"source record: {row.get('source_record_url') or 'not available'}"
            for row in flagged
        )
    else:
        lines.append("No records met the configured screening rules in this sample.")
    lines.extend(
        [
            "",
            "Flagged rows, reason text, and record-level source links are also in the companion CSV.",
            "A lack of flags is not assurance that an award is error-free.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run_pipeline(
    fiscal_year: int = 2025,
    max_records: int = 5000,
    page_size: int = 100,
    amount_threshold: float = 1_000_000_000,
    root: Path | None = None,
    client: USAspendingClient | None = None,
    page_delay_seconds: float = 0.25,
    min_group_size: int = 20,
    lifecycle_award_limit: int = 10,
    reconciliation_sample_size: int = 5,
    resume_run_dir: Path | None = None,
    fpds_client: Any = None,
) -> dict[str, Any]:
    from .analysis import analyze_awards
    from .lifecycle import fetch_lifecycle_transactions
    from .reconciliation import FPDSClient, reconcile_awards
    from .reporting import write_phase2_outputs

    root = root or Path(__file__).resolve().parents[1]
    if resume_run_dir is not None:
        raw_dir = Path(resume_run_dir)
        if not raw_dir.is_absolute():
            raw_dir = root / raw_dir
        run_id = raw_dir.name
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        raw_dir = root / "data" / "raw" / f"fy{fiscal_year}" / run_id
    api_client = client or USAspendingClient(page_delay_seconds=page_delay_seconds)
    records = api_client.fetch_contract_awards(
        fiscal_year=fiscal_year,
        max_records=max_records,
        page_size=page_size,
        raw_dir=raw_dir,
        page_delay_seconds=page_delay_seconds,
    )
    cleaned = clean_awards(records)
    analysis = analyze_awards(
        cleaned,
        amount_threshold=amount_threshold,
        min_group_size=min_group_size,
    )
    transactions, lifecycle_summaries = fetch_lifecycle_transactions(
        cleaned,
        api_client,
        fiscal_year=fiscal_year,
        award_limit=lifecycle_award_limit,
        raw_root=raw_dir / "transactions",
    )
    fpds_raw_dir = root / "data" / "raw" / "fpds" / run_id
    reconciliation = reconcile_awards(
        cleaned,
        fpds_client or FPDSClient(),
        sample_size=reconciliation_sample_size,
        raw_dir=fpds_raw_dir,
    )
    output_paths = write_phase2_outputs(
        root=root,
        fiscal_year=fiscal_year,
        records=cleaned,
        analysis=analysis,
        transactions=transactions,
        lifecycle_summaries=lifecycle_summaries,
        reconciliation=reconciliation,
        run_id=run_id,
        target_records=max_records,
        page_size=page_size,
        lifecycle_award_limit=lifecycle_award_limit,
        reconciliation_sample_size=reconciliation_sample_size,
    )
    run_metadata_path = raw_dir / "run_metadata.json"
    api_client._write_json_atomic(
        run_metadata_path,
        {
                "run_id": run_id,
                "fiscal_year": fiscal_year,
                "target_records": max_records,
                "records_retrieved": len(cleaned),
                "agency_count": len({record.get("awarding_agency_code") or record.get("awarding_agency") for record in cleaned}),
                "rule_counts": analysis["rule_counts"],
                "lifecycle_award_limit": lifecycle_award_limit,
                "lifecycle_award_status_counts": dict(Counter(row.get("status") for row in lifecycle_summaries)),
                "reconciliation_sample_size": reconciliation_sample_size,
                "reconciliation_status_counts": dict(Counter(row.get("fpds_status") for row in reconciliation)),
                "reconciliation_amount_comparison_status_counts": dict(
                    Counter(row.get("amount_comparison_status") for row in reconciliation)
                ),
        },
    )
    return {
        "records": len(cleaned),
        "flagged": len(
            {
                str(
                    row.get("internal_id")
                    or row.get("generated_internal_id")
                    or row.get("award_id")
                    or row["finding_id"]
                )
                for row in analysis["findings"]
            }
        ),
        "finding_rows": len(analysis["findings"]),
        "rule_counts": analysis["rule_counts"],
        "reconciliation_status_counts": dict(
            Counter(row.get("fpds_status") for row in reconciliation)
        ),
        "reconciliation_amount_comparison_status_counts": dict(
            Counter(row.get("amount_comparison_status") for row in reconciliation)
        ),
        "lifecycle_transactions": len(transactions),
        "raw_dir": raw_dir,
        "run_metadata_path": run_metadata_path,
        "flagged_path": output_paths["findings_path"],
        **output_paths,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fiscal-year", type=int, default=2025)
    parser.add_argument("--max-records", type=int, default=5000)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--amount-threshold", type=float, default=1_000_000_000)
    parser.add_argument("--page-delay-seconds", type=float, default=0.25)
    parser.add_argument("--min-group-size", type=int, default=20)
    parser.add_argument("--lifecycle-awards", type=int, default=10)
    parser.add_argument("--reconciliation-sample-size", type=int, default=5)
    parser.add_argument("--resume-run", type=Path)
    args = parser.parse_args()
    result = run_pipeline(
        fiscal_year=args.fiscal_year,
        max_records=args.max_records,
        page_size=args.page_size,
        amount_threshold=args.amount_threshold,
        page_delay_seconds=args.page_delay_seconds,
        min_group_size=args.min_group_size,
        lifecycle_award_limit=args.lifecycle_awards,
        reconciliation_sample_size=args.reconciliation_sample_size,
        resume_run_dir=args.resume_run,
    )
    print(f"Records analyzed: {result['records']}")
    print(f"Records with findings: {result['flagged']}")
    print(f"Finding rows by rule: {result['rule_counts']}")
    print(f"Lifecycle transaction rows: {result['lifecycle_transactions']}")
    print(f"FPDS reconciliation statuses: {result['reconciliation_status_counts']}")
    print(f"Raw responses: {result['raw_dir']}")
    print(f"Run metadata: {result['run_metadata_path']}")
    print(f"Cleaned CSV: {result['cleaned_path']}")
    print(f"Amount statistics CSV: {result['amount_statistics_path']}")
    print(f"Flagged CSV: {result['flagged_path']}")
    print(f"Transaction CSV: {result['transactions_path']}")
    print(f"Lifecycle summary CSV: {result['lifecycle_summary_path']}")
    print(f"Concentration CSV: {result['concentration_path']}")
    print(f"Repeated awards CSV: {result['repeated_awards_path']}")
    print(f"Reconciliation CSV: {result['reconciliation_path']}")
    print(f"Amount chart: {result['chart_path']}")
    print(f"Summary report: {result['report_path']}")


if __name__ == "__main__":
    main()