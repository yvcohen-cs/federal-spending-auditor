"""Opt-in offline C4 CLI: python -m src.match_evidence --help."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime, timezone

from .evidence_io import EvidenceError, canonical, write_report
from .identity_matching import MatchLimits
from .matching_ingestion import match_collection


def human_summary(report):
    counts = report.counts
    lines = ["Identity association only; no financial verification or misconduct inference.",
             f"{len(report.records)} distinct retrieval contents; {report.comparisons} bounded comparison slots."]
    for claim, values in counts.items():
        lines.append(claim + ": " + ", ".join(f"{k}={v}" for k, v in values.items() if v))
    lines.append(f"Excluded artifacts: {len(report.excluded_artifacts)}; history, freshness and query scope unknown.")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Match preserved C3 identities offline; never fetch URLs or compare finances.")
    parser.add_argument("--root", required=True, help="Single flat validated C3 collection")
    parser.add_argument("--output", help="New JSON file outside evidence; otherwise stdout")
    parser.add_argument("--max-records", type=int, default=1000)
    parser.add_argument("--max-candidates", type=int, default=100)
    parser.add_argument("--max-comparisons", type=int, default=10000)
    parser.add_argument("--execution-time", action="store_true")
    args = parser.parse_args(argv)
    try:
        limits = MatchLimits(max_records=args.max_records, max_candidates=args.max_candidates, max_comparisons=args.max_comparisons)
        report = match_collection(args.root, limits=limits)
        if args.execution_time:
            report = replace(report, executed_at_utc=datetime.now(timezone.utc).isoformat())
        payload = canonical({"report": report.to_dict(), "counts": report.counts,
                             "substantive_sha256": report.substantive_sha256, "exit_code": report.exit_code})
        if args.output:
            write_report(args.output, payload, args.root)
        else:
            print(payload)
        print(human_summary(report), file=sys.stderr)
        return report.exit_code
    except KeyboardInterrupt:
        print(canonical({"error_code": "interrupted", "exit_code": 130}))
        return 130
    except EvidenceError as exc:
        print(canonical({"error_code": exc.code, "exit_code": 2}))
        return 2
    except (ValueError, TypeError, KeyError, OSError, RecursionError):
        print(canonical({"error_code": "invalid_matching_input_or_output", "exit_code": 2}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
