"""Identifier-level reconciliation against the official FPDS ATOM feed."""

from __future__ import annotations

import time
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


FPDS_URL = "https://www.fpds.gov/ezsearch/FEEDS/ATOM"
FPDS_DOCS_URL = "https://www.fpds.gov/ezsearch/FPDSNG_Atom_GettingStarted.html"


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _first_child(parent: ET.Element | None, name: str) -> ET.Element | None:
    if parent is None:
        return None
    return next((child for child in parent if _local_name(child) == name), None)


def _descendant(parent: ET.Element, name: str) -> ET.Element | None:
    return next((node for node in parent.iter() if _local_name(node) == name), None)


def _text(node: ET.Element | None) -> str | None:
    if node is None or node.text is None or not node.text.strip():
        return None
    return node.text.strip()


def parse_fpds_feed(xml_text: str) -> tuple[list[dict[str, Any]], str | None]:
    root = ET.fromstring(xml_text)
    entries = []
    next_url = None
    for link in root.iter():
        if _local_name(link) == "link" and link.attrib.get("rel") == "next":
            next_url = link.attrib.get("href")
            break

    for entry in (node for node in root.iter() if _local_name(node) == "entry"):
        award = _descendant(entry, "award")
        award_id = _first_child(award, "awardID")
        contract_id = _first_child(award_id, "awardContractID")
        agency = _first_child(contract_id, "agencyID")
        piid = _first_child(contract_id, "PIID")
        mod = _first_child(contract_id, "modNumber")
        transaction = _first_child(contract_id, "transactionNumber")
        dollar_values = _first_child(award, "dollarValues")
        total_values = _first_child(award, "totalDollarValues")
        contract_dates = _first_child(award, "relevantContractDates")
        entry_link = next(
            (
                node.attrib.get("href")
                for node in entry
                if _local_name(node) == "link"
                and node.attrib.get("rel") == "alternate"
            ),
            None,
        )
        vendor_name = _descendant(award, "vendorName")
        entries.append(
            {
                "piid": _text(piid),
                "contracting_agency_id": _text(agency),
                "contracting_agency_name": agency.attrib.get("name") if agency is not None else None,
                "modification_number": _text(mod),
                "transaction_number": _text(transaction),
                "action_date": _text(_first_child(contract_dates, "effectiveDate")),
                "obligated_amount": _text(_first_child(dollar_values, "obligatedAmount")),
                "total_obligated_amount": _text(
                    _first_child(total_values, "totalObligatedAmount")
                ),
                "recipient_name": _text(vendor_name),
                "source_record_url": entry_link,
                "title": _text(_first_child(entry, "title")),
            }
        )
    return entries, next_url


class FPDSClient:
    """Small, rate-limited reader for the public FPDS Atom feed."""

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 25.0,
        retries: int = 2,
        backoff_seconds: float = 0.75,
        page_delay_seconds: float = 0.5,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.page_delay_seconds = page_delay_seconds

    def _get(self, url: str, params: dict[str, Any] | None = None) -> str:
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return response.text
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt >= self.retries:
                    raise RuntimeError("FPDS request failed after retries") from exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response else None
                retryable = status == 429 or (status is not None and status >= 500)
                if not retryable:
                    raise
                if attempt >= self.retries:
                    raise RuntimeError(f"FPDS returned HTTP {status} after retries") from exc
                retry_after = exc.response.headers.get("Retry-After") if exc.response else None
                try:
                    delay = max(self.backoff_seconds * (2**attempt), float(retry_after or 0))
                except ValueError:
                    delay = self.backoff_seconds * (2**attempt)
                if delay:
                    time.sleep(delay)
                continue
            if self.backoff_seconds:
                time.sleep(self.backoff_seconds * (2**attempt))
        raise RuntimeError("FPDS request exhausted retries")

    def search_award(
        self,
        piid: str,
        contracting_agency_id: str,
        max_results: int = 50,
        raw_path: Path | None = None,
    ) -> list[dict[str, Any]]:
        if max_results < 1:
            raise ValueError("max_results must be at least 1")
        if not piid or not contracting_agency_id:
            raise ValueError("PIID and contracting agency ID are required")
        query = f"PIID:{piid.strip()} AND CONTRACTING_AGENCY_ID:{contracting_agency_id.strip()}"
        url = FPDS_URL
        params: dict[str, Any] | None = {
            "FEEDNAME": "PUBLIC",
            "q": query,
            "length": min(10, max_results),
        }
        all_entries: list[dict[str, Any]] = []
        raw_pages = []
        while url:
            xml_text = self._get(url, params=params)
            raw_pages.append(xml_text)
            entries, next_url = parse_fpds_feed(xml_text)
            all_entries.extend(entries)
            if len(all_entries) >= max_results or not next_url:
                break
            url, params = next_url, None
            if self.page_delay_seconds:
                time.sleep(self.page_delay_seconds)
        if raw_path is not None:
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            query_metadata = {
                "source": "FPDS public ATOM feed",
                "endpoint": FPDS_URL,
                "documentation": FPDS_DOCS_URL,
                "method": "GET",
                "query": query,
                "params": {
                    "FEEDNAME": "PUBLIC",
                    "q": query,
                    "length": min(10, max_results),
                },
                "max_results": max_results,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            }
            raw_path.with_name(f"{raw_path.stem}_query.json").write_text(
                json.dumps(query_metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for page_number, xml_text in enumerate(raw_pages, start=1):
                page_path = raw_path.with_name(
                    f"{raw_path.stem}_page_{page_number:03d}{raw_path.suffix}"
                )
                page_path.write_text(xml_text, encoding="utf-8")
        return all_entries[:max_results]


def _amount_difference(left: Any, right: Any) -> str | None:
    if left is None or right is None:
        return None
    try:
        return str(Decimal(str(left)) - Decimal(str(right)))
    except (InvalidOperation, ValueError):
        return None


def reconcile_awards(
    awards: list[dict[str, Any]],
    client: FPDSClient,
    sample_size: int = 5,
    raw_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Compare exact award PIID + contracting-agency identifiers with FPDS."""
    if sample_size < 0:
        raise ValueError("sample_size cannot be negative")
    results = []
    for index, award in enumerate(awards[:sample_size]):
        piid = award.get("award_id")
        agency_id = award.get("awarding_sub_agency_code")
        result: dict[str, Any] = {
            "internal_id": award.get("internal_id"),
            "award_id": piid,
            "generated_internal_id": award.get("generated_internal_id"),
            "usa_awarding_sub_agency_code": agency_id,
            "usa_award_amount": award.get("award_amount"),
            "usa_recipient_uei": award.get("recipient_uei"),
            "usa_source_url": award.get("source_record_url"),
            "fpds_status": "not_requested",
            "fpds_record_count": 0,
            "fpds_modifications": "",
            "fpds_transaction_ids": "",
            "fpds_record_urls": "",
            "fpds_total_obligated_amount": None,
            "amount_difference_usa_minus_fpds": None,
            "amount_comparison_status": "not_compared",
            "verification_status": "unverified",
            "match_rule": "exact trimmed PIID + contracting agency identifier",
            "benign_explanations": (
                "Differences can result from reporting latency, source coverage, identifier mapping, "
                "or distinct award/obligation definitions. A missing match is not evidence of misconduct."
            ),
        }
        if not piid or not agency_id:
            result["fpds_status"] = "missing_match_identifiers"
            results.append(result)
            continue
        raw_path = raw_dir / f"fpds_lookup_{index + 1:03d}.xml" if raw_dir else None
        try:
            source_rows = client.search_award(
                str(piid), str(agency_id), raw_path=raw_path
            )
        except (RuntimeError, ValueError, ET.ParseError, requests.RequestException) as exc:
            result["fpds_status"] = "source_error"
            result["error"] = str(exc)
            results.append(result)
            continue

        exact_matches = [
            row
            for row in source_rows
            if (row.get("piid") or "").strip() == str(piid).strip()
            and (row.get("contracting_agency_id") or "").strip()
            == str(agency_id).strip()
        ]
        if not exact_matches:
            result["fpds_status"] = "no_exact_identifier_match"
        else:
            result["fpds_status"] = "matched_identifiers"
            result["fpds_record_count"] = len(exact_matches)
            result["fpds_modifications"] = " | ".join(
                str(row["modification_number"])
                for row in exact_matches
                if row.get("modification_number") is not None
            )
            result["fpds_transaction_ids"] = " | ".join(
                str(row["transaction_number"])
                for row in exact_matches
                if row.get("transaction_number") is not None
            )
            result["fpds_record_urls"] = " | ".join(
                str(row["source_record_url"])
                for row in exact_matches
                if row.get("source_record_url")
            )
            dated_matches = [row for row in exact_matches if row.get("action_date")]
            latest_date = max((row["action_date"] for row in dated_matches), default=None)
            latest_matches = [row for row in dated_matches if row["action_date"] == latest_date]
            if len(latest_matches) == 1:
                result["fpds_total_obligated_amount"] = latest_matches[0].get("total_obligated_amount")
                result["fpds_latest_action_date"] = latest_date
            elif not dated_matches and len(exact_matches) == 1:
                result["fpds_total_obligated_amount"] = exact_matches[0].get("total_obligated_amount")
            else:
                result["amount_comparison_status"] = "not_compared_ambiguous_modification_history"
            result["amount_difference_usa_minus_fpds"] = _amount_difference(
                award.get("award_amount"), result["fpds_total_obligated_amount"]
            )
            if result["amount_difference_usa_minus_fpds"] is not None:
                result["amount_comparison_status"] = "values_available_definitions_may_differ"
            elif result["amount_comparison_status"] != "not_compared_ambiguous_modification_history":
                result["amount_comparison_status"] = "not_comparable_missing_value"
        results.append(result)
        if index < min(sample_size, len(awards)) - 1 and client.page_delay_seconds:
            time.sleep(client.page_delay_seconds)
    return results
