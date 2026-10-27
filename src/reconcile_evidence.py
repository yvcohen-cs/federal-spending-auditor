"""Opt-in C5 offline financial reconciliation: python -m src.reconcile_evidence."""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime, timezone

from .evidence_io import EvidenceError, canonical, write_report
from .financial_ingestion import reconcile_collection
from .financial_models import FinancialLimits


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare compatible observed action obligations offline; no collection or misconduct inference.")
    parser.add_argument("--root", required=True, help="Single flat preserved C3 collection")
    parser.add_argument("--identity-report", help="Optional prior C4 report outside evidence; revalidated against actual C3 bytes")
    parser.add_argument("--output", help="New JSON report outside evidence; otherwise stdout")
    parser.add_argument("--max-observations", type=int, default=5000)
    parser.add_argument("--max-comparison-work", type=int, default=20000)
    parser.add_argument("--execution-time", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = reconcile_collection(args.root, identity_report_path=args.identity_report,
                      limits=FinancialLimits(max_observations=args.max_observations, max_comparison_work=args.max_comparison_work))
        if args.execution_time:
            report = replace(report, executed_at_utc=datetime.now(timezone.utc).isoformat())
        payload = canonical({"report": report.to_dict(), "counts": report.counts,
                             "substantive_sha256": report.substantive_sha256, "exit_code": report.exit_code})
        if args.output:
            write_report(args.output, payload, args.root)
        else:
            print(payload)
        print("Observed action-value reconciliation only; no financial-history assurance or misconduct inference.", file=sys.stderr)
        print(", ".join(f"{k}={v}" for k, v in report.counts.items() if v) or "No eligible subject claims.", file=sys.stderr)
        print("History, source revision alignment and freshness remain unknown; no history totals computed.", file=sys.stderr)
        return report.exit_code
    except KeyboardInterrupt:
        print(canonical({"error_code": "interrupted", "exit_code": 130}))
        return 130
    except EvidenceError as exc:
        print(canonical({"error_code": exc.code, "exit_code": 2}))
        return 2
    except (ValueError, TypeError, KeyError, IndexError, OSError, RecursionError):
        print(canonical({"error_code": "invalid_financial_input_or_output", "exit_code": 2}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
