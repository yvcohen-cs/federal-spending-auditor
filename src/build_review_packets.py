"""Opt-in offline C6 JSON/HTML packet bundles."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone

from .evidence_io import EvidenceError, canonical
from .review_packet_builder import build_packets, validate_packet_sources
from .review_packet_html import render_html
from .review_packet_io import outside, write_bundle
from .review_events import read_events


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build offline evidence-linked review packets; no network or misconduct inference.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--identity-report")
    parser.add_argument("--financial-report")
    parser.add_argument("--output-dir", required=True, help="New directory outside evidence and review logs")
    parser.add_argument("--claim-id", action="append")
    parser.add_argument("--max-claims", type=int, default=100)
    parser.add_argument("--max-output-bytes", type=int, default=8*1024*1024)
    parser.add_argument("--review-dir", help="Read existing separate review history; never append during rendering")
    parser.add_argument("--generation-time", action="store_true")
    args = parser.parse_args(argv)
    try:
        manifest = build_packets(args.root, identity_report=args.identity_report, financial_report=args.financial_report,
                                claim_ids=args.claim_id, max_claims=args.max_claims)
        if args.generation_time:
            manifest = replace(manifest, generated_at_utc=datetime.now(timezone.utc).isoformat())
        if args.review_dir:
            outside(args.review_dir, (args.root, args.output_dir))
        events = read_events(args.review_dir, manifest) if args.review_dir else ()
        protected = (args.root,) + ((args.review_dir,) if args.review_dir else ())
        html = render_html(manifest, events, max_bytes=args.max_output_bytes)
        validate_packet_sources(args.root, manifest)
        write_bundle(args.output_dir, manifest, html, events,
                     protected=protected, max_output_bytes=args.max_output_bytes)
        print(canonical({"selected_claims": len(manifest.packets), "available_claims": manifest.total_available_claims,
                         "substantive_sha256": manifest.substantive_sha256, "exit_code": manifest.exit_code}))
        return manifest.exit_code
    except KeyboardInterrupt:
        print(canonical({"error_code": "interrupted", "exit_code": 130}))
        return 130
    except (OSError, ValueError, TypeError, KeyError, IndexError, RecursionError) as exc:
        print(canonical({"error_code": exc.code if isinstance(exc, EvidenceError) else "invalid_review_input_or_output", "exit_code": 2}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
