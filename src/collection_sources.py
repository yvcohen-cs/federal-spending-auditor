"""Bounded transports and source-context parsing for C3 (no financial judgments)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from .evidence_io import EvidenceError, canonical, digest, safe_xml, strict_json


USA = "https://api.usaspending.gov/api/v2/transactions/"
FPDS = "https://www.fpds.gov/ezsearch/FEEDS/ATOM"
ATOM = "{http://www.w3.org/2005/Atom}"
FPDS_NAMESPACES = ("https://www.fpds.gov/FPDS", "http://www.fpds.gov/FPDS")
FPDS_CONTINUATION_RULE = "fpds-continuation-v1"
FPDS_FEED_VERSION = "1.5.3"
FPDS_BACKENDS = ("FPDSNG.COM", "FPDS")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def fpds_query(award):
    def quoted(value):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"PIID:{quoted(award['piid'])} AND CONTRACTING_AGENCY_ID:{quoted(award['agency_id'])}"


def request_for(source, award, page, size, next_parameters=None):
    if source == "usaspending":
        return {"source": source, "endpoint": USA, "method": "POST",
                "parameters": {"award_id": award["generated_id"], "page": page, "limit": size,
                               "sort": "action_date", "order": "asc"}}
    parameters = {"FEEDNAME": "PUBLIC", "q": fpds_query(award), "length": 10}
    if next_parameters:
        if set(next_parameters)-{"start","index","s","VERSION"}:
            raise EvidenceError("fpds_next_scope_conflict")
        parameters.update(next_parameters)
    return {"source": source, "endpoint": FPDS, "method": "GET", "parameters": parameters}


def safe_next(href, request):
    if (request.get("endpoint")!=FPDS or request.get("method")!="GET"
            or request.get("parameters",{}).get("FEEDNAME")!="PUBLIC"
            or request["parameters"].get("length")!=10 or not isinstance(request["parameters"].get("q"),str)):
        raise EvidenceError("invalid_fpds_request_scope")
    if not isinstance(href, str) or not href or len(href) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in href) or "\\" in href or "#" in href:
        raise EvidenceError("unsafe_fpds_next_url")
    try:
        literal = urlsplit(href)
        if any(p in (".", "..") for p in literal.path.split("/")):
            raise EvidenceError("unsafe_fpds_next_url")
        url = urlsplit(urljoin(FPDS, href))
    except ValueError:
        raise EvidenceError("unsafe_fpds_next_url") from None
    base = urlsplit(FPDS)
    if (url.scheme, url.netloc, url.path) != (base.scheme, base.netloc, base.path) or url.fragment:
        raise EvidenceError("unsafe_fpds_next_url")
    if re.search(r"%(?![0-9a-fA-F]{2})", url.query) or any("%" in part.split("=",1)[0] for part in url.query.split("&")):
        raise EvidenceError("invalid_fpds_next_encoding")
    try:
        params = parse_qs(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8, errors="strict")
    except (ValueError, UnicodeError):
        raise EvidenceError("invalid_fpds_next_parameters") from None
    if any(len(v) != 1 for v in params.values()) or set(params) - {"q", "FEEDNAME", "length", "start", "index", "s", "VERSION"}:
        raise EvidenceError("unsupported_fpds_next_parameters")
    if any(any(ord(c)<32 or ord(c)==127 for c in k+v[0]) for k,v in params.items()):
        raise EvidenceError("invalid_fpds_next_encoding")
    for name in ("q", "FEEDNAME", "length"):
        if name in params and params[name][0] != str(request["parameters"][name]):
            raise EvidenceError("fpds_next_scope_conflict")
    result = {}
    for key in ("start", "index"):
        if key in params:
            value = params[key][0]
            if not re.fullmatch(r"[0-9]{1,8}", value):
                raise EvidenceError("invalid_fpds_offset")
            result[key] = int(value)
    # Exact, evidence-backed tokens, never arbitrary strings or an opaque cursor.
    # Omitted tokens inherit the established request, so omission cannot silently
    # switch a negotiated feed/backend. Explicit changes are rejected.
    for key, allowed in (("VERSION",(FPDS_FEED_VERSION,)),("s",FPDS_BACKENDS)):
        current = request["parameters"].get(key)
        value = params[key][0] if key in params else current
        if value is not None:
            if value not in allowed:
                raise EvidenceError("unsupported_fpds_next_parameters")
            if current is not None and value != current:
                raise EvidenceError("fpds_continuation_protocol_changed")
            result[key] = value
    if result.get("s")=="FPDS" and result.get("VERSION")!=FPDS_FEED_VERSION:
        raise EvidenceError("unsupported_fpds_next_parameters")
    if len(set(result) & {"start", "index"}) != 1:
        raise EvidenceError("missing_or_ambiguous_fpds_offset")
    key = "start" if "start" in result else "index"
    current_keys = set(request["parameters"]) & {"start", "index"}
    if current_keys and current_keys != {key}:
        raise EvidenceError("fpds_offset_protocol_changed")
    previous = request["parameters"].get(key, 0)
    if type(previous) is not int or result[key] != previous + 10:
        raise EvidenceError("noncontiguous_fpds_offset")
    # Reconstruct only validated offsets; retain the selected PIID/agency query.
    return result


def parse_page(source, raw, request, award):
    if source == "usaspending":
        body = strict_json(raw)
        if (not isinstance(body, dict) or not isinstance(body.get("results"), list)
                or not isinstance(body.get("page_metadata"), dict)):
            raise EvidenceError("unsupported_transaction_schema")
        rows, meta = body["results"], body["page_metadata"]
        if (any(not isinstance(r, dict) for r in rows) or type(meta.get("hasNext")) is not bool
                or type(meta.get("page")) is not int or meta["page"] != request["parameters"]["page"]
                or len(rows) > request["parameters"]["limit"] or not rows and meta["hasNext"]):
            raise EvidenceError("invalid_transaction_pagination")
        contexts = []
        for row in rows:
            context = "query_bound_candidate"
            if not isinstance(row.get("id"), str) or not row["id"].strip():
                context = "missing_action_identifier"
            elif (not isinstance(row.get("action_date"), str) or not row["action_date"]
                  or any(key not in row for key in ("modification_number", "federal_action_obligation"))):
                context = "incomplete_transaction_record"
            elif (row["modification_number"] is not None and not isinstance(row["modification_number"], str)
                  or row["federal_action_obligation"] is not None and type(row["federal_action_obligation"]) not in (int, float)):
                context = "unsupported_action_field_type"
            if row.get("award_id") is not None and row["award_id"] != award["generated_id"]:
                context = "nonmatching_award_identifier"
            for name in ("id", "modification_number"):
                value = row.get(name)
                if value is not None and (not isinstance(value, str) or any(ord(c) < 32 for c in value)):
                    context = "unsupported_identifier_type"
            contexts.append(context)
        return {"rows": rows, "contexts": contexts, "has_next": meta["hasNext"],
                "next_parameters": None, "source_updates": [], "fingerprints": [digest(r) for r in rows]}
    _, root = safe_xml(raw)
    if root.tag != ATOM + "feed":
        raise EvidenceError("unsupported_fpds_schema")
    for link in root:
        if link.tag.rsplit("}",1)[-1]=="link" and (link.get("rel") or "").strip().lower()=="next":
            if link.tag!=ATOM+"link" or link.get("rel")!="next":
                raise EvidenceError("unsupported_fpds_next_relation")
    links = [link.get("href") for link in root.findall(ATOM + "link") if link.get("rel") == "next"]
    if len(links) > 1 or links and not links[0]:
        raise EvidenceError("ambiguous_fpds_next_url")
    following = safe_next(links[0], request) if links else None
    rows, contexts, updates, fingerprints = [], [], [], []
    for entry in root.findall(ATOM + "entry"):
        contents = entry.findall(ATOM + "content")
        awards = [n for content in contents for n in content
                  if n.tag in tuple("{" + ns + "}award" for ns in FPDS_NAMESPACES)]
        namespace = awards[0].tag.split("}")[0] + "}" if len(awards) == 1 else ""
        award_ids = awards[0].findall(namespace + "awardID") if len(awards) == 1 else []
        contracts = award_ids[0].findall(namespace + "awardContractID") if len(award_ids) == 1 else []

        def identifiers(container, names):
            result = {}
            for node in container:
                name = node.tag.rsplit("}", 1)[-1]
                if name not in names:
                    continue
                if node.tag != namespace + name:
                    raise EvidenceError("unsupported_fpds_identifier_namespace")
                if name in result:
                    raise EvidenceError("conflicting_fpds_identifiers")
                result[name] = node.text
            return result

        record = {"atom_id": entry.findtext(ATOM + "id"), "updated": entry.findtext(ATOM + "updated")}
        record_links = [n.get("href") for n in entry.findall(ATOM + "link") if n.get("rel") == "alternate"]
        record["source_record_url"] = record_links[0] if len(record_links) == 1 else None
        context = "missing_award_context"
        if len(contracts) == 1:
            record.update(identifiers(contracts[0], ("PIID", "agencyID", "modNumber", "transactionNumber")))
            if record.get("PIID") == award["piid"] and record.get("agencyID") == award["agency_id"]:
                context = "query_bound_candidate"
                if not record.get("modNumber") or not record.get("transactionNumber"):
                    context = "missing_action_identifier"
            elif record.get("PIID") and record.get("agencyID"):
                context = "nonmatching_piid_or_agency"
        elif len(contracts) > 1 or len(awards) > 1 or len(award_ids) > 1:
            context = "ambiguous_award_context"
        for parent_name, name in (("relevantContractDates", "effectiveDate"), ("relevantContractDates", "signedDate"),
                                  ("dollarValues", "obligatedAmount"), ("totalDollarValues", "totalObligatedAmount")):
            values = awards[0].findall(namespace + parent_name + "/" + namespace + name) if len(awards) == 1 else []
            if len(values) == 1:
                record[name] = values[0].text
        parents = award_ids[0].findall(namespace + "referencedIDVID") if len(award_ids) == 1 else []
        record["parent_context"] = [identifiers(parent, ("PIID", "agencyID", "modNumber")) for parent in parents]
        if len(parents) > 1:
            context = "ambiguous_parent_context"
        if award.get("parent_piid") is not None:
            parent = record["parent_context"][0] if len(parents) == 1 else {}
            if parent.get("PIID") != award["parent_piid"] or parent.get("agencyID") != award["parent_agency_id"]:
                context = "nonmatching_or_missing_parent_context"
        if record["updated"]:
            updates.append(record["updated"])
        rows.append(record)
        contexts.append(context)
        fingerprints.append(digest({"entry_xml": ET.tostring(entry, encoding="unicode")}))
    if len(rows) > 10 or not rows and following is not None:
        raise EvidenceError("invalid_fpds_pagination")
    return {"rows": rows, "contexts": contexts, "has_next": following is not None,
            "next_parameters": following, "source_updates": updates, "fingerprints": fingerprints,
            "next_href":links[0] if links else None,"continuation_rule":FPDS_CONTINUATION_RULE}


class HTTPTransport:
    def __init__(self, limits, session=None):
        if limits["pace_seconds"] < 0.25:
            raise EvidenceError("live_pacing_too_fast")
        self.limits = limits
        self.session = session or requests.Session()

    def __call__(self, request, sequence):
        raw = bytearray()
        status = update = retry = None
        complete = False
        error = None
        response = None
        try:
            kwargs = {"json" if request["method"] == "POST" else "params": request["parameters"]}
            response = self.session.request(request["method"], request["endpoint"],
                                            timeout=(self.limits["timeout_seconds"], self.limits["timeout_seconds"]),
                                            allow_redirects=False, stream=True, **kwargs)
            status = response.status_code  # Do not use Response truthiness.
            retry = response.headers.get("Retry-After")
            update = response.headers.get("Last-Modified")
            for chunk in response.iter_content(chunk_size=65536):
                remaining = self.limits["max_response_bytes"] - len(raw)
                raw.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    error = "response_size_limit"
                    break
            else:
                complete = True
        except requests.exceptions.SSLError:
            error = "tls_error"
        except requests.Timeout:
            error = "timeout"
        except requests.ConnectionError:
            error = "connection_error"
        except requests.RequestException:
            error = "request_error"
        finally:
            if response is not None:
                response.close()
        def safe_header(value):
            return value if isinstance(value, str) and len(value) <= 256 and not any(ord(c) < 32 for c in value) else None
        return {"status": status, "retrieved_at_utc": utcnow() if status is not None else None,
                "body_complete": complete, "error_code": error,
                "retry_after": safe_header(retry), "source_update_raw": safe_header(update)}, bytes(raw) if status is not None else None


class FixtureTransport:
    """Explicit synthetic transport; never a production fallback."""
    def __init__(self, scenario):
        if not isinstance(scenario, dict) or set(scenario) != {"schema_version", "responses"} or type(scenario["schema_version"]) is not int or scenario["schema_version"] != 1 or not isinstance(scenario["responses"], list):
            raise EvidenceError("invalid_fixture_scenario")
        allowed = {"source", "status", "json", "text", "retrieved_at_utc", "body_complete", "error_code", "retry_after", "source_update_raw"}
        for item in scenario["responses"]:
            if (not isinstance(item, dict) or set(item) - allowed or item.get("source") not in ("usaspending", "fpds")
                    or "json" in item and "text" in item
                    or "json" in item and not isinstance(item["json"], dict)
                    or "text" in item and not isinstance(item["text"], str)):
                raise EvidenceError("invalid_fixture_response")
        canonical(scenario)  # Reject nonfinite values even for injected fixtures.
        self.scenario = scenario

    def __call__(self, request, sequence):
        if sequence >= len(self.scenario["responses"]):
            raise EvidenceError("fixture_exhausted")
        item = self.scenario["responses"][sequence]
        if item.get("source") != request["source"]:
            raise EvidenceError("fixture_source_conflict")
        raw = canonical(item["json"]).encode() if "json" in item else item.get("text", "").encode()
        status = item.get("status", 200)
        return {"status": status, "retrieved_at_utc": item.get("retrieved_at_utc", "2025-01-01T00:00:00Z") if status is not None else None,
                "body_complete": item.get("body_complete", True), "error_code": item.get("error_code"),
                "retry_after": item.get("retry_after"), "source_update_raw": item.get("source_update_raw")}, raw if status is not None else None
