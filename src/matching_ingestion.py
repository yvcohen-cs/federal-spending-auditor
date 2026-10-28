"""Read-only C3-to-C4 boundary. Revalidate bytes and locators; never collect."""
from __future__ import annotations

import re

from .collection_ingestion import validate_control
from .collection_sources import ATOM, FPDS_NAMESPACES, parse_page
from .evidence import Completeness
from .evidence_ingestion import ValidationStatus, inspect_directory
from .evidence_io import EvidenceError, EvidenceRoot, digest, safe_xml, strict_json
from .identity_matching import MatchLimits, identify, match_records
from .matching_models import ExcludedArtifact, MatchCoverage, MatchEvidenceReference


def match_collection(path, *, limits=None,scope_request=None):
    """One flat validated C3 journal. Partial valid responses remain explicit.

    A prior manifest alone is not trusted. Both C2 structural verification and
    snapshot rechecks are performed on the actual files used for matching.
    """
    if scope_request is not None:
        from .scope_ingestion import scoped_match_collection
        return scoped_match_collection(path,scope_request,limits=limits)
    limits = limits or MatchLimits()
    manifest = inspect_directory(path)
    if not manifest.complete or not manifest.entries or any(e.status in (ValidationStatus.INVALID, ValidationStatus.UNSUPPORTED) for e in manifest.entries):
        raise EvidenceError("invalid_matching_evidence")
    names = {e.relative_path for e in manifest.entries}
    controls = {"c3_plan.json", "c3_checkpoint.json", "c3_summary.json"}
    if not {"c3_plan.json", "c3_checkpoint.json"} <= names or any(n not in controls and not re.fullmatch(r"c3_attempt_\d{6}\.(body|json)", n) for n in names):
        raise EvidenceError("single_flat_c3_collection_required")
    records, coverage, exclusions = [], [], []
    with EvidenceRoot(path) as root:
        if set(root.discover()) != names:
            raise EvidenceError("matching_evidence_changed")
        snapshots = {e.relative_path: root.read(e.relative_path) for e in manifest.entries}
        if any(snapshots[e.relative_path].byte_sha256 != e.byte_sha256 for e in manifest.entries):
            raise EvidenceError("matching_evidence_changed")
        plan = strict_json(snapshots["c3_plan.json"].data)
        validate_control("c3_plan.json", plan)
        for entry in manifest.entries:
            if not entry.relative_path.endswith(".body"):
                # Network failures have metadata but no body; preserve exclusions.
                if re.fullmatch(r"c3_attempt_\d{6}\.json", entry.relative_path):
                    meta = strict_json(snapshots[entry.relative_path].data)
                    if meta["body_sha256"] is None:
                        exclusions.append(ExcludedArtifact(relative_path=entry.relative_path, reason="no_response_body"))
                continue
            observation = entry.observation
            meta = strict_json(snapshots[entry.relative_path[:-5] + ".json"].data)
            usable = entry.status is ValidationStatus.VERIFIED
            if observation is None:
                raise EvidenceError("missing_matching_observation")
            has_next = None
            if usable:
                req = meta["request"]
                selected = plan["awards"][req["task_index"] // len(plan["sources"])]
                fpds_fingerprints = None
                if req["source"] == "fpds":
                    fpds_fingerprints = _check_fpds_contexts(snapshots[entry.relative_path].data)
                parsed = parse_page(req["source"], snapshots[entry.relative_path].data, req, selected)
                has_next = parsed["has_next"]
                if len(parsed["rows"]) != len(observation.records):
                    raise EvidenceError("matching_locator_count_conflict")
                if len(records) + len(parsed["rows"]) > limits.max_records:
                    raise EvidenceError("matching_record_limit")
                fingerprints = fpds_fingerprints if fpds_fingerprints is not None else parsed["fingerprints"]
                for row, fingerprint, occurrence in zip(parsed["rows"], fingerprints, observation.records):
                    reference = MatchEvidenceReference(reference=occurrence.reference,
                                                       artifact=observation.artifact,
                                                       observation_id=observation.observation_id,
                                                       metadata_paths=observation.metadata_paths)
                    records.append(identify(req["source"], row, (reference,), fingerprint))
            else:
                exclusions.append(ExcludedArtifact(relative_path=entry.relative_path, reason="incomplete_or_unsuccessful_response"))
            coverage.append(MatchCoverage(artifact=observation.artifact, observation_id=observation.observation_id,
                                           has_next=has_next,
                                           pagination=Completeness.PARTIAL if has_next is True else Completeness.UNKNOWN))
        report = match_records(records, input_manifest_sha256=manifest.substantive_sha256,
                               limits=limits, coverage=coverage, excluded_artifacts=exclusions)
        # Includes controls and failed responses, never only matched record bytes.
        for name, before in snapshots.items():
            after = root.read(name, recheck=True)
            if before.stamp != after.stamp or before.byte_sha256 != after.byte_sha256:
                raise EvidenceError("matching_evidence_changed")
        if set(root.discover()) != names:
            raise EvidenceError("matching_evidence_changed")
    return report


def _check_fpds_contexts(raw):
    """Reject compound XML containers rather than taking a convenient first ID.

    C3 preserves these responses; C4 v1 cannot enumerate nested alternative
    award containers as independently substantiated source records.
    """
    _, tree = safe_xml(raw)
    fingerprints = []

    def structural(node):
        # Expanded names and untouched text/attributes; independent of global
        # ElementTree prefix registrations. This is retrieval grouping only.
        return {"tag": node.tag, "attributes": node.attrib, "text": node.text,
                "tail": node.tail, "children": [structural(child) for child in node]}

    for entry in tree.findall(ATOM + "entry"):
        fingerprints.append(digest(structural(entry)))
        contents = entry.findall(ATOM + "content")
        if len(contents) > 1 or len(entry.findall(ATOM + "id")) > 1:
            raise EvidenceError("unsupported_matching_fpds_context")
        awards = [n for content in contents for n in content
                  if n.tag in tuple("{" + ns + "}award" for ns in FPDS_NAMESPACES)]
        if len(awards) > 1:
            raise EvidenceError("unsupported_matching_fpds_context")
        for award in awards:
            ns = award.tag.split("}")[0] + "}"
            ids = award.findall(ns + "awardID")
            if len(ids) > 1 or any(len(i.findall(ns + "awardContractID")) > 1 for i in ids):
                raise EvidenceError("unsupported_matching_fpds_context")
    return fingerprints
