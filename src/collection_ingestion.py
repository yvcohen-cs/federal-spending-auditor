"""Read-only C3 format extension for C2's offline inventory command."""
from __future__ import annotations

import re

from .collection_sources import FPDS, USA, fpds_query, parse_page
from .evidence import EvidenceArtifact, EvidenceRecordRef, Representation, SourceIdentifier
from .evidence_io import EvidenceError, canonical, digest, strict_json


def validate_control(name, doc):
    if not isinstance(doc, dict) or type(doc.get("schema_version")) is not int or doc["schema_version"] != 1:
        raise EvidenceError("invalid_c3_control")
    expected = {"c3_plan.json": "CollectionPlan", "c3_checkpoint.json": "CollectionCheckpoint", "c3_summary.json": "CollectionSummary"}
    if re.fullmatch(r"c3_attempt_\d{6}\.json", name):
        expected[name] = "CollectedResponse"
        required = {"schema_type", "schema_version", "fingerprint", "sequence", "request", "body_sha256", "representation", "hash_basis", "body_processing", "error_code", "status", "retrieved_at_utc", "body_complete", "retry_after", "source_update_raw"}
        if set(doc) != required or type(doc.get("sequence")) is not int or doc["sequence"] < 0:
            raise EvidenceError("invalid_c3_response_metadata")
        if doc["representation"] != "response_bytes" or doc["hash_basis"] != "original_bytes" or type(doc["body_complete"]) is not bool:
            raise EvidenceError("invalid_c3_representation")
        request = doc["request"]
        if (not isinstance(request, dict) or set(request) != {"source", "endpoint", "method", "parameters", "task_index", "page_index", "attempt_index"}
                or request.get("source") not in ("usaspending", "fpds")
                or request["endpoint"] != (USA if request["source"] == "usaspending" else FPDS)
                or request["method"] != ("POST" if request["source"] == "usaspending" else "GET")
                or not isinstance(request["parameters"], dict)):
            raise EvidenceError("invalid_c3_request")
        from .evidence import _hash, _timestamp
        _hash(doc["fingerprint"])
        if doc["body_sha256"] is not None:
            _hash(doc["body_sha256"])
        value = doc["retrieved_at_utc"]
        if value is not None and not isinstance(value, str):
            raise EvidenceError("invalid_c3_timestamp")
        _timestamp(value)
        if doc["status"] is not None and (type(doc["status"]) is not int or not 100 <= doc["status"] <= 599):
            raise EvidenceError("invalid_c3_http_status")
        if doc["body_processing"] != "application_body_bytes_not_wire_capture":
            raise EvidenceError("invalid_c3_representation")
        if doc["body_complete"] and (doc["status"] is None or doc["body_sha256"] is None or doc["retrieved_at_utc"] is None):
            raise EvidenceError("incomplete_c3_capture_metadata")
        if doc["status"] is None and (doc["error_code"] is None or doc["retrieved_at_utc"] is not None or doc["body_sha256"] is not None):
            raise EvidenceError("invalid_c3_failed_request_metadata")
        if doc["error_code"] is not None and doc["error_code"] not in ("interrupted_request_outcome_unknown", "timeout", "connection_error", "tls_error", "request_error", "response_size_limit"):
            raise EvidenceError("unsupported_c3_transport_error")
        for key in ("retry_after", "source_update_raw"):
            value = doc[key]
            if value is not None and (not isinstance(value, str) or len(value) > 256 or any(ord(c) < 32 for c in value)):
                raise EvidenceError("invalid_c3_header_metadata")
    if name not in expected or doc.get("schema_type") != expected[name]:
        raise EvidenceError("unsupported_c3_control")
    if name == "c3_plan.json":
        from .collection import CollectionLimits, SelectedAward, make_plan
        if not isinstance(doc.get("awards"), list):
            raise EvidenceError("invalid_c3_plan")
        selected = [SelectedAward.from_dict(a) for a in doc["awards"]]
        limits = CollectionLimits.from_dict(doc["limits"])
        if make_plan(tuple(selected), limits, tuple(doc["sources"]), doc["profile"]) != doc:
            raise EvidenceError("invalid_c3_plan")
    if name == "c3_checkpoint.json":
        if not isinstance(doc.get("events"), list) or len(doc["events"]) > 1000:
            raise EvidenceError("invalid_c3_checkpoint")
        from .evidence import _hash
        _hash(doc.get("fingerprint", ""))
        if doc.get("pending") is not None:
            raise EvidenceError("pending_c3_request")
        for index, event in enumerate(doc["events"]):
            if not isinstance(event, dict) or set(event) != {"sequence", "metadata_sha256", "body_sha256"} or type(event["sequence"]) is not int or event["sequence"] != index:
                raise EvidenceError("invalid_c3_checkpoint")
            _hash(event["metadata_sha256"])
            if event["body_sha256"] is not None:
                _hash(event["body_sha256"])
    if name == "c3_summary.json":
        if (doc.get("historical_completeness") != "unknown" or doc.get("source_freshness") != "unknown"
                or not isinstance(doc.get("tasks"), list)
                or any(t.get("history") != "unknown" or t.get("freshness") != "unknown" or t.get("source_wide") != "unknown" for t in doc["tasks"] if isinstance(t, dict))):
            raise EvidenceError("unsupported_c3_completeness_claim")


def check_attempt(session, path, meta):
    from .evidence_ingestion import _safe_request
    name = path.rsplit("/", 1)[-1]
    prefix = path[:-len(name)]
    validate_control(name, meta)
    _safe_request(meta)
    plan = session.metadata(path, prefix + "c3_plan.json")
    cp = session.metadata(path, prefix + "c3_checkpoint.json")
    if plan is None or cp is None or digest(plan) != meta["fingerprint"] or cp["fingerprint"] != meta["fingerprint"]:
        raise EvidenceError("c3_plan_conflict")
    sequence = int(name[11:17])
    if sequence != meta["sequence"] or sequence >= len(cp["events"]) or cp["events"][sequence]["metadata_sha256"] != digest(meta):
        raise EvidenceError("c3_metadata_hash_mismatch")
    request = meta["request"]
    task, count = request["task_index"], len(plan["sources"])
    if (type(task) is not int or not 0 <= task < len(plan["awards"]) * count
            or plan["sources"][task % count] != request["source"]
            or type(request["page_index"]) is not int or not 1 <= request["page_index"] <= plan["limits"]["max_pages"]
            or type(request["attempt_index"]) is not int or not 0 <= request["attempt_index"] <= plan["limits"]["retries"]):
        raise EvidenceError("invalid_c3_task_context")
    selected = plan["awards"][task // count]
    params = request["parameters"]
    if request["source"] == "usaspending":
        if (set(params) != {"award_id", "page", "limit", "sort", "order"}
                or params["award_id"] != selected["generated_id"] or type(params["page"]) is not int
                or params["page"] != request["page_index"] or type(params["limit"]) is not int
                or not 1 <= params["limit"] <= plan["limits"]["page_size"] or params["sort"] != "action_date" or params["order"] != "asc"):
            raise EvidenceError("c3_query_scope_conflict")
    elif (params.get("q") != fpds_query(selected) or params.get("FEEDNAME") != "PUBLIC"
          or type(params.get("length")) is not int or params["length"] != 10
          or set(params) - {"q", "FEEDNAME", "length", "start", "index", "s"}):
        raise EvidenceError("c3_query_scope_conflict")
    return plan, cp


def adapt_body(session, path):
    from .evidence_ingestion import ArtifactValidation, EvidenceObservation, RecordOccurrence, ValidationStatus, _safe_request
    raw = session.read(path)
    name = path.rsplit("/", 1)[-1]
    prefix = path[:-len(name)]
    meta_path = path[:-5] + ".json"
    meta = session.metadata(path, meta_path)
    plan_path, cp_path = prefix + "c3_plan.json", prefix + "c3_checkpoint.json"
    plan, cp = session.metadata(path, plan_path), session.metadata(path, cp_path)
    if meta is None or plan is None or cp is None:
        raise EvidenceError("missing_c3_provenance")
    check_attempt(session, meta_path, meta)
    if digest(plan) != meta["fingerprint"] or cp["fingerprint"] != meta["fingerprint"]:
        raise EvidenceError("c3_plan_conflict")
    sequence = int(name[11:17])
    if sequence != meta["sequence"] or sequence >= len(cp["events"]):
        raise EvidenceError("unjournaled_c3_response")
    event = cp["events"][sequence]
    if (event["metadata_sha256"] != digest(meta) or event["body_sha256"] != raw.byte_sha256
            or meta["body_sha256"] != raw.byte_sha256):
        raise EvidenceError("c3_response_hash_mismatch")
    req = meta["request"]
    _safe_request(req["parameters"])
    limitations = ["application_response_bytes_not_http_wire_capture", "historical_completeness_unknown", "source_freshness_unknown"]
    if plan["profile"] != "live":
        limitations.append("synthetic_fixture_only")
    if meta["retrieved_at_utc"] is None:
        limitations.append("missing_retrieval_time")
    artifact = EvidenceArtifact(source=req["source"], relative_path=path, sha256=raw.byte_sha256,
                                representation=Representation.RESPONSE_BYTES, hash_basis="original_bytes",
                                endpoint=req["endpoint"], method=req["method"], request_json=canonical(req["parameters"]),
                                retrieved_at_utc=meta["retrieved_at_utc"], http_status=meta["status"],
                                limitations=tuple(limitations))
    records = []
    success = not meta["error_code"] and meta["body_complete"] and meta["status"] is not None and 200 <= meta["status"] < 300
    payload_hash = raw.byte_sha256
    if success:
        task = req["task_index"]
        source_count = len(plan["sources"])
        if type(task) is not int or task < 0 or task >= len(plan["awards"]) * source_count or plan["sources"][task % source_count] != req["source"]:
            raise EvidenceError("invalid_c3_task_context")
        selected = plan["awards"][task // source_count]
        parsed = parse_page(req["source"], raw.data, req, selected)
        if req["source"] == "usaspending":
            payload_hash = digest(strict_json(raw.data))
        for index, row in enumerate(parsed["rows"]):
            values = [("id", row.get("id")), ("modification_number", row.get("modification_number"))] if req["source"] == "usaspending" else [(key, row.get(key)) for key in ("atom_id", "PIID", "agencyID", "modNumber", "transactionNumber")]
            identifiers = tuple(SourceIdentifier(source=req["source"], namespace=key, value=value) for key, value in values if isinstance(value, str) and value.strip())
            ref = EvidenceRecordRef(artifact_id=artifact.artifact_id, source=artifact.source,
                                    locator=f"/results/{index}" if req["source"] == "usaspending" else f"/feed/entry[{index + 1}]",
                                    native_id=identifiers[0] if identifiers else None,
                                    source_record_url=row.get("source_record_url"))
            records.append(RecordOccurrence(reference=ref, identifiers=identifiers, source_update_raw=row.get("updated")))
    else:
        limitations.append("failed_or_partial_source_response")
        from dataclasses import replace
        artifact = replace(artifact, limitations=tuple(limitations))
    observation = EvidenceObservation(artifact=artifact, payload_sha256=payload_hash,
                                       metadata_paths=tuple(sorted((meta_path, plan_path, cp_path))),
                                       context_json=canonical({"profile": plan["profile"], "source_update_raw": meta["source_update_raw"], "body_complete": meta["body_complete"]}),
                                       records=tuple(records))
    return ArtifactValidation(relative_path=path, status=ValidationStatus.VERIFIED if success else ValidationStatus.INCOMPLETE,
                              format="c3_application_response_bytes", byte_sha256=raw.byte_sha256,
                              representation=Representation.RESPONSE_BYTES, representation_sha256=raw.byte_sha256,
                              observation=observation, integrity="declared_match")
