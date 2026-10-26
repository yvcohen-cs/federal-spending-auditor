"""Read-only adapters and deterministic C2 manifests. No source verification claims.

The C1 schemas are unchanged. These companion v1 contracts preserve multiple
observations of content that C1 VerificationRun intentionally deduplicates.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import PurePosixPath

from .evidence import EvidenceArtifact, EvidenceRecordRef, Representation, Schema, SourceIdentifier, VerificationRun, _hash, _timestamp
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, parts, safe_xml, strict_json


USA_AWARDS = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
USA_TRANSACTIONS = "https://api.usaspending.gov/api/v2/transactions/"
FPDS = "https://www.fpds.gov/ezsearch/FEEDS/ATOM"
ATOM = "{http://www.w3.org/2005/Atom}"


class ValidationStatus(str, Enum):
    VERIFIED = "verified"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, kw_only=True)
class RecordOccurrence(Schema):
    reference: EvidenceRecordRef
    identifiers: tuple[SourceIdentifier, ...] = ()
    source_update_raw: str | None = None

    def validate(self):
        if any(i.source != self.reference.source for i in self.identifiers):
            raise ValueError("record identifier source conflict")


@dataclass(frozen=True, kw_only=True)
class EvidenceObservation(Schema):
    artifact: EvidenceArtifact
    payload_sha256: str
    metadata_paths: tuple[str, ...] = ()
    context_json: str = "{}"
    records: tuple[RecordOccurrence, ...] = ()

    def validate(self):
        _hash(self.payload_sha256)
        for path in self.metadata_paths:
            parts(path)
        context = strict_json(self.context_json.encode("utf-8"))
        if not isinstance(context, dict) or canonical(context) != self.context_json:
            raise ValueError("context must be canonical object")
        for row in self.records:
            if row.reference.artifact_id != self.artifact.artifact_id or row.reference.source != self.artifact.source:
                raise ValueError("record reference conflicts with artifact")

    @property
    def content_id(self):
        return "content:sha256:" + self.payload_sha256

    @property
    def observation_id(self) -> str | None:
        a = self.artifact
        if any(x is None for x in (a.endpoint, a.method, a.request_json, a.retrieved_at_utc)):
            return None
        event = {"version": 1, "source": a.source, "endpoint": a.endpoint,
                 "method": a.method, "request_json": a.request_json,
                 "retrieved_at_utc": a.retrieved_at_utc,
                 "representation": a.representation.value}
        return "observation:v1:" + digest(event)

    def to_dict(self, *, substantive=False):
        return {**super().to_dict(substantive=substantive),
                "content_id": self.content_id, "observation_id": self.observation_id,
                "observation_identity_status": "documented" if self.observation_id else "ambiguous"}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("expected observation object")
        computed = {"content_id", "observation_id", "observation_identity_status"}
        if not computed <= set(value):
            raise ValueError("observation identity declarations required")
        result = super().from_dict({k: v for k, v in value.items() if k not in computed})
        actual = result.to_dict()
        if any(value[k] != actual[k] for k in computed):
            raise ValueError("observation identity declaration conflicts with metadata")
        return result


@dataclass(frozen=True, kw_only=True)
class ArtifactValidation(Schema):
    relative_path: str
    status: ValidationStatus
    format: str
    byte_sha256: str | None = None
    representation: Representation | None = None
    representation_sha256: str | None = None
    observation: EvidenceObservation | None = None
    error_code: str | None = None
    integrity: str = "unanchored"

    def validate(self):
        parts(self.relative_path)
        if self.byte_sha256 is not None:
            _hash(self.byte_sha256)
        if self.representation_sha256 is not None:
            _hash(self.representation_sha256)
        if (self.representation is None) != (self.representation_sha256 is None):
            raise ValueError("representation and content hash must be declared together")
        if self.integrity not in ("unanchored", "declared_match", "not_checked"):
            raise ValueError("invalid integrity state")
        if self.status in (ValidationStatus.INVALID, ValidationStatus.UNSUPPORTED):
            if not self.error_code or self.observation is not None:
                raise ValueError("failed validation cannot retain a trusted observation")
        elif self.error_code is not None or self.byte_sha256 is None:
            raise ValueError("successful validation requires bytes and no error")
        elif self.representation is None:
            raise ValueError("successful validation requires declared representation")
        if self.observation is not None and self.observation.artifact.relative_path != self.relative_path:
            raise ValueError("observation path conflict")
        if self.observation and (self.observation.artifact.representation != self.representation
                                 or self.observation.artifact.sha256 != self.representation_sha256):
            raise ValueError("observation representation conflict")


@dataclass(frozen=True, kw_only=True)
class IngestionManifest(Schema):
    entries: tuple[ArtifactValidation, ...]
    complete: bool = True
    errors: tuple[str, ...] = ()
    executed_at_utc: str | None = field(default=None, metadata={"execution": True})

    def validate(self):
        paths = [item.relative_path for item in self.entries]
        if paths != sorted(set(paths)):
            raise ValueError("manifest paths must be unique and sorted")
        if self.complete and self.errors:
            raise ValueError("incomplete scan cannot be complete")
        _timestamp(self.executed_at_utc)

    @property
    def summary(self):
        return {status.value: sum(e.status is status for e in self.entries) for status in ValidationStatus}

    @property
    def substantive_sha256(self):
        return digest(self.to_dict(substantive=True))

    @property
    def exit_code(self):
        if "interrupted" in self.errors:
            return 130
        if not self.complete or any(e.status is ValidationStatus.INVALID for e in self.entries):
            return 2
        if not self.entries or any(e.status is not ValidationStatus.VERIFIED for e in self.entries):
            return 1
        return 0


def _metadata_object(value):
    if not isinstance(value, dict):
        raise EvidenceError("invalid_metadata")
    return value


def _safe_request(value):
    if not isinstance(value, dict):
        raise EvidenceError("invalid_request")
    # Do not echo credential-bearing untrusted metadata into reports. Current
    # collectors use only public filters; reject rather than redact provenance.
    def visit(item):
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = re.sub(r"[^a-z]", "", key.lower())
                if any(s in normalized for s in ("password", "secret", "token", "authorization", "apikey", "cookie")):
                    raise EvidenceError("sensitive_metadata")
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)
    visit(value)
    return canonical(value)


class _Session:
    def __init__(self, root):
        self.root = root
        self.snapshots = {}
        self.documents = {}
        self.dependencies = {}

    def read(self, path):
        if path not in self.snapshots:
            self.snapshots[path] = self.root.read(path)
        return self.snapshots[path]

    def json(self, path):
        if path not in self.documents:
            self.documents[path] = strict_json(self.read(path).data)
        return self.documents[path]

    def metadata(self, owner, path):
        self.dependencies.setdefault(owner, set()).add(path)
        try:
            doc = _metadata_object(self.json(path))
            _validate_control(PurePosixPath(path).name, doc)
            return doc
        except EvidenceError as exc:
            if exc.code == "missing_file":
                return None
            raise


def _join(path, name):
    return str(PurePosixPath(path).parent / name)


def _ids(source, values, limitations):
    result = []
    for namespace, value in values:
        if value is None:
            continue
        if not isinstance(value, str):
            limitations.add("nonstring_native_identifier_not_coerced")
            continue
        try:
            result.append(SourceIdentifier(source=source, namespace=namespace, value=value))
        except ValueError:
            raise EvidenceError("invalid_native_identifier") from None
    if not result:
        limitations.add("missing_native_identifiers")
    return tuple(result)


def _json_records(body, prefix, artifact, transactions, limitations):
    rows = body.get("results")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise EvidenceError("invalid_results")
    if len(rows) > 100:
        raise EvidenceError("results_size_exceeds_collector_limit")
    result = []
    for index, row in enumerate(rows):
        names = (("id", "modification_number") if transactions else
                 ("generated_internal_id", "Award ID", "Awarding Agency Code", "Awarding Sub Agency Code"))
        identifiers = _ids("usaspending", [(name, row.get(name)) for name in names], limitations)
        reference = EvidenceRecordRef(artifact_id=artifact.artifact_id, source="usaspending",
                                      locator=f"{prefix}/results/{index}",
                                      native_id=identifiers[0] if identifiers else None)
        updated = row.get("Last Modified Date")
        if updated is not None and not isinstance(updated, str):
            raise EvidenceError("invalid_source_update")
        result.append(RecordOccurrence(reference=reference, identifiers=identifiers, source_update_raw=updated))
    return tuple(result)


def _xml_records(root, artifact, limitations):
    if root.tag != ATOM + "feed":
        raise EvidenceError("unsupported_xml_format")
    result = []
    for index, entry in enumerate(root.findall(ATOM + "entry"), 1):
        awards = [node for node in entry.iter() if node.tag.rsplit("}", 1)[-1] == "awardContractID"]
        if len(awards) != 1:
            raise EvidenceError("invalid_fpds_award_context")
        values = [("atom_entry_id", entry.findtext(ATOM + "id"))]
        for node in awards[0]:
            name = node.tag.rsplit("}", 1)[-1]
            if name in ("PIID", "agencyID", "modNumber", "transactionNumber"):
                values.append((name, node.text))  # Preserve original text, no trim.
        identifiers = _ids("fpds", values, limitations)
        if len({i.namespace for i in identifiers}) != len(identifiers):
            raise EvidenceError("conflicting_native_identifiers")
        # Only an actual alternate link is recorded; never construct a permalink.
        links = [link.get("href") for link in entry.findall(ATOM + "link") if link.get("rel") == "alternate"]
        if len(links) > 1:
            raise EvidenceError("ambiguous_record_url")
        ref = EvidenceRecordRef(artifact_id=artifact.artifact_id, source="fpds",
                                locator=f"/feed/entry[{index}]",
                                native_id=identifiers[0] if identifiers else None,
                                source_record_url=links[0] if links else None)
        result.append(RecordOccurrence(reference=ref, identifiers=identifiers,
                                       source_update_raw=entry.findtext(ATOM + "updated")))
    return tuple(result)


def _artifact(path, source, sha, representation, endpoint, method, request, timestamp, limitations):
    if endpoint is None:
        limitations.add("missing_endpoint")
    if method is None:
        limitations.add("missing_method")
    if timestamp is None:
        limitations.add("missing_page_retrieval_time")
    limitations.add("http_status_not_saved")
    limitations.add("source_wide_freshness_unknown")
    return EvidenceArtifact(source=source, relative_path=path, sha256=sha,
                            representation=representation,
                            hash_basis="canonical_json" if representation is Representation.PARSED_JSON else "utf8_text",
                            endpoint=endpoint, method=method, request_json=request,
                            retrieved_at_utc=timestamp, limitations=tuple(sorted(limitations)))


def _adapt(session, path):
    snap = session.read(path)
    name = PurePosixPath(path).name
    if re.fullmatch(r"c3_attempt_\d{6}\.body", name):
        from .collection_ingestion import adapt_body
        return adapt_body(session, path)
    if not snap.data:
        raise EvidenceError("empty_file")
    if re.fullmatch(r"c3_attempt_\d{6}\.json", name):
        from .collection_ingestion import check_attempt
        check_attempt(session, path, session.json(path))
    limitations = set()
    endpoint = method = request = timestamp = None
    context = {}
    integrity = "unanchored"
    metadata_paths = []
    if name.endswith(".json"):
        doc = session.json(path)
        if re.fullmatch(r"response_\d{6}\.json", name):
            if not isinstance(doc, dict) or not isinstance(doc.get("request"), dict) or not isinstance(doc.get("response"), dict):
                raise EvidenceError("invalid_envelope")
            request = _safe_request(doc["request"])
            if (type(doc["request"].get("page")) is not int or doc["request"]["page"] < 1
                    or type(doc["request"].get("limit")) is not int or not 1 <= doc["request"]["limit"] <= 100):
                raise EvidenceError("invalid_request")
            timestamp = doc.get("retrieved_at_utc")
            if timestamp is not None and not isinstance(timestamp, str):
                raise EvidenceError("invalid_timestamp")
            plan_path = _join(path, "query_metadata.json")
            plan = session.metadata(path, plan_path)
            if plan:
                _validate_control("query_metadata.json", plan)
                if plan.get("mode") != "stratified" or plan.get("version") != 2 or plan.get("endpoint") != USA_AWARDS:
                    raise EvidenceError("conflicting_query_metadata")
                endpoint = plan["endpoint"]
                metadata_paths.append(plan_path)
                for key in ("fields", "sort", "order"):
                    if doc["request"].get(key) != plan.get(key):
                        raise EvidenceError("request_plan_conflict")
                if not any(doc["request"].get("filters") == s.get("filters") for s in plan.get("strata", []) if isinstance(s, dict)):
                    raise EvidenceError("request_plan_conflict")
                if doc["request"].get("limit") != plan.get("page_size"):
                    raise EvidenceError("request_plan_conflict")
            else:
                limitations.add("missing_query_metadata")
            method = "POST"
            limitations.add("method_from_collector_contract")
            cp_path = _join(path, "checkpoint.json")
            cp = session.metadata(path, cp_path)
            if cp is not None:
                metadata_paths.append(cp_path)
                if cp.get("version") != 2 or not isinstance(cp.get("events"), list):
                    raise EvidenceError("invalid_checkpoint")
                if plan and cp.get("query_fingerprint") != plan.get("query_fingerprint"):
                    raise EvidenceError("checkpoint_plan_conflict")
                step = int(name[9:15])
                events = cp["events"]
                if [e.get("step") for e in events if isinstance(e, dict)] != list(range(len(events))):
                    raise EvidenceError("invalid_checkpoint")
                if step < len(events):
                    if events[step].get("sha256") != digest(doc):
                        raise EvidenceError("hash_mismatch")
                    integrity = "declared_match"
                else:
                    if cp.get("complete"):
                        raise EvidenceError("unexpected_response_after_complete_checkpoint")
                    limitations.add("response_not_in_checkpoint")
            else:
                limitations.add("missing_checkpoint")
            body, prefix, transactions = doc["response"], "/response", False
            if (not isinstance(body.get("page_metadata"), dict)
                    or type(body["page_metadata"].get("hasNext")) is not bool
                    or "page" in body["page_metadata"] and body["page_metadata"]["page"] != doc["request"]["page"]):
                raise EvidenceError("invalid_pagination_metadata")
            if isinstance(body.get("results"), list) and (len(body["results"]) > doc["request"]["limit"]
                    or not body["results"] and body["page_metadata"]["hasNext"]):
                raise EvidenceError("invalid_pagination_metadata")
            fmt = "usaspending_stratified_v2"
        elif re.fullmatch(r"page_\d{4,}\.json", name):
            if int(name[5:-5]) < 1:
                raise EvidenceError("invalid_page_number")
            if not isinstance(doc, dict):
                raise EvidenceError("invalid_results")
            plan_path = _join(path, "query_metadata.json")
            plan = session.metadata(path, plan_path)
            transactions = False
            if plan:
                _validate_control("query_metadata.json", plan)
                metadata_paths.append(plan_path)
                endpoint, method = plan.get("endpoint"), plan.get("method")
                if endpoint not in (USA_AWARDS, USA_TRANSACTIONS) or method != "POST":
                    raise EvidenceError("conflicting_query_metadata")
                transactions = endpoint == USA_TRANSACTIONS
                # Legacy collectors did not save each exact request/limit.
                context = {"query_metadata": plan}
                _safe_request(context)
            else:
                limitations.add("missing_query_metadata_award_or_transaction_unknown")
            limitations.add("exact_page_request_not_saved")
            limitations.add("page_timestamp_not_saved")
            body, prefix = doc, ""
            fmt = "usaspending_legacy_transactions" if transactions else "usaspending_legacy_page"
        else:
            _validate_control(name, doc)
            return ArtifactValidation(relative_path=path, status=ValidationStatus.VERIFIED,
                                      format="collector_metadata", byte_sha256=snap.byte_sha256,
                                      representation=Representation.PARSED_JSON, representation_sha256=digest(doc))
        artifact = _artifact(path, "usaspending", digest(doc), Representation.PARSED_JSON,
                             endpoint, method, request, timestamp, limitations)
        records = _json_records(body, prefix, artifact, transactions, limitations)
    elif re.fullmatch(r"fpds_lookup_\d{3,}_page_\d{3,}\.xml", name):
        if int(name.rsplit("_", 1)[1][:-4]) < 1:
            raise EvidenceError("invalid_page_number")
        text, tree = safe_xml(snap.data)
        meta_name = re.sub(r"_page_\d+\.xml$", "_query.json", name)
        meta_path = _join(path, meta_name)
        plan = session.metadata(path, meta_path)
        if plan:
            _validate_control(meta_name, plan)
            metadata_paths.append(meta_path)
            if plan.get("endpoint") != FPDS or plan.get("method") != "GET":
                raise EvidenceError("conflicting_query_metadata")
            endpoint, method = FPDS, "GET"
            context = {"lookup_metadata": plan}
            _safe_request(context)
        else:
            limitations.add("missing_lookup_metadata")
        limitations.add("lookup_timestamp_is_completion_not_page_retrieval")
        limitations.add("exact_page_request_not_saved")
        artifact = _artifact(path, "fpds", hashlib.sha256(text.encode("utf-8")).hexdigest(),
                             Representation.DECODED_XML, endpoint, method, None, None, limitations)
        records = _xml_records(tree, artifact, limitations)
        fmt = "fpds_decoded_atom"
    elif name.endswith(".xml"):
        safe_xml(snap.data)
        raise EvidenceError("unsupported_xml_format")
    else:
        raise EvidenceError("unsupported_format")
    artifact = replace(artifact, limitations=tuple(sorted(limitations)))
    payload_sha = digest(body) if artifact.source == "usaspending" else artifact.sha256
    observation = EvidenceObservation(artifact=artifact, payload_sha256=payload_sha,
                                       metadata_paths=tuple(sorted(metadata_paths)),
                                       context_json=canonical(context), records=records)
    incomplete = observation.observation_id is None or any(
        x in limitations for x in ("missing_native_identifiers", "nonstring_native_identifier_not_coerced", "response_not_in_checkpoint"))
    return ArtifactValidation(relative_path=path,
                              status=ValidationStatus.INCOMPLETE if incomplete else ValidationStatus.VERIFIED,
                              format=fmt, byte_sha256=snap.byte_sha256,
                              representation=artifact.representation, representation_sha256=artifact.sha256,
                              observation=observation, integrity=integrity)


def _validate_control(name, doc):
    if name in ("c3_plan.json", "c3_checkpoint.json", "c3_summary.json") or re.fullmatch(r"c3_attempt_\d{6}\.json", name):
        from .collection_ingestion import validate_control
        _safe_request(doc)
        validate_control(name, doc)
        return
    if name not in ("query_metadata.json", "checkpoint.json", "sampling_coverage.json", "run_metadata.json") and not re.fullmatch(r"fpds_lookup_\d{3,}_query\.json", name):
        raise EvidenceError("unsupported_json_format")
    _metadata_object(doc)
    _safe_request(doc)
    if name == "query_metadata.json":
        if doc.get("mode") == "stratified":
            if doc.get("version") != 2 or doc.get("endpoint") != USA_AWARDS or not isinstance(doc.get("strata"), list):
                raise EvidenceError("invalid_query_metadata")
            config = {k: v for k, v in doc.items() if k not in ("created_at_utc", "query_fingerprint")}
            if digest(config) != doc.get("query_fingerprint"):
                raise EvidenceError("query_fingerprint_mismatch")
        elif doc.get("endpoint") not in (USA_AWARDS, USA_TRANSACTIONS) or doc.get("method") != "POST":
            raise EvidenceError("invalid_query_metadata")
        for key in ("generated_at_utc", "created_at_utc"):
            value = doc.get(key)
            if value is not None and not isinstance(value, str):
                raise EvidenceError("invalid_timestamp")
            _timestamp(value)
    elif re.fullmatch(r"fpds_lookup_\d{3,}_query\.json", name):
        if (doc.get("endpoint") != FPDS or doc.get("method") != "GET"
                or not isinstance(doc.get("params"), dict)
                or doc.get("query") != doc["params"].get("q")):
            raise EvidenceError("invalid_lookup_metadata")
        value = doc.get("retrieved_at_utc")
        if value is not None and not isinstance(value, str):
            raise EvidenceError("invalid_timestamp")
        _timestamp(value)
    elif name == "sampling_coverage.json":
        if not isinstance(doc.get("strata"), list) or type(doc.get("complete")) is not bool:
            raise EvidenceError("invalid_sampling_coverage")
    elif name == "run_metadata.json":
        if not isinstance(doc.get("run_id"), str) or not doc["run_id"]:
            raise EvidenceError("invalid_run_metadata")
    if name == "checkpoint.json":
        _hash(doc.get("query_fingerprint", ""))
        if "events" in doc:
            if doc.get("version") != 2 or not isinstance(doc["events"], list):
                raise EvidenceError("invalid_checkpoint")
            if [e.get("step") for e in doc["events"] if isinstance(e, dict)] != list(range(len(doc["events"]))):
                raise EvidenceError("invalid_checkpoint")
            for event in doc["events"]:
                if type(event.get("step")) is not int:
                    raise EvidenceError("invalid_checkpoint")
                _hash(event.get("sha256", ""))
        elif not isinstance(doc.get("completed_pages"), list):
            raise EvidenceError("invalid_checkpoint")
        elif any(type(p) is not int or p < 1 for p in doc["completed_pages"]):
            raise EvidenceError("invalid_checkpoint")
        if type(doc.get("complete")) is not bool:
            raise EvidenceError("invalid_checkpoint")


def validate_record_ref(observation, reference):
    """Validate a stored locator/native ID against adapter-extracted records."""
    for row in observation.records:
        if row.reference.locator == reference.locator:
            if (reference.artifact_id != observation.artifact.artifact_id
                    or reference.source != observation.artifact.source
                    or reference.native_id is not None and reference.native_id not in row.identifiers):
                raise EvidenceError("record_reference_conflict")
            return
    raise EvidenceError("invalid_record_locator")


def read_manifest(doc):
    """Accept a C2 manifest or the CLI report wrapper; verify wrapper consistency."""
    if not isinstance(doc, dict):
        raise EvidenceError("invalid_manifest")
    if doc.get("schema_type") == "VerificationRun":
        return VerificationRun.from_dict(doc)
    if "manifest" not in doc:
        return IngestionManifest.from_dict(doc)
    if set(doc) != {"manifest", "summary", "substantive_sha256", "exit_code"}:
        raise EvidenceError("invalid_manifest")
    manifest = IngestionManifest.from_dict(doc["manifest"])
    if (doc["summary"] != manifest.summary or doc["substantive_sha256"] != manifest.substantive_sha256
            or type(doc["exit_code"]) is not int or doc["exit_code"] != manifest.exit_code):
        raise EvidenceError("invalid_manifest_summary")
    return manifest


def inspect_directory(root_path, *, declared: IngestionManifest | VerificationRun | None = None, manifest_path=None, **limits):
    """Return a complete or explicitly partial manifest; never write evidence."""
    entries = {}
    errors = []
    expected = {}
    try:
        with EvidenceRoot(root_path, **limits) as root:
            session = _Session(root)
            paths = root.discover()
            if manifest_path is not None:
                parts(manifest_path)
                if declared is not None:
                    raise EvidenceError("conflicting_manifest_inputs")
                try:
                    declared = read_manifest(session.json(manifest_path))
                except (ValueError, TypeError, KeyError):
                    raise EvidenceError("invalid_manifest") from None
                paths = tuple(p for p in paths if p != manifest_path)
            legacy_manifest = isinstance(declared, VerificationRun)
            if declared:
                expected = {e.relative_path: e for e in declared.artifacts} if legacy_manifest else {e.relative_path: e for e in declared.entries}
                if legacy_manifest and len(expected) != len(declared.artifacts):
                    raise EvidenceError("duplicate_manifest_paths")
            required = set(paths) | set(expected)
            # Checkpoint filenames are constructed from validated integer steps,
            # never taken from arbitrary path values in metadata.
            for path in paths:
                if PurePosixPath(path).name == "c3_checkpoint.json":
                    try:
                        checkpoint = session.json(path)
                        _validate_control("c3_checkpoint.json", checkpoint)
                        for event in checkpoint["events"]:
                            required.add(_join(path, f"c3_attempt_{event['sequence']:06d}.json"))
                            if event["body_sha256"] is not None:
                                required.add(_join(path, f"c3_attempt_{event['sequence']:06d}.body"))
                    except (EvidenceError, ValueError, TypeError, KeyError):
                        pass
                if PurePosixPath(path).name == "checkpoint.json":
                    try:
                        checkpoint = session.json(path)
                        _validate_control("checkpoint.json", checkpoint)
                        if "events" in checkpoint:
                            if len(checkpoint["events"]) > root.max_files:
                                raise EvidenceError("file_count_limit")
                            required.update(_join(path, f"response_{e['step']:06d}.json") for e in checkpoint["events"])
                        else:
                            if len(checkpoint["completed_pages"]) > root.max_files:
                                raise EvidenceError("file_count_limit")
                            required.update(_join(path, f"page_{p:04d}.json") for p in checkpoint["completed_pages"])
                    except EvidenceError as exc:
                        if exc.code == "file_count_limit":
                            raise
                    except (ValueError, TypeError, KeyError):
                        pass  # The checkpoint's own validation emits its error.
            if len(required) > root.max_files:
                raise EvidenceError("file_count_limit")
            for path in sorted(required):
                try:
                    entry = _adapt(session, path)
                    prior = expected.get(path)
                    if prior and legacy_manifest:
                        actual = entry.observation.artifact if entry.observation else None
                        if actual is None or any(getattr(prior, key) != getattr(actual, key) for key in ("source", "sha256", "representation", "hash_basis")):
                            raise EvidenceError("hash_or_representation_mismatch")
                        for key in ("endpoint", "method", "request_json", "retrieved_at_utc", "source_updated_at_utc", "http_status"):
                            if getattr(prior, key) is not None and getattr(prior, key) != getattr(actual, key):
                                raise EvidenceError("manifest_provenance_conflict")
                        for result in declared.results:
                            for reference in result.evidence + result.coverage.evidence:
                                if reference.artifact_id == actual.artifact_id:
                                    validate_record_ref(entry.observation, reference)
                        entry = replace(entry, integrity="declared_match")
                    elif prior:
                        if prior.byte_sha256 is None or prior.byte_sha256 != entry.byte_sha256:
                            raise EvidenceError("hash_mismatch")
                        if prior.observation:
                            if not entry.observation or prior.observation.artifact != entry.observation.artifact:
                                raise EvidenceError("manifest_provenance_conflict")
                            for record in prior.observation.records:
                                validate_record_ref(entry.observation, record.reference)
                                if record not in entry.observation.records:
                                    raise EvidenceError("manifest_record_conflict")
                            if prior.observation != entry.observation:
                                raise EvidenceError("manifest_observation_conflict")
                        entry = replace(entry, integrity="declared_match")
                    elif declared and not legacy_manifest:
                        raise EvidenceError("undeclared_artifact")
                    entries[path] = entry
                except EvidenceError as exc:
                    status = ValidationStatus.UNSUPPORTED if exc.code.startswith("unsupported_") else ValidationStatus.INVALID
                    entries[path] = ArtifactValidation(relative_path=path, status=status, format="unknown",
                                                        error_code=exc.code, integrity="not_checked")
                except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
                    entries[path] = ArtifactValidation(relative_path=path, status=ValidationStatus.INVALID,
                                                        format="unknown", error_code="invalid_metadata", integrity="not_checked")
            # A repeated event fingerprint is not a license to select conflicting
            # payloads. Copies with equal payloads remain separate inventory rows.
            events = {}
            for path, entry in entries.items():
                if entry.observation and entry.observation.observation_id:
                    events.setdefault(entry.observation.observation_id, []).append(path)
            for group in events.values():
                if len({entries[p].observation.content_id for p in group}) > 1:
                    for path in group:
                        entries[path] = ArtifactValidation(relative_path=path, status=ValidationStatus.INVALID,
                                                            format=entries[path].format,
                                                            error_code="conflicting_observation_payloads", integrity="not_checked")
            # Re-read all data and metadata after adaptation, including shared
            # metadata. Never trust an observation built across changing files.
            changed = set()
            for path, snapshot in session.snapshots.items():
                try:
                    again = root.read(path, recheck=True)
                    if again.stamp != snapshot.stamp or again.byte_sha256 != snapshot.byte_sha256:
                        changed.add(path)
                except EvidenceError:
                    changed.add(path)
            for path, entry in list(entries.items()):
                if path in changed or session.dependencies.get(path, set()) & changed:
                    entries[path] = ArtifactValidation(relative_path=path, status=ValidationStatus.INVALID,
                                                        format=entry.format, error_code="changed_during_validation", integrity="not_checked")
            final_paths = tuple(p for p in root.discover() if p != manifest_path)
            if final_paths != paths:
                errors.append("directory_changed_during_validation")
    except KeyboardInterrupt:
        errors.append("interrupted")
        # A partially validated batch cannot assert final snapshot integrity.
        entries = {p: ArtifactValidation(relative_path=p, status=ValidationStatus.INVALID,
                                         format=e.format, error_code="interrupted", integrity="not_checked")
                   for p, e in entries.items()}
    except EvidenceError as exc:
        errors.append(exc.code)
    except (OSError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        errors.append("invalid_scan_or_manifest")
    if errors:
        entries = {p: ArtifactValidation(relative_path=p, status=ValidationStatus.INVALID,
                                         format=e.format, error_code="scan_incomplete", integrity="not_checked")
                   for p, e in entries.items()}
    return IngestionManifest(entries=tuple(entries[p] for p in sorted(entries)),
                             complete=not errors, errors=tuple(errors))
