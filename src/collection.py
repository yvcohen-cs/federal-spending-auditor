"""Opt-in bounded C3 orchestration. No legacy pipeline integration or comparisons."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .collection_sources import FPDS, USA, HTTPTransport, parse_page, request_for
from .collection_store import CollectionStore
from .evidence import Schema, _text
from .evidence_io import EvidenceError, digest


@dataclass(frozen=True, kw_only=True)
class SelectedAward(Schema):
    generated_id: str | None = None
    piid: str | None = None
    agency_id: str | None = None
    parent_piid: str | None = None
    parent_agency_id: str | None = None

    def validate(self):
        if not any((self.generated_id, self.piid, self.agency_id)):
            raise ValueError("explicit native award selection required")
        for key in ("generated_id", "piid", "agency_id", "parent_piid", "parent_agency_id"):
            value = getattr(self, key)
            if value is not None:
                _text(value, key)
                if len(value) > 256:
                    raise ValueError("identifier too long")


@dataclass(frozen=True, kw_only=True)
class CollectionLimits(Schema):
    max_awards: int = 3
    max_pages: int = 2
    max_records_per_source_award: int = 10
    max_records_total: int = 30
    max_requests: int = 10
    page_size: int = 10
    retries: int = 2
    timeout_seconds: float = 20.0
    pace_seconds: float = 0.5
    backoff_seconds: float = 1.0
    max_retry_after_seconds: float = 60.0
    max_response_bytes: int = 8 * 1024 * 1024

    def validate(self):
        import math
        for name in ("max_awards", "max_pages", "max_records_per_source_award", "max_records_total", "max_requests", "page_size", "max_response_bytes"):
            if not 1 <= getattr(self, name) <= 100_000:
                if name != "max_response_bytes" or not 1 <= self.max_response_bytes <= 8 * 1024 * 1024:
                    raise ValueError("invalid collection bound")
        if self.max_awards > 100 or self.max_requests > 1000 or self.page_size > 100 or not 0 <= self.retries <= 5:
            raise ValueError("collection bound exceeds conservative cap")
        for name in ("timeout_seconds", "pace_seconds", "backoff_seconds", "max_retry_after_seconds"):
            if not math.isfinite(getattr(self, name)) or not 0 <= getattr(self, name) <= 300:
                raise ValueError("invalid timing bound")
        if self.timeout_seconds == 0:
            raise ValueError("timeout must be positive")


def make_plan(awards, limits, sources, profile):
    if not awards or len(awards) > limits.max_awards or len(set(awards)) != len(awards):
        raise EvidenceError("invalid_or_duplicate_award_selection")
    if not sources or len(set(sources)) != len(sources) or any(s not in ("usaspending", "fpds") for s in sources):
        raise EvidenceError("unsupported_source_or_filter")
    generated = [a.generated_id for a in awards if a.generated_id is not None]
    if len(set(generated)) != len(generated):
        raise EvidenceError("conflicting_generated_award_selection")
    return {"schema_type": "CollectionPlan", "schema_version": 1, "collector_version": 1,
            "evidence_schema_version": 1, "ingestion_schema_version": 1,
            "awards": [a.to_dict() for a in awards], "limits": limits.to_dict(),
            "sources": list(sources), "profile": profile,
            "source_config": {"usaspending": {"endpoint": USA, "method": "POST", "sort": "action_date", "order": "asc"},
                              "fpds": {"endpoint": FPDS, "method": "GET", "feed": "PUBLIC", "page_size": 10}},
            "identity_basis": "explicit_user_selection_no_crosswalk_validation"}


def retry_delay(meta, attempt, limits, now=None):
    delay = limits.backoff_seconds * (2 ** attempt)
    value = meta.get("retry_after")
    if value is not None:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            try:
                stamp = parsedate_to_datetime(value)
                if stamp.tzinfo is None:
                    return None
                reference = datetime.fromisoformat(meta["retrieved_at_utc"].replace("Z", "+00:00")) if meta.get("retrieved_at_utc") else (now or datetime.now(timezone.utc))
                seconds = (stamp - reference).total_seconds()
            except (TypeError, ValueError, OverflowError):
                seconds = 0
        import math
        if not math.isfinite(seconds):
            return None
        delay = max(delay, seconds, 0)
    # Do not retry earlier than a long server instruction. Stop bounded instead.
    return delay if delay <= limits.max_retry_after_seconds else None


def collect_selected(path, awards, *, limits=None, sources=("usaspending", "fpds"),
                     resume=False, transport=None, profile="live", sleep=time.sleep, progress=None):
    limits = limits or CollectionLimits()
    plan = make_plan(tuple(awards), limits, tuple(sources), profile)
    if transport is None:
        if profile != "live":
            raise EvidenceError("explicit_fixture_transport_required")
        transport = HTTPTransport(limits.to_dict())
    tasks = []
    returned_total = 0
    processed_requests = 0
    record_slots = 0
    with CollectionStore(path, plan, resume=resume) as store:
        try:
            for award_index, award in enumerate(plan["awards"]):
                for source in sources:
                    task = {"award_index": award_index, "source": source, "pages": 0, "returned_rows": 0,
                            "unique_retrieval_rows": 0, "duplicate_retrieval_rows": 0,
                            "action_context_counts": {}, "pagination": "unknown", "query_scope": "unknown",
                            "history": "unknown", "freshness": "unknown", "source_wide": "unknown",
                            "status": "not_requested", "error_code": None, "source_updates_raw": [],
                            "limitations": ["explicit_selection_not_authoritative_cross_source_identity",
                                            "pagination_does_not_establish_history", "publication_delays_unknown"]}
                    tasks.append(task)
                    needed = ("generated_id",) if source == "usaspending" else ("piid", "agency_id")
                    if any(award[k] is None for k in needed) or (source == "fpds" and (award["parent_piid"] is None) != (award["parent_agency_id"] is None)):
                        task.update(status="unresolved_identifiers", error_code="missing_selection_context")
                        continue
                    same_key = [a for a in plan["awards"] if (a["piid"], a["agency_id"]) == (award["piid"], award["agency_id"])]
                    if source == "fpds" and len(same_key) > 1:
                        task.update(status="ambiguous_selection", error_code="reused_piid_agency_selection")
                        continue
                    remaining = limits.max_records_total - record_slots
                    size = min(limits.page_size, limits.max_records_per_source_award, remaining) if source == "usaspending" else 10
                    seen_pages, seen_rows, seen_requests, parent_contexts = set(), set(), set(), set()
                    following = None
                    for page in range(1, limits.max_pages + 1):
                        if (size < 1 or task["returned_rows"] + size > limits.max_records_per_source_award
                                or record_slots + size > limits.max_records_total):
                            task.update(status="truncated", error_code="record_limit", pagination="partial", query_scope="partial")
                            break
                        base = request_for(source, award, page, size, following)
                        key = digest(base)
                        if key in seen_requests:
                            task.update(status="source_error", error_code="repeated_page_request", pagination="partial", query_scope="partial")
                            break
                        seen_requests.add(key)
                        successful = None
                        for attempt in range(limits.retries + 1):
                            if record_slots + size > limits.max_records_total:
                                task.update(status="truncated", error_code="record_request_budget", pagination="partial", query_scope="partial")
                                break
                            request = {**base, "task_index": len(tasks) - 1, "page_index": page, "attempt_index": attempt}
                            saved = store.saved(request)
                            live_request = saved is None
                            if saved is None:
                                if len(store.state["events"]) >= limits.max_requests:
                                    task.update(status="truncated", error_code="request_limit", pagination="partial", query_scope="partial")
                                    break
                                if store.state["events"] and limits.pace_seconds:
                                    sleep(limits.pace_seconds)
                                store.reserve(request)
                                fields, raw = transport(request, len(store.state["events"]))
                                if raw is not None and len(raw) > limits.max_response_bytes:
                                    raw = raw[:limits.max_response_bytes]
                                    fields = {**fields, "body_complete": False, "error_code": "response_size_limit"}
                                metadata = store.finish(fields, raw)
                                store.cursor += 1
                            else:
                                metadata, raw = saved
                            record_slots += size
                            processed_requests += 1
                            status, error = metadata["status"], metadata["error_code"]
                            if not error and status is not None and 200 <= status < 300 and metadata["body_complete"]:
                                successful = (raw, base)
                                break
                            retryable = error in ("timeout", "connection_error") or error is None and (status == 429 or status is not None and 500 <= status <= 599)
                            delay = retry_delay(metadata, attempt, limits)
                            if not retryable or attempt == limits.retries or delay is None:
                                code = error or ("retry_after_exceeds_bound" if delay is None else f"http_{status}")
                                task.update(status="source_error", error_code=code, pagination="partial", query_scope="partial")
                                break
                            if delay and (live_request or store.cursor == len(store.state["events"])):
                                remaining = delay
                                if not live_request and metadata.get("retrieved_at_utc"):
                                    stamp = datetime.fromisoformat(metadata["retrieved_at_utc"].replace("Z", "+00:00"))
                                    remaining = max(0, delay - (datetime.now(timezone.utc) - stamp).total_seconds())
                                if remaining:
                                    if remaining > limits.max_retry_after_seconds:
                                        task.update(status="source_error", error_code="clock_skew_wait_exceeds_bound", pagination="partial", query_scope="partial")
                                        break
                                    sleep(remaining)
                        if successful is None:
                            break
                        try:
                            parsed = parse_page(source, successful[0], base, award)
                        except (EvidenceError, ValueError, TypeError) as exc:
                            task.update(status="source_error", error_code=exc.code if isinstance(exc, EvidenceError) else "unsupported_response_schema",
                                        pagination="partial", query_scope="partial")
                            break
                        fingerprints = parsed["fingerprints"]
                        page_hash = digest(fingerprints)
                        # Retain/count the returned response, but do not add a
                        # repeated page to the unique retrieval-row count.
                        task["pages"] += 1
                        task["returned_rows"] += len(parsed["rows"])
                        returned_total += len(parsed["rows"])
                        for row_hash, context, row in zip(fingerprints, parsed["contexts"], parsed["rows"]):
                            task["duplicate_retrieval_rows"] += int(row_hash in seen_rows)
                            seen_rows.add(row_hash)
                            task["action_context_counts"][context] = task["action_context_counts"].get(context, 0) + 1
                            if source == "fpds":
                                parent_contexts.add(digest(row["parent_context"]))
                        task["unique_retrieval_rows"] = len(seen_rows)
                        task["source_updates_raw"] = sorted(set(task["source_updates_raw"] + parsed["source_updates"]))
                        if fingerprints and page_hash in seen_pages:
                            task.update(status="source_error", error_code="repeated_page_content", pagination="partial", query_scope="partial")
                            break
                        seen_pages.add(page_hash)
                        if progress:
                            progress({"award_index": award_index, "source": source, "page": page, "returned_rows": task["returned_rows"]})
                        if not parsed["has_next"]:
                            task.update(status="pagination_exhausted", pagination="complete", query_scope="complete")
                            if any(k != "query_bound_candidate" for k in task["action_context_counts"]):
                                task.update(status="context_unresolved", query_scope="partial")
                            if source == "fpds" and len(parent_contexts) > 1:
                                task.update(status="ambiguous_award_context", query_scope="partial")
                            if not parsed["rows"] and task["returned_rows"] == 0:
                                task["status"] = "no_records_returned"
                            break
                        following = parsed["next_parameters"]
                        if page == limits.max_pages:
                            task.update(status="truncated", error_code="page_limit", pagination="partial", query_scope="partial")
            if store.cursor != len(store.state["events"]):
                raise EvidenceError("unused_collection_journal_events")
        except KeyboardInterrupt:
            summary = _summary(store, tasks, returned_total, processed_requests, record_slots, interrupted=True)
            store.summary(summary)
            raise
        summary = _summary(store, tasks, returned_total, processed_requests, record_slots)
        store.summary(summary)
        return summary


def _summary(store, tasks, total, processed, record_slots, interrupted=False):
    return {"schema_type": "CollectionSummary", "schema_version": 1,
            "plan_fingerprint": store.fingerprint, "profile": store.plan["profile"],
            "requests_reserved": len(store.state["events"]) + int(store.state["pending"] is not None),
            "responses_preserved": sum(e["body_sha256"] is not None for e in store.state["events"]),
            "returned_rows": total, "processed_requests": processed, "interrupted": interrupted,
            "record_slots_requested": record_slots,
            "tasks": tasks, "historical_completeness": "unknown", "source_freshness": "unknown",
            "limitations": ["bounded_selected_queries_not_census", "no_financial_discrepancy_judgment", "responses_not_atomic_upstream_snapshot"]}
