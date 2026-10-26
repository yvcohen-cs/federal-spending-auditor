"""Opt-in offline evidence validation: python -m src.verify_evidence --help."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from dataclasses import replace
from .evidence_ingestion import inspect_directory
from .evidence_io import EvidenceError, canonical, write_report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate preserved evidence offline; no collection or financial verification.")
    parser.add_argument("--root", required=True, help="Explicit trusted evidence directory (no symlinks)")
    parser.add_argument("--manifest", help="Previously produced manifest, relative to the evidence root")
    parser.add_argument("--output", help="New JSON report path outside evidence; existing files are refused")
    parser.add_argument("--max-artifact-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--max-total-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--execution-time", action="store_true", help="Include execution UTC timestamp, excluded from substantive hash")
    args = parser.parse_args(argv)
    try:
        report = inspect_directory(args.root,
                                   manifest_path=args.manifest,
                                   max_bytes=args.max_artifact_bytes,
                                   max_total_bytes=args.max_total_bytes)
        if args.execution_time:
            report = replace(report, executed_at_utc=datetime.now(timezone.utc).isoformat())
        payload = canonical({"manifest": report.to_dict(), "summary": report.summary,
                             "substantive_sha256": report.substantive_sha256,
                             "exit_code": report.exit_code})
        if args.output:
            write_report(args.output, payload, args.root)
        else:
            print(payload)
        return report.exit_code
    except KeyboardInterrupt:
        print(canonical({"error_code": "interrupted", "exit_code": 130}))
        return 130
    except (EvidenceError, ValueError, TypeError):
        # No untrusted values or OS exception details in errors.
        print(canonical({"error_code": "invalid_manifest_or_arguments_or_output", "exit_code": 2}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
