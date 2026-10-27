"""Separate append-only C6 review assertions; no authentication/signature claims."""
from __future__ import annotations

import argparse
import fcntl
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .evidence import Schema, _text, _timestamp
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .matching_models import _ComputedIdentity
from .review_packet_models import RecommendedVerificationAction
from .review_packet_io import atomic_create, check_store_location, new_directory, outside

MAX_LOG_BYTES = 16*1024*1024


class WorkflowState(str, Enum):
    PENDING_REVIEW = "pending_review"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    REVIEWED = "reviewed"
    CLOSED = "closed"


@dataclass(frozen=True, kw_only=True)
class ReviewWorkflowEvent(_ComputedIdentity):
    _computed_name = "event_id"
    packet_manifest_sha256: str
    packet_id: str
    claim_id: str
    sequence: int
    previous_event_id: str | None
    state: WorkflowState
    reviewer: str
    notes: str
    timestamp_utc: str
    follow_up: tuple[RecommendedVerificationAction, ...] = ()
    assertion_kind: str = "reviewer_entered_unverified_assertion"

    @property
    def event_id(self):
        return "review-event:v1:" + digest(Schema.to_dict(self))

    def validate(self):
        from .evidence import _hash
        _hash(self.packet_manifest_sha256)
        for value, prefix in ((self.packet_id, "review-packet:v1:"),):
            if not value.startswith(prefix):
                raise ValueError("constructed packet ID required")
            _hash(value.removeprefix(prefix))
        prefix = "identity-claim:v1:" if self.claim_id.startswith("identity-claim:v1:") else "financial-claim:v1:"
        if not self.claim_id.startswith(prefix):
            raise ValueError("C4/C5 claim ID required")
        _hash(self.claim_id.removeprefix(prefix))
        if self.previous_event_id is not None:
            if not self.previous_event_id.startswith("review-event:v1:"):
                raise ValueError("constructed previous event ID required")
            _hash(self.previous_event_id.removeprefix("review-event:v1:"))
        _timestamp(self.timestamp_utc)
        _text(self.reviewer, "reviewer label")
        if len(self.reviewer) > 128 or not self.notes.strip() or len(self.notes) > 4096 or any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in self.notes):
            raise ValueError("bounded reviewer label/plain-text notes required")
        if self.sequence < 0 or len(self.follow_up) > 8 or self.assertion_kind != "reviewer_entered_unverified_assertion":
            raise ValueError("invalid review event")


def validate_events(manifest, events):
    if len(events) > 1000:
        raise EvidenceError("review_event_limit")
    packets = {p.packet_id: p for p in manifest.packets}
    states = {}
    transitions = {None: {WorkflowState.PENDING_REVIEW},
        WorkflowState.PENDING_REVIEW: {WorkflowState.PENDING_REVIEW, WorkflowState.NEEDS_MORE_EVIDENCE, WorkflowState.REVIEWED},
        WorkflowState.NEEDS_MORE_EVIDENCE: {WorkflowState.NEEDS_MORE_EVIDENCE, WorkflowState.PENDING_REVIEW, WorkflowState.REVIEWED},
        WorkflowState.REVIEWED: {WorkflowState.REVIEWED, WorkflowState.NEEDS_MORE_EVIDENCE, WorkflowState.CLOSED},
        WorkflowState.CLOSED: set()}
    previous = None
    timestamp = None
    context_hash = manifest.substantive_sha256
    for index, event in enumerate(events):
        packet = packets.get(event.packet_id)
        if event.sequence != index or event.previous_event_id != previous or event.packet_manifest_sha256 != context_hash or packet is None or event.claim_id != packet.claim.claim_id:
            raise EvidenceError("review_event_context_or_chain_conflict")
        if event.state not in transitions[states.get(event.packet_id)]:
            raise EvidenceError("invalid_review_state_transition")
        stamp = datetime.fromisoformat(event.timestamp_utc.replace("Z", "+00:00"))
        if timestamp is not None and stamp < timestamp:
            raise EvidenceError("review_event_time_order_conflict")
        known = {c.citation_id for c in packet.citations}
        if any(c not in known for a in event.follow_up for c in a.citation_ids):
            raise EvidenceError("unknown_review_follow_up_citation")
        states[event.packet_id], previous, timestamp = event.state, event.event_id, stamp


def _read(root, manifest):
    paths = root.discover()
    snapshots = {p: root.read(p) for p in paths}
    if sum(len(s.data) for s in snapshots.values()) > MAX_LOG_BYTES:
        raise EvidenceError("review_log_size_limit")
    if "review-context.json" not in snapshots:
        raise EvidenceError("incomplete_review_log_context")
    context = strict_json(snapshots["review-context.json"].data)
    expected = {"schema_type": "ReviewLogContext", "schema_version": 1, "packet_manifest_sha256": manifest.substantive_sha256}
    if canonical(context) != canonical(expected):
        raise EvidenceError("incompatible_review_log_context")
    event_names = tuple(p for p in paths if p != "review-context.json")
    if event_names != tuple(f"review-event-{i:06d}.json" for i in range(len(event_names))):
        raise EvidenceError("partial_extra_or_missing_review_events")
    events = tuple(ReviewWorkflowEvent.from_dict(strict_json(snapshots[n].data)) for n in event_names)
    validate_events(manifest, events)
    for path, before in snapshots.items():
        after = root.read(path, recheck=True)
        if before.stamp != after.stamp or before.byte_sha256 != after.byte_sha256:
            raise EvidenceError("review_log_changed")
    if root.discover() != paths:
        raise EvidenceError("review_log_changed")
    return events


def read_events(path, manifest):
    with EvidenceRoot(path, max_bytes=65536, max_total_bytes=MAX_LOG_BYTES, max_files=1001) as root:
        fcntl.flock(root.fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return _read(root, manifest)


def append_event(path, manifest, *, packet_id, state, reviewer, notes, timestamp_utc,
                 protected, follow_up=()):
    target = outside(path, protected)
    check_store_location(target)
    packet = next((p for p in manifest.packets if p.packet_id == packet_id), None)
    if packet is None:
        raise EvidenceError("unknown_review_packet")

    def prepare(events):
        event = ReviewWorkflowEvent(packet_manifest_sha256=manifest.substantive_sha256, packet_id=packet_id,
            claim_id=packet.claim.claim_id, sequence=len(events), previous_event_id=events[-1].event_id if events else None,
            state=state, reviewer=reviewer, notes=notes, timestamp_utc=timestamp_utc, follow_up=follow_up)
        validate_events(manifest, events + (event,))
        raw = (event.to_json() + "\n").encode()
        if len(raw) > 65536:
            raise EvidenceError("review_event_size_limit")
        return event, raw

    if not target.exists():
        prepare(())
        new_directory(target)
    # Three full scans share this reader. Enforce the logical 16 MiB history
    # bound per scan, separately from cumulative IO accounting.
    with EvidenceRoot(target, max_bytes=65536, max_total_bytes=4*MAX_LOG_BYTES, max_files=1001) as root:
        fcntl.flock(root.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not root.discover():
            prepare(())
            atomic_create(root.fd, "review-context.json", (canonical({"schema_type": "ReviewLogContext", "schema_version": 1,
                          "packet_manifest_sha256": manifest.substantive_sha256}) + "\n").encode())
        events = _read(root, manifest)
        event, raw = prepare(events)
        # Revalidate old bytes immediately before exclusive publication.
        if _read(root, manifest) != events:
            raise EvidenceError("review_log_changed")
        if sum(len(root.read(n, recheck=True).data) for n in root.discover()) + len(raw) > MAX_LOG_BYTES:
            raise EvidenceError("review_log_size_limit")
        atomic_create(root.fd, f"review-event-{len(events):06d}.json", raw)
        if _read(root, manifest) != events + (event,):
            raise EvidenceError("review_log_changed")
    return event


def main(argv=None):
    parser = argparse.ArgumentParser(description="Append a separate unauthenticated review assertion; never change evidence/findings.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--packet-bundle", required=True)
    parser.add_argument("--review-dir", required=True)
    parser.add_argument("--packet-id", required=True)
    parser.add_argument("--state", required=True, choices=[s.value for s in WorkflowState])
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--note", required=True)
    parser.add_argument("--timestamp", help="Explicit UTC event time; otherwise actual append time")
    parser.add_argument("--follow-up", action="append", default=[])
    parser.add_argument("--identity-report")
    parser.add_argument("--financial-report")
    args = parser.parse_args(argv)
    try:
        from .review_packet_io import read_bundle
        from .review_packet_builder import build_packets
        manifest, _ = read_bundle(args.packet_bundle)
        fresh = build_packets(args.root, claim_ids=manifest.selected_claim_ids, max_claims=1000,
                              identity_report=args.identity_report, financial_report=args.financial_report)
        if fresh.substantive_sha256 != manifest.substantive_sha256:
            raise EvidenceError("stale_review_packet_bundle")
        event = append_event(args.review_dir, manifest, packet_id=args.packet_id, state=WorkflowState(args.state),
            reviewer=args.reviewer, notes=args.note, timestamp_utc=args.timestamp or datetime.now(timezone.utc).isoformat(),
            protected=(args.root, args.packet_bundle), follow_up=tuple(RecommendedVerificationAction(instruction=s) for s in args.follow_up))
        print(event.to_json())
        return 0
    except KeyboardInterrupt:
        print(canonical({"error_code": "interrupted", "exit_code": 130}))
        return 130
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        print(canonical({"error_code": exc.code if isinstance(exc, EvidenceError) else "invalid_review_event_or_storage", "exit_code": 2}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
