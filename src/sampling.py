"""Deterministic, non-probability stratified retrieval with replayable evidence."""
from __future__ import annotations

import calendar
import hashlib
import json
import math
import time
from collections import Counter, deque
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1
LIMITATIONS = (
    "Deterministic Award-ID prefixes within period/type strata are not random or "
    "statistically representative. Inclusion probabilities and population totals are unknown. "
    "Equal quotas are not population weights. Period queries can overlap at award level; "
    "first selected generated award identity wins. Missing generated identities are excluded "
    "from analysis but retained in raw evidence. API data, sort ties and offset pagination can "
    "change during collection; resume replays saved evidence, not an immutable source snapshot. "
    "Agency coverage is observed only, with no guaranteed agency allocation."
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def allocate(total, count):
    """Equal integer quotas; remainder goes to earlier canonical strata."""
    if total < 1 or count < 1:
        raise ValueError("positive target and stratum count required")
    return [total // count + (index < total % count) for index in range(count)]


def make_strata(fiscal_year, period="quarter", award_types=("A", "B", "C", "D")):
    if not 2 <= fiscal_year <= 9998 or period not in ("quarter", "year", "month"):
        raise ValueError("invalid fiscal year or sampling period")
    types = sorted(set(award_types))
    if not types or any(code not in ("A", "B", "C", "D") for code in types):
        raise ValueError("award types must be a nonempty subset of A,B,C,D")
    width = {"quarter": 3, "year": 12, "month": 1}[period]
    strata = []
    for offset in range(0, 12, width):
        year, month = divmod((fiscal_year - 1) * 12 + 9 + offset, 12)
        end_year, end_month = divmod((fiscal_year - 1) * 12 + 9 + offset + width - 1, 12)
        start = f"{year:04d}-{month + 1:02d}-01"
        end = f"{end_year:04d}-{end_month + 1:02d}-{calendar.monthrange(end_year, end_month + 1)[1]}"
        for code in types:
            strata.append({"id": f"{start}_{code}", "filters": {
                "time_period": [{"start_date": start, "end_date": end}],
                "award_type_codes": [code],
            }})
    return strata


def collect(client, fiscal_year=2025, max_records=5000, page_size=100,
            raw_dir=None, page_delay_seconds=None, period="quarter",
            award_types=("A", "B", "C", "D"), max_pages_per_stratum=1000):
    from .federal_spending_auditor import API_URL, AWARD_FIELDS

    if not 1 <= page_size <= 100 or max_records < 1:
        raise ValueError("page_size must be 1..100 and max_records positive")
    if max_pages_per_stratum < 1:
        raise ValueError("max_pages_per_stratum must be positive")
    delay = client.page_delay_seconds if page_delay_seconds is None else page_delay_seconds
    if not math.isfinite(delay) or delay < 0:
        raise ValueError("page delay must be nonnegative")
    strata = make_strata(fiscal_year, period, award_types)
    quotas = allocate(max_records, len(strata))
    # Use only documented field spellings. Legacy mode retains its old request.
    fields = [f for f in AWARD_FIELDS if f not in ("Recipient DUNS", "NAICS Code", "PSC Code")]
    fields += ["Recipient DUNS Number", "NAICS", "PSC", "generated_internal_id", "Last Modified Date"]
    config = {"version": VERSION, "mode": "stratified", "endpoint": API_URL,
              "fiscal_year": fiscal_year, "date_boundaries": [f"{fiscal_year-1}-10-01", f"{fiscal_year}-09-30"],
              "strata": strata, "quotas": quotas, "target": max_records, "fields": fields,
              "max_pages_per_stratum": max_pages_per_stratum, "page_size": page_size, "sort": "Award ID", "order": "asc",
              "page_delay_seconds": delay, "allocation": "equal_then_canonical_round_robin",
              "identity": "generated_internal_id; missing excluded; first occurrence wins",
              "selection": "deterministic_prefix", "population_total": None}
    fingerprint = digest(config)
    root = Path(raw_dir) if raw_dir is not None else None
    checkpoint = {"version": VERSION, "query_fingerprint": fingerprint, "events": [], "complete": False}
    if root:
        path = root / "checkpoint.json"
        if path.exists():
            try:
                checkpoint = json.loads(path.read_text())
                if (checkpoint["version"] != VERSION or checkpoint["query_fingerprint"] != fingerprint
                        or not isinstance(checkpoint["events"], list)
                        or type(checkpoint["complete"]) is not bool):
                    raise ValueError("Checkpoint query differs or checkpoint is corrupt")
                metadata = json.loads((root / "query_metadata.json").read_text())
                if any(metadata.get(key) != value for key, value in config.items()) or metadata.get("query_fingerprint") != fingerprint:
                    raise ValueError("Checkpoint query metadata is corrupt")
                for event in checkpoint["events"]:
                    if type(event["step"]) is not int or event["step"] < 0:
                        raise ValueError("Corrupt checkpoint event")
                    saved = root / f"response_{event['step']:06d}.json"
                    if digest(json.loads(saved.read_text())) != event["sha256"]:
                        raise ValueError("Checkpoint raw evidence hash differs")
                if [e["step"] for e in checkpoint["events"]] != list(range(len(checkpoint["events"]))):
                    raise ValueError("Checkpoint events are not contiguous")
            except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
                raise ValueError("Corrupt or missing checkpoint evidence") from exc
        elif root.exists() and any(root.iterdir()):
            raise ValueError("Nonempty raw directory has no checkpoint; refusing to overwrite evidence")
        root.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            client._write_json_atomic(path, checkpoint)
            client._write_json_atomic(root / "query_metadata.json", {**config, "query_fingerprint": fingerprint, "created_at_utc": now()})

    selected, identities = [], set()
    states = [{"definition": s, "initial_quota": q, "collected": 0, "pages": [],
               "rows_observed": 0, "duplicates": 0, "missing_identifiers": 0,
               "exhausted": False, "buffer": deque(), "page_hashes": set()}
              for s, q in zip(strata, quotas)]
    step = 0
    active_stratum = None
    pending_request = None

    def persist_summary(complete, error=None):
        summary = {"config": config, "query_fingerprint": fingerprint, "updated_at_utc": now(),
                   "complete": complete, "error": error,
                   "failure_stratum": active_stratum if error else None,
                   "failed_request": pending_request if error else None, "requested": max_records,
                   "collected": len(selected), "target_met": len(selected) == max_records,
                   "population_total": None, "limitations": LIMITATIONS,
                   "observed_agencies": dict(Counter(str(r.get("Awarding Agency") or "missing") for r in selected)),
                   "strata": [{**{k: v for k, v in s.items() if k not in ("buffer", "page_hashes")},
                               "buffered_rows": len(s["buffer"]),
                               "truncated": bool(s["buffer"]) or not s["exhausted"]} for s in states]}
        client.last_sampling_summary = summary
        if root:
            client._write_json_atomic(root / "sampling_coverage.json", summary)
        return summary

    def take(state):
        nonlocal step, active_stratum, pending_request
        active_stratum = state["definition"]["id"]
        while True:
            while state["buffer"]:
                row = state["buffer"].popleft()
                identity = row.get("generated_internal_id")
                if not isinstance(identity, str) or not identity.strip():
                    continue
                if identity in identities:
                    state["duplicates"] += 1
                    continue
                identities.add(identity)
                selected.append(row)
                state["collected"] += 1
                return True
            if state["exhausted"]:
                return False
            if len(state["pages"]) >= max_pages_per_stratum:
                raise ValueError("Stratum page safety limit reached; collection incomplete")
            payload = {"filters": state["definition"]["filters"], "fields": fields,
                       "sort": "Award ID", "order": "asc", "page": len(state["pages"]) + 1,
                       "limit": page_size}
            pending_request = payload
            events = checkpoint["events"]
            saved_path = root / f"response_{step:06d}.json" if root else None
            if step < len(events):
                event = events[step]
                envelope = json.loads(saved_path.read_text())
            elif saved_path and saved_path.exists():
                # A crash after evidence write but before checkpoint commit: adopt exactly once.
                envelope = json.loads(saved_path.read_text())
            else:
                if checkpoint["complete"]:
                    raise ValueError("Complete checkpoint is inconsistent with replay")
                if step and delay:
                    time.sleep(delay)
                body = client._post(payload)
                envelope = {"request": payload, "retrieved_at_utc": now(), "response": body}
                if root:
                    client._write_json_atomic(saved_path, envelope)
            if envelope.get("request") != payload:
                raise ValueError("Checkpoint request differs from deterministic replay")
            body = envelope["response"]
            rows = body.get("results")
            metadata = body.get("page_metadata")
            if (not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows)
                    or len(rows) > page_size or not isinstance(metadata, dict)
                    or type(metadata.get("hasNext")) is not bool
                    or ("page" in metadata and metadata["page"] != payload["page"])
                    or (not rows and metadata["hasNext"])):
                raise ValueError("Invalid pagination response; raw evidence retained")
            row_hash = digest(rows)
            if rows and row_hash in state["page_hashes"]:
                raise ValueError("Repeated page; refusing silent pagination loop")
            state["page_hashes"].add(row_hash)
            if step == len(events):
                events.append({"step": step, "sha256": digest(envelope)})
                if root:
                    client._write_json_atomic(root / "checkpoint.json", checkpoint)
            state["pages"].append({"request": payload, "page_metadata": metadata,
                                   "retrieved_at_utc": envelope["retrieved_at_utc"],
                                   "raw_file": f"response_{step:06d}.json", "rows": len(rows),
                                   "source_last_modified_values": sorted({str(r["Last Modified Date"]) for r in rows if r.get("Last Modified Date")})})
            state["missing_identifiers"] += sum(not isinstance(r.get("generated_internal_id"), str) or not r["generated_internal_id"].strip() for r in rows)
            state["rows_observed"] += len(rows)
            state["buffer"].extend(rows)
            state["exhausted"] = not metadata["hasNext"]
            step += 1
            pending_request = None

    try:
        for state, quota in zip(states, quotas):
            for _ in range(quota):
                if not take(state):
                    break
        while len(selected) < max_records:
            progress = False
            for state in states:
                if len(selected) == max_records:
                    break
                progress = take(state) or progress
            if not progress:
                break
        if step != len(checkpoint["events"]):
            raise ValueError("Checkpoint contains unused events")
        checkpoint["complete"] = True
        if root:
            client._write_json_atomic(root / "checkpoint.json", checkpoint)
        persist_summary(True)
        return selected
    except Exception as exc:
        persist_summary(False, type(exc).__name__)
        raise


def write_coverage_report(summary, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Sampling and coverage", "", f"Collected {summary['collected']} / {summary['requested']} requested awards.",
             f"Collection complete: {summary['complete']}; population total: unknown.", "", LIMITATIONS, "",
             "| Stratum | Initial quota | Collected | Observed rows | Duplicate rows | Missing IDs | Truncated |",
             "|---|---:|---:|---:|---:|---:|---|"]
    for s in summary["strata"]:
        lines.append(f"| {s['definition']['id']} | {s['initial_quota']} | {s['collected']} | {s['rows_observed']} | {s['duplicates']} | {s['missing_identifiers']} | {s['truncated']} |")
    lines += ["", "Full query, pagination, timestamps and coverage provenance: sampling_coverage.json in the raw run directory.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
