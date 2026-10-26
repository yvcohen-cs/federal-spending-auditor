"""POSIX, single-writer, append-only response journal for opt-in C3 runs."""
from __future__ import annotations

import fcntl
import hashlib
import os
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, _directory, canonical, digest, parts, strict_json


class CollectionStore:
    def __init__(self, path, plan, *, resume=False):
        self.path, self.plan, self.resume = Path(path).absolute(), plan, resume
        self.fingerprint = digest(plan)
        self.reader = None
        self.cursor = 0

    def __enter__(self):
        if not self.resume:
            parent = _directory(self.path.parent)
            try:
                os.mkdir(self.path.name, 0o700, dir_fd=parent)
                os.fsync(parent)
            finally:
                os.close(parent)
        self.reader = EvidenceRoot(self.path, max_bytes=16 * 1024 * 1024,
                                   max_total_bytes=512 * 1024 * 1024, max_files=40000)
        self.reader.__enter__()
        try:
            fcntl.flock(self.reader.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.resume:
                saved = self.json("c3_plan.json")
                if saved != self.plan:
                    raise EvidenceError("incompatible_collection_plan")
                try:
                    self.state = self.json("c3_checkpoint.json")
                except EvidenceError as exc:
                    if exc.code != "missing_file" or set(self.reader.discover()) != {"c3_plan.json"}:
                        raise
                    # No request could have been reserved before initialization.
                    self.state = {"schema_version": 1, "schema_type": "CollectionCheckpoint",
                                  "fingerprint": self.fingerprint, "events": [], "pending": None}
                    self._replace_json("c3_checkpoint.json", self.state)
                self._validate_state()
            else:
                self._create_json("c3_plan.json", self.plan)
                self.state = {"schema_version": 1, "schema_type": "CollectionCheckpoint",
                              "fingerprint": self.fingerprint, "events": [], "pending": None}
                self._replace_json("c3_checkpoint.json", self.state)
            self._recover()
            return self
        except BaseException:
            self.reader.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        if self.reader:
            self.reader.__exit__(*exc)

    def json(self, name):
        return strict_json(self.reader.read(name, recheck=True).data)

    def _root_check(self):
        probe = _directory(self.path)
        try:
            a, b = os.fstat(probe), os.fstat(self.reader.fd)
            if (a.st_dev, a.st_ino) != (b.st_dev, b.st_ino):
                raise EvidenceError("collection_root_changed")
        finally:
            os.close(probe)

    def _write_temp(self, name, raw):
        parts(name)
        self._root_check()
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=self.reader.fd)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def _create(self, name, raw):
        temporary = name + ".partial"
        self._write_temp(temporary, raw)
        os.link(temporary, name, src_dir_fd=self.reader.fd,
                dst_dir_fd=self.reader.fd, follow_symlinks=False)
        os.unlink(temporary, dir_fd=self.reader.fd)
        os.fsync(self.reader.fd)

    def _create_json(self, name, value):
        self._create(name, (canonical(value) + "\n").encode())

    def _replace_json(self, name, value):
        if name in self.reader.discover():
            self.reader.read(name, recheck=True)  # Reject linked/nonregular targets.
        temporary = name + ".next"
        self._write_temp(temporary, (canonical(value) + "\n").encode())
        self._root_check()
        os.replace(temporary, name, src_dir_fd=self.reader.fd, dst_dir_fd=self.reader.fd)
        os.fsync(self.reader.fd)

    def _validate_state(self):
        state = self.state
        if (not isinstance(state, dict) or set(state) != {"schema_version", "schema_type", "fingerprint", "events", "pending"}
                or type(state["schema_version"]) is not int or state["schema_version"] != 1
                or state["schema_type"] != "CollectionCheckpoint" or state["fingerprint"] != self.fingerprint
                or not isinstance(state["events"], list) or len(state["events"]) > self.plan["limits"]["max_requests"]):
            raise EvidenceError("invalid_collection_checkpoint")
        for index, event in enumerate(state["events"]):
            if not isinstance(event, dict) or set(event) != {"sequence", "metadata_sha256", "body_sha256"} or type(event["sequence"]) is not int or event["sequence"] != index:
                raise EvidenceError("invalid_collection_checkpoint")
            metadata = self.json(f"c3_attempt_{index:06d}.json")
            if digest(metadata) != event["metadata_sha256"] or metadata.get("sequence") != index or metadata.get("fingerprint") != self.fingerprint:
                raise EvidenceError("collection_metadata_hash_mismatch")
            if metadata.get("body_sha256") != event["body_sha256"]:
                raise EvidenceError("collection_body_hash_mismatch")
            self._verify_body(index, metadata)
        pending = state["pending"]
        if pending is not None and (not isinstance(pending, dict) or set(pending) != {"sequence", "request"}
                                    or type(pending["sequence"]) is not int or pending["sequence"] != len(state["events"])
                                    or len(state["events"]) >= self.plan["limits"]["max_requests"]):
            raise EvidenceError("invalid_pending_reservation")

    def _verify_body(self, index, metadata):
        from .collection_ingestion import validate_control
        validate_control(f"c3_attempt_{index:06d}.json", metadata)
        sha = metadata.get("body_sha256")
        if sha is not None:
            raw = self.reader.read(f"c3_attempt_{index:06d}.body", recheck=True).data
            if hashlib.sha256(raw).hexdigest() != sha:
                raise EvidenceError("collection_body_hash_mismatch")

    def _recover(self):
        allowed = {"c3_plan.json", "c3_checkpoint.json", "c3_summary.json"}
        for index in range(len(self.state["events"])):
            allowed.add(f"c3_attempt_{index:06d}.json")
            if self.state["events"][index]["body_sha256"] is not None:
                allowed.add(f"c3_attempt_{index:06d}.body")
        pending = self.state["pending"]
        if pending:
            index = pending["sequence"]
            allowed.update((f"c3_attempt_{index:06d}.json", f"c3_attempt_{index:06d}.body"))
        actual = set(self.reader.discover())
        if not actual <= allowed:
            raise EvidenceError("unexpected_or_partial_collection_files")
        if "c3_summary.json" in actual:
            from .collection_ingestion import validate_control
            validate_control("c3_summary.json", self.json("c3_summary.json"))
        if pending:
            name = f"c3_attempt_{pending['sequence']:06d}.json"
            if name in actual:
                metadata = self.json(name)
                if (metadata.get("request") != pending["request"] or metadata.get("sequence") != pending["sequence"]
                        or metadata.get("fingerprint") != self.fingerprint):
                    raise EvidenceError("orphan_metadata_conflict")
                self._verify_body(pending["sequence"], metadata)
                self._commit(metadata)
            elif f"c3_attempt_{pending['sequence']:06d}.body" in actual:
                raise EvidenceError("incomplete_preserved_observation")
            else:
                # Sending may have happened. Consume its reservation, never
                # silently replay an uncertain request after a process crash.
                self.finish({"error_code": "interrupted_request_outcome_unknown", "status": None,
                             "retrieved_at_utc": None, "body_complete": False,
                             "retry_after": None, "source_update_raw": None}, None)

    def reserve(self, request):
        if self.state["pending"] is not None:
            raise EvidenceError("unresolved_pending_request")
        pending = {"sequence": len(self.state["events"]), "request": request}
        self.state = {**self.state, "pending": pending}
        self._replace_json("c3_checkpoint.json", self.state)

    def finish(self, fields, body):
        pending = self.state["pending"]
        if pending is None:
            raise EvidenceError("missing_request_reservation")
        index = pending["sequence"]
        sha = hashlib.sha256(body).hexdigest() if body is not None else None
        metadata = {"schema_type": "CollectedResponse", "schema_version": 1,
                    "fingerprint": self.fingerprint, "sequence": index,
                    "request": pending["request"], "body_sha256": sha,
                    "representation": "response_bytes", "hash_basis": "original_bytes",
                    "body_processing": "application_body_bytes_not_wire_capture", **fields}
        from .collection_ingestion import validate_control
        validate_control(f"c3_attempt_{index:06d}.json", metadata)
        if body is not None:
            self._create(f"c3_attempt_{index:06d}.body", body)
        self._create_json(f"c3_attempt_{index:06d}.json", metadata)
        self._commit(metadata)
        return metadata

    def _commit(self, metadata):
        self._verify_body(metadata["sequence"], metadata)
        if self.json(f"c3_attempt_{metadata['sequence']:06d}.json") != metadata:
            raise EvidenceError("written_metadata_conflict")
        event = {"sequence": metadata["sequence"], "metadata_sha256": digest(metadata),
                 "body_sha256": metadata["body_sha256"]}
        self.state = {**self.state, "events": self.state["events"] + [event], "pending": None}
        self._replace_json("c3_checkpoint.json", self.state)

    def saved(self, request):
        if self.cursor >= len(self.state["events"]):
            return None
        index = self.cursor
        metadata = self.json(f"c3_attempt_{index:06d}.json")
        if metadata["request"] != request:
            raise EvidenceError("collection_replay_request_conflict")
        self.cursor += 1
        raw = self.reader.read(f"c3_attempt_{index:06d}.body", recheck=True).data if metadata["body_sha256"] is not None else None
        if raw is not None and hashlib.sha256(raw).hexdigest() != metadata["body_sha256"]:
            raise EvidenceError("collection_body_hash_mismatch")
        return metadata, raw

    def summary(self, value):
        self._replace_json("c3_summary.json", value)
