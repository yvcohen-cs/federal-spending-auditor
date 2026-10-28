"""Read-only C3 format extension for C2's offline inventory command."""
from __future__ import annotations

import re

from .collection_sources import FPDS, USA, FPDS_BACKENDS, FPDS_FEED_VERSION, fpds_query, parse_page, request_for
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
        if digest(make_plan(tuple(selected), limits, tuple(doc["sources"]), doc["profile"], collector_version=doc.get("collector_version"),stop_on_context_mismatch=doc.get("stop_on_context_mismatch",False))) != digest(doc):
            raise EvidenceError("invalid_c3_plan")
    if name == "c3_checkpoint.json":
        if set(doc) != {"schema_type", "schema_version", "fingerprint", "events", "pending"} or not isinstance(doc.get("events"), list) or len(doc["events"]) > 1000:
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
                or any(not isinstance(t, dict) or t.get("history") != "unknown" or t.get("freshness") != "unknown" or t.get("source_wide") != "unknown"
                       or t.get("pagination") not in ("unknown", "partial", "complete")
                       or t.get("query_scope") not in ("unknown", "partial", "complete") for t in doc["tasks"])):
            raise EvidenceError("unsupported_c3_completeness_claim")
        from .collection_sources import FPDS_CONTINUATION_RULE
        from .evidence import _hash
        for task in doc["tasks"]:
            if "continuations" not in task and "terminal_page_seen" not in task:
                continue  # Historical summaries remain readable.
            if (type(task.get("terminal_page_seen")) is not bool
                    or task["terminal_page_seen"] and task["pagination"]!="complete"
                    or not isinstance(task.get("continuations"),list) or len(task["continuations"])>1000):
                raise EvidenceError("invalid_c3_pagination_summary")
            for c in task["continuations"]:
                if (task.get("source")!="fpds" or not isinstance(c,dict)
                        or set(c)!={"source_page","response_sequence","decoded_atom_href","next_parameters","scope_sha256","rule_version"}
                        or c["rule_version"]!=FPDS_CONTINUATION_RULE
                        or type(c["source_page"]) is not int or not 1<=c["source_page"]<=100000
                        or type(c["response_sequence"]) is not int or c["response_sequence"]<0
                        or not isinstance(c["decoded_atom_href"],str) or not 1<=len(c["decoded_atom_href"])<=8192
                        or not isinstance(c["next_parameters"],dict)):
                    raise EvidenceError("invalid_c3_pagination_summary")
                _hash(c["scope_sha256"])
                p=c["next_parameters"]
                offsets=set(p)&{"start","index"}
                if (len(offsets)!=1 or set(p)-{"start","index","s","VERSION"}
                        or any(type(p[k]) is not int or p[k]!=c["source_page"]*10 for k in offsets)
                        or "VERSION" in p and p["VERSION"]!=FPDS_FEED_VERSION
                        or "s" in p and p["s"] not in FPDS_BACKENDS
                        or p.get("s")=="FPDS" and p.get("VERSION")!=FPDS_FEED_VERSION):
                    raise EvidenceError("invalid_c3_pagination_summary")


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
    if cp["events"][sequence]["body_sha256"] != meta["body_sha256"]:
        raise EvidenceError("c3_body_hash_declaration_conflict")
    validate_request(meta["request"], plan)
    if plan["collector_version"]>=3 and meta["request"]["source"]=="fpds" and meta["request"]["page_index"]>1:
        _validate_predecessor(session,path,prefix,meta,plan,cp)
    return plan, cp


def _validate_predecessor(session,owner,prefix,meta,plan,checkpoint):
    """V3 requests must be authorized by one preserved successful preceding page.

    This is also checked on read, not only when outgoing requests are built.
    Individual immutable request hashes alone do not prove continuation scope.
    """
    request=meta["request"]
    predecessors=[]
    for index in range(meta["sequence"]):
        name=f"c3_attempt_{index:06d}.json"
        previous=session.metadata(owner,prefix+name)
        if previous is None or digest(previous)!=checkpoint["events"][index]["metadata_sha256"]:
            raise EvidenceError("c3_predecessor_metadata_conflict")
        validate_request(previous["request"],plan)
        p=previous["request"]
        if p["task_index"]==request["task_index"] and p["page_index"]==request["page_index"]-1 and previous["error_code"] is None and previous["body_complete"] and previous["status"] is not None and 200<=previous["status"]<300:
            predecessors.append(previous)
    if len(predecessors)!=1:
        raise EvidenceError("c3_missing_or_ambiguous_predecessor")
    previous=predecessors[0]
    raw=session.read(prefix+f"c3_attempt_{previous['sequence']:06d}.body")
    if raw.byte_sha256!=previous["body_sha256"] or raw.byte_sha256!=checkpoint["events"][previous["sequence"]]["body_sha256"]:
        raise EvidenceError("c3_predecessor_body_conflict")
    selected=plan["awards"][request["task_index"]//len(plan["sources"])]
    parsed=parse_page("fpds",raw.data,previous["request"],selected)
    if not parsed["has_next"]:
        raise EvidenceError("c3_continuation_not_authorized")
    expected=request_for("fpds",selected,request["page_index"],10,parsed["next_parameters"])
    if digest(expected["parameters"])!=digest(request["parameters"]):
        raise EvidenceError("c3_continuation_scope_conflict")


def validate_request(request, plan):
    """Pure validation, including in-flight reservations before any recovery write."""
    if (not isinstance(request, dict) or set(request) != {"source", "endpoint", "method", "parameters", "task_index", "page_index", "attempt_index"}
            or request.get("source") not in ("usaspending", "fpds")
            or request["endpoint"] != (USA if request["source"] == "usaspending" else FPDS)
            or request["method"] != ("POST" if request["source"] == "usaspending" else "GET")
            or not isinstance(request["parameters"], dict)):
        raise EvidenceError("invalid_c3_request")
    task, count = request["task_index"], len(plan["sources"])
    if (type(task) is not int or not 0 <= task < len(plan["awards"]) * count
            or plan["sources"][task % count] != request["source"]
            or type(request["page_index"]) is not int or not 1 <= request["page_index"] <= plan["limits"]["max_pages"]
            or type(request["attempt_index"]) is not int or not 0 <= request["attempt_index"] <= plan["limits"]["retries"]):
        raise EvidenceError("invalid_c3_task_context")
    selected = plan["awards"][task // count]
    params = request["parameters"]
    if request["source"] == "fpds" and (selected["piid"] is None or selected["agency_id"] is None):
        raise EvidenceError("c3_query_scope_conflict")
    if request["source"] == "usaspending":
        if (set(params) != {"award_id", "page", "limit", "sort", "order"}
                or selected["generated_id"] is None or params["award_id"] != selected["generated_id"] or type(params["page"]) is not int
                or params["page"] != request["page_index"] or type(params["limit"]) is not int
                or not 1 <= params["limit"] <= plan["limits"]["page_size"] or params["sort"] != "action_date" or params["order"] != "asc"):
            raise EvidenceError("c3_query_scope_conflict")
    elif (params.get("q") != fpds_query(selected) or params.get("FEEDNAME") != "PUBLIC"
          or type(params.get("length")) is not int or params["length"] != 10
          or set(params) - ({"q", "FEEDNAME", "length", "start", "index", "s", "VERSION"} if plan["collector_version"]>=3 else {"q", "FEEDNAME", "length", "start", "index", "s"})):
        raise EvidenceError("c3_query_scope_conflict")
    elif request["source"] == "fpds":
        if selected["piid"] is None or selected["agency_id"] is None or (selected["parent_piid"] is None) != (selected["parent_agency_id"] is None):
            raise EvidenceError("c3_query_scope_conflict")
        offsets = set(params) & {"start", "index"}
        backends=FPDS_BACKENDS if plan["collector_version"]>=3 else ("FPDSNG.COM",)
        if len(offsets) > 1 or any(type(params[k]) is not int or params[k] < 0 for k in offsets) or params.get("s", "FPDSNG.COM") not in backends:
            raise EvidenceError("invalid_c3_offset")
        if "VERSION" in params and (params["VERSION"]!=FPDS_FEED_VERSION or type(params["VERSION"]) is not str):
            raise EvidenceError("unsupported_c3_feed_version")
        if params.get("s")=="FPDS" and params.get("VERSION")!=FPDS_FEED_VERSION:
            raise EvidenceError("unsupported_c3_feed_version")
        if plan["collector_version"]>=3 and request["page_index"]==1 and ("VERSION" in params or "s" in params):
            raise EvidenceError("unsolicited_c3_continuation_token")
        if plan["collector_version"] >= 2:
            expected = (request["page_index"] - 1) * 10
            if (expected == 0 and offsets) or (expected > 0 and (not offsets or params[next(iter(offsets))] != expected)):
                raise EvidenceError("noncontiguous_c3_offset")


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
    if req["source"] == "fpds":
        limitations.append("fpds_query_scope_not_universally_verified")
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
    inconclusive = False
    if success:
        task = req["task_index"]
        source_count = len(plan["sources"])
        if type(task) is not int or task < 0 or task >= len(plan["awards"]) * source_count or plan["sources"][task % source_count] != req["source"]:
            raise EvidenceError("invalid_c3_task_context")
        selected = plan["awards"][task // source_count]
        parsed = parse_page(req["source"], raw.data, req, selected)
        if req["source"]=="fpds" and parsed["next_parameters"] and parsed["next_parameters"].get("VERSION")==FPDS_FEED_VERSION:
            from dataclasses import replace
            artifact=replace(artifact,limitations=artifact.limitations+("fpds_version_1_5_3_continuation_validated_not_history_proof",))
        inconclusive = req["source"] == "fpds" and not parsed["rows"]
        if inconclusive:
            from dataclasses import replace
            artifact = replace(artifact, limitations=artifact.limitations + ("inconclusive_empty_feed",))
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
    return ArtifactValidation(relative_path=path, status=ValidationStatus.VERIFIED if success and not inconclusive else ValidationStatus.INCOMPLETE,
                              format="c3_application_response_bytes", byte_sha256=raw.byte_sha256,
                              representation=Representation.RESPONSE_BYTES, representation_sha256=raw.byte_sha256,
                              observation=observation, integrity="declared_match")
