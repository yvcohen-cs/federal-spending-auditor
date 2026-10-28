"""C5 read-only adapter: money comes from preserved bytes, never C4 JSON floats."""
from __future__ import annotations

import re
from pathlib import Path

from .collection_sources import ATOM, FPDS_NAMESPACES
from .evidence_ingestion import inspect_directory
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, safe_xml, strict_json
from .financial_models import FinancialLimits, FinancialObservation, FPDS_ACTION, USA_ACTION, field_semantics, signed_date
from .financial_reconciliation import reconcile_observations
from .financial_values import NumberToken, RawKind, exact_json, monetary_value
from .matching_ingestion import match_collection
from .matching_models import MatchRunSummary


def read_identity_report(path):
    target = Path(path).absolute()
    with EvidenceRoot(target.parent, max_bytes=16 * 1024 * 1024, max_total_bytes=16 * 1024 * 1024) as root:
        before = root.read(target.name)
        doc = strict_json(before.data)
        payload = doc.get("report") if isinstance(doc, dict) and "report" in doc else doc
        identity = MatchRunSummary.from_dict(payload)
        if isinstance(doc, dict) and "report" in doc:
            expected = {"report": identity.to_dict(), "counts": identity.counts,
                        "substantive_sha256": identity.substantive_sha256, "exit_code": identity.exit_code}
            if digest(doc) != digest(expected):
                raise EvidenceError("invalid_identity_report_wrapper")
        after = root.read(target.name, recheck=True)
        if before.stamp != after.stamp or before.byte_sha256 != after.byte_sha256:
            raise EvidenceError("identity_report_changed")
    return identity


def _text(value):
    if value is None or type(value) is str:
        return value
    return canonical(value)


def _currency(node, container):
    # The defined USD unit comes from the field contract. Explicit incompatible
    # or unknown attributes cannot silently override it.
    if set(node.attrib) - {"currency"} or set(container.attrib) - {"currency"}:
        return "unsupported_amount_attributes"
    local, parent = node.get("currency"), container.get("currency")
    if any(child.tag.rsplit("}", 1)[-1].lower() in ("currency", "currencycode", "currency_code") for child in container):
        return "unsupported_currency_element"
    return "conflicting_currency_metadata" if local is not None and parent is not None and local != parent else (local if local is not None else parent)


def _fpds_fields(entry):
    awards = [node for content in entry.findall(ATOM + "content") for node in content
              if node.tag in tuple("{" + ns + "}award" for ns in FPDS_NAMESPACES)]
    if not awards:
        return None, [(FPDS_ACTION, RawKind.MISSING, None, None)]
    if len(awards) != 1:
        raise EvidenceError("ambiguous_financial_award_context")
    award = awards[0]
    ns = award.tag.split("}")[0] + "}"
    dates = award.findall(ns + "relevantContractDates")
    if len(dates) > 1:
        raise EvidenceError("ambiguous_financial_signed_date")
    signed = dates[0].findall(ns + "signedDate") if dates else []
    if len(signed) > 1 or any(len(n) or n.attrib for n in signed):
        raise EvidenceError("ambiguous_financial_signed_date")
    date_raw = signed[0].text if signed else None
    fields = {}
    for container_name in ("dollarValues", "totalDollarValues"):
        containers = award.findall(ns + container_name)
        if len(containers) > 1:
            raise EvidenceError("ambiguous_financial_xml_fields")
        for container in containers:
            for node in container:
                if node.tag.startswith(ns):
                    name = node.tag[len(ns):]
                else:
                    # No local-name fallback for monetary values.
                    raise EvidenceError("unsupported_financial_field_namespace")
                path = container_name + "/" + name
                if path in fields or len(node):
                    raise EvidenceError("ambiguous_financial_xml_fields")
                fields[path] = (path, RawKind.XML_TEXT if node.text is not None else RawKind.MISSING,
                                node.text, _currency(node, container))
    fields.setdefault(FPDS_ACTION, (FPDS_ACTION, RawKind.MISSING, None, None))
    return date_raw, list(fields.values())


def _usa_fields(row):
    fields = []
    names = {USA_ACTION} | {name for name in row if any(word in name.lower() for word in ("amount", "oblig", "outlay", "loan"))}
    currency = _text(row.get("currency"))
    for name in sorted(names):
        raw = row.get(name)
        if raw is None:
            kind, text = RawKind.MISSING, None
        elif isinstance(raw, NumberToken):
            kind, text = RawKind.JSON_NUMBER, str(raw)
        elif type(raw) is str:
            kind, text = RawKind.JSON_STRING, raw
        else:
            kind, text = RawKind.UNSUPPORTED, canonical(raw)
        fields.append((name, kind, text, currency))
    return _text(row.get("action_date")), fields


def reconcile_collection(path, *, identity_report_path=None, limits=None,scope_request=None):
    limits = limits or FinancialLimits()
    prior = read_identity_report(identity_report_path) if identity_report_path else None
    identity = match_collection(path, **({"limits": prior.limits} if prior else {}),**({"scope_request":scope_request} if scope_request is not None else {}))
    if prior is not None and prior.substantive_sha256 != identity.substantive_sha256:
        raise EvidenceError("stale_or_conflicting_identity_report")
    manifest = inspect_directory(path)
    if manifest.substantive_sha256 != identity.input_manifest_sha256:
        raise EvidenceError("financial_evidence_changed")
    expected = {e.relative_path: e.byte_sha256 for e in manifest.entries}
    observations = []
    with EvidenceRoot(path) as root:
        if set(root.discover()) != set(expected):
            raise EvidenceError("financial_evidence_changed")
        snapshots = {name: root.read(name) for name in expected}
        if scope_request is not None:
            # A scoped adapter may preserve an unsupported row in an otherwise
            # intact response. Pin those unused/partly usable body bytes through
            # their VERIFIED C3 metadata; never waive a declared hash mismatch.
            verified={e.relative_path for e in manifest.entries if e.status.value=='verified'}
            for name,sha in tuple(expected.items()):
                metadata=name[:-5]+'.json' if name.endswith('.body') else None
                if sha is None and metadata in verified:
                    expected[name]=strict_json(snapshots[metadata].data)['body_sha256']
        if any(snapshots[name].byte_sha256 != sha for name, sha in expected.items()):
            raise EvidenceError("financial_evidence_changed")
        parsed = {}
        for record in identity.records:
            for evidence in record.evidence:
                relative = evidence.artifact.relative_path
                raw = snapshots[relative]
                if raw.byte_sha256 != evidence.artifact.sha256:
                    raise EvidenceError("financial_artifact_hash_conflict")
                if relative not in parsed:
                    parsed[relative] = exact_json(raw.data) if record.source == "usaspending" else safe_xml(raw.data)[1]
                body = parsed[relative]
                locator = evidence.reference.locator
                pattern = r"/results/([0-9]+)" if record.source == "usaspending" else r"/feed/entry\[([0-9]+)\]"
                located = re.fullmatch(pattern, locator)
                if located is None:
                    raise EvidenceError("unsupported_financial_record_locator")
                index = int(located[1])
                if record.source == "usaspending":
                    row = body["results"][index]
                    date_raw, fields = _usa_fields(row)
                else:
                    entry = body.findall(ATOM + "entry")[index - 1]
                    date_raw, fields = _fpds_fields(entry)
                for name, kind, text, currency in fields:
                    if len(observations) >= limits.max_observations:
                        raise EvidenceError("financial_observation_limit")
                    if text is not None and len(text) > 4096:
                        raise EvidenceError("financial_field_size_limit")
                    if len(name) > 256 or date_raw is not None and len(date_raw) > 4096 or currency is not None and len(currency) > 256:
                        raise EvidenceError("financial_field_size_limit")
                    observations.append(FinancialObservation(record_id=record.record_id, source=record.source,
                                        original_field=name, value=monetary_value(kind, text), semantics=field_semantics(record.source, name),
                                        evidence=evidence, action_date_raw=date_raw, action_date=signed_date(date_raw), declared_currency_raw=currency))
        report = reconcile_observations(identity, observations, limits=limits)
        for name, before in snapshots.items():
            after = root.read(name, recheck=True)
            if before.stamp != after.stamp or before.byte_sha256 != after.byte_sha256:
                raise EvidenceError("financial_evidence_changed")
        if set(root.discover()) != set(expected):
            raise EvidenceError("financial_evidence_changed")
    return report
