"""Predeclared v1 diversity selection, not probability sampling or identity inference."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .evidence import Schema, _hash, _text
from .evidence_io import canonical, digest
from .federal_spending_auditor import API_URL

VERSION = "pilot-v1"
LIMITATIONS = (
    "Deliberate diversity sample from bounded sorted prefixes; not statistically representative.",
    "Population counts and inclusion probabilities unknown; quotas are not population weights.",
    "Agency/value/modification coverage observed only; no guaranteed allocation of missing strata.",
    "Query periods describe award activity filters, not verified original award dates.",
    "Offset results and source refresh may change; saved frame is not an atomic source snapshot.",
    "Missing modification fields stay unknown; no-modification history cannot be inferred.",
)


@dataclass(frozen=True, kw_only=True)
class PilotConfig(Schema):
    mode: str
    target: int = 24
    seed: str = "phase4a-v1"
    frame_limit: int = 10
    max_response_bytes: int = 1024 * 1024
    max_run_bytes: int = 512 * 1024 * 1024
    version: str = VERSION
    implementation_sha256: str

    def validate(self):
        _hash(self.implementation_sha256)
        _text(self.seed, "seed")
        if self.version != VERSION or self.mode not in ("live", "synthetic"):
            raise ValueError("explicit pilot mode/version required")
        if not 1 <= self.target <= 30 or len(self.seed) > 128 or not 1 <= self.frame_limit <= 10:
            raise ValueError("pilot selection bounds")
        if not 1024 <= self.max_response_bytes <= 1024*1024 or not 1024 <= self.max_run_bytes <= 512*1024*1024:
            raise ValueError("pilot storage bounds")


def frame_requests(config):
    fields = ["Award ID", "Award Amount", "Awarding Agency", "Start Date",
              "Contract Award Type", "generated_internal_id"]
    return [{"source": "usaspending", "endpoint": API_URL, "method": "POST", "parameters": {
        "filters": {"time_period": [{"start_date": f"{fy-1}-10-01", "end_date": f"{fy}-09-30"}],
                    "award_type_codes": [kind]}, "fields": fields,
        "sort": "Award ID", "order": "asc", "page": 1, "limit": config.frame_limit}}
        for fy in (2024, 2025) for kind in ("A", "B", "C", "D")]


def text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256 or any(ord(c)<32 or ord(c)==127 for c in value):
        return None
    return value  # Never coerce identifiers/names or strip punctuation/zeros.


def amount_band(raw):
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return "unknown"
    try:
        d = Decimal(str(raw))
    except InvalidOperation:
        return "unknown"
    if not d.is_finite():
        return "unknown"
    return "negative" if d<0 else "under_100k" if d<100000 else "100k_to_1m" if d<1000000 else "1m_plus"


def select_sample(rows, config):
    """Rows are normalized frame candidates with preserved source-row references."""
    grouped = defaultdict(list)
    excluded = defaultdict(int)
    for row in rows:
        identifier = text(row.get("generated_id"))
        if identifier is None or not row.get("frame_ref"):
            excluded["missing_identifier_or_provenance"] += 1
        else:
            grouped[identifier].append(row)
    strata = defaultdict(list)
    for identifier, occurrences in sorted(grouped.items()):
        # Search-period overlap is ordinary. Conflicting actual row content is not
        # silently resolved; query membership alone is not a content conflict.
        if len({digest(o["source_row"]) for o in occurrences}) != 1:
            excluded["conflicting_generated_identifier"] += len(occurrences)
            continue
        row = min(occurrences, key=canonical)
        periods = sorted({o["period"] for o in occurrences})
        row = {**row, "period": periods[0], "frame_refs": sorted({o["frame_ref"] for o in occurrences})}
        key = (row["agency"], row["kind"], row["period"], row["value_band"], row["modifications"])
        strata[key].append(row)
        excluded["duplicate_occurrences"] += len(occurrences)-1
    queues = {k: deque(sorted(v, key=lambda r: (digest([config.seed,r["generated_id"]]),r["generated_id"]))) for k,v in sorted(strata.items())}
    selected = []
    while len(selected)<config.target and any(queues.values()):
        for k,q in queues.items():
            if q and len(selected)<config.target:
                selected.append({**q.popleft(),"stratum":list(k)})
    return {"schema_type":"PilotSample", "schema_version":1, "version":VERSION,
            "target":config.target, "seed":config.seed, "eligible_unique":sum(len(v) for v in strata.values()),
            "frame_rows":len(rows), "selected":selected, "exclusions":dict(sorted(excluded.items())),
            "strata":[{"key":list(k),"eligible":len(v),"selected":sum(s["stratum"]==list(k) for s in selected)} for k,v in sorted(strata.items())],
            "limitations":list(LIMITATIONS), "population_total":None, "selection":"seeded_hash_round_robin_observed_strata"}
