"""Separate opt-in C3 CLI. Legacy pipeline defaults are untouched."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .collection import CollectionLimits, SelectedAward, collect_selected
from .collection_sources import FixtureTransport
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json


def load_input(path):
    path = Path(path).absolute()
    with EvidenceRoot(path.parent) as root:
        return strict_json(root.read(path.name).data)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded public cross-source collection; no financial comparisons.")
    parser.add_argument("--selection", required=True, help="JSON object with explicit awards array; no name/agency inference")
    parser.add_argument("--run-dir", required=True, help="New evidence directory (parent must exist), or existing directory with --resume")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--sources", nargs="+", choices=("usaspending", "fpds"), default=["usaspending", "fpds"])
    parser.add_argument("--fixture", help="Explicit synthetic response scenario; no network")
    parser.add_argument("--max-awards", type=int, default=3)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("--max-records-per-source-award", type=int, default=10)
    parser.add_argument("--max-records-total", type=int, default=30)
    parser.add_argument("--max-requests", type=int, default=10)
    parser.add_argument("--page-size", type=int, default=10, help="USAspending size; FPDS uses 10")
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--pace-seconds", type=float, default=0.5)
    args = parser.parse_args(argv)
    try:
        selected = load_input(args.selection)
        if not isinstance(selected, dict) or set(selected) != {"awards"} or not isinstance(selected["awards"], list):
            raise EvidenceError("invalid_selection_file")
        awards = [SelectedAward(**value) for value in selected["awards"]]
        limits = CollectionLimits(**{name: getattr(args, name) for name in (
            "max_awards", "max_pages", "max_records_per_source_award", "max_records_total", "max_requests", "page_size", "retries", "timeout_seconds", "pace_seconds")})
        transport, profile = None, "live"
        if args.fixture:
            scenario = load_input(args.fixture)
            transport, profile = FixtureTransport(scenario), "fixture:" + digest(scenario)
        summary = collect_selected(args.run_dir, awards, limits=limits, sources=tuple(args.sources),
                                   resume=args.resume, transport=transport, profile=profile,
                                   sleep=(lambda _: None) if args.fixture else time.sleep,
                                   progress=lambda event: print(canonical(event), file=sys.stderr))
        print(canonical(summary))
        return 0 if all(t["status"] in ("pagination_exhausted", "no_records_returned") for t in summary["tasks"]) else 1
    except KeyboardInterrupt:
        print(canonical({"error_code": "interrupted", "resume_requires_same_plan": True}), file=sys.stderr)
        return 130
    except (EvidenceError, ValueError, TypeError, OSError):
        print(canonical({"error_code": "collection_failed_check_preserved_evidence"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
