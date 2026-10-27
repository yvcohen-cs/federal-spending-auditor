"""POSIX exclusive atomic files, commit-marked output bundles, bounded reads."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, _directory, canonical, parts, strict_json


def outside(path, protected):
    target = Path(path).absolute()
    for value in protected:
        root = Path(value).absolute()
        if target == root or root in target.parents:
            raise EvidenceError("review_output_inside_protected_directory")
    return target


def atomic_create(fd, name, raw):
    if len(parts(name)) != 1:
        raise EvidenceError("unsafe_review_filename")
    temporary = name + ".partial"
    output = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(output, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
    os.unlink(temporary, dir_fd=fd)
    os.fsync(fd)


def check_store_location(path):
    target = Path(path).absolute()
    for ancestor in (target.parent,) + tuple(target.parent.parents):
        probe = _directory(ancestor)
        try:
            for marker in ("c3_plan.json", "output-manifest.json", "review-context.json"):
                try:
                    os.stat(marker, dir_fd=probe, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise EvidenceError("new_output_inside_existing_evidence_or_review_store")
        finally:
            os.close(probe)


def new_directory(path):
    target = Path(path).absolute()
    check_store_location(target)
    parent = _directory(target.parent)
    try:
        os.mkdir(target.name, 0o700, dir_fd=parent)
        os.fsync(parent)
    finally:
        os.close(parent)


def write_bundle(path, manifest, html, events=(), *, protected=(), max_output_bytes=8*1024*1024):
    target = outside(path, protected)
    if type(max_output_bytes) is not int or not 1024 <= max_output_bytes <= 32*1024*1024:
        raise EvidenceError("invalid_review_output_limit")
    from .review_packet_html import render_html
    if html != render_html(manifest, events, max_bytes=max_output_bytes):
        raise EvidenceError("review_html_not_safe_projection")
    context = manifest.substantive_sha256
    files = {"packets.json": (manifest.to_json() + "\n").encode(), "review.html": html.encode(),
             "review-events.json": (canonical({"schema_type": "ReviewHistory", "schema_version": 1,
               "packet_manifest_sha256": context, "events": [e.to_dict() for e in events]}) + "\n").encode()}
    commit = {"schema_type": "ReviewOutputCommit", "schema_version": 1,
              "files": {n: hashlib.sha256(v).hexdigest() for n, v in files.items()}}
    files["output-manifest.json"] = (canonical(commit) + "\n").encode()
    if sum(len(v) for v in files.values()) > max_output_bytes:
        raise EvidenceError("review_output_size_limit")
    new_directory(target)
    with EvidenceRoot(target, max_bytes=max_output_bytes, max_total_bytes=max_output_bytes) as root:
        # Commit marker last: incomplete outputs remain preserved but unreadable
        # as complete bundles. Individual files become visible atomically.
        for name, raw in files.items():
            atomic_create(root.fd, name, raw)
            if root.read(name, recheck=True).byte_sha256 != hashlib.sha256(raw).hexdigest():
                raise EvidenceError("review_output_changed")
        if root.discover() != tuple(sorted(files)):
            raise EvidenceError("review_output_changed")


def read_bundle(path):
    from .review_packet_models import ReviewPacketManifest
    from .review_events import ReviewWorkflowEvent, validate_events
    from .review_packet_html import render_html
    with EvidenceRoot(path, max_bytes=32*1024*1024, max_total_bytes=32*1024*1024) as root:
        names = ("output-manifest.json", "packets.json", "review-events.json", "review.html")
        if root.discover() != names:
            raise EvidenceError("incomplete_or_extra_review_output")
        snapshots = {n: root.read(n) for n in names}
        commit = strict_json(snapshots["output-manifest.json"].data)
        expected = {"schema_type": "ReviewOutputCommit", "schema_version": 1,
                    "files": {n: s.byte_sha256 for n, s in snapshots.items() if n != "output-manifest.json"}}
        if canonical(commit) != canonical(expected):
            raise EvidenceError("review_output_hash_conflict")
        manifest = ReviewPacketManifest.from_json(snapshots["packets.json"].data.decode())
        history = strict_json(snapshots["review-events.json"].data)
        if set(history) != {"schema_type", "schema_version", "packet_manifest_sha256", "events"} or history["schema_type"] != "ReviewHistory" or type(history["schema_version"]) is not int or history["schema_version"] != 1 or history["packet_manifest_sha256"] != manifest.substantive_sha256:
            raise EvidenceError("invalid_review_history")
        events = tuple(ReviewWorkflowEvent.from_dict(e) for e in history["events"])
        validate_events(manifest, events)
        if snapshots["review.html"].data != render_html(manifest, events).encode():
            raise EvidenceError("review_html_not_safe_projection")
        for n, before in snapshots.items():
            after = root.read(n, recheck=True)
            if before.stamp != after.stamp or before.byte_sha256 != after.byte_sha256:
                raise EvidenceError("review_bundle_changed")
        if root.discover() != names:
            raise EvidenceError("review_bundle_changed")
    return manifest, events
