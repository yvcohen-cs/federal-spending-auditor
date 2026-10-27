"""Bounded deterministic C4 rules. No network, financial arithmetic or name matching."""
from __future__ import annotations

from dataclasses import replace

from .evidence import ComparisonStatus as Status, SourceIdentifier
from .evidence_io import EvidenceError, canonical
from .matching_models import (ActionIdentityCandidate, AwardIdentityCandidate,
                              IdentifierState as State, IdentityComponent,
                              MatchDecision, MatchLimits, MatchRunSummary, Relation,
                              SourceRecordIdentity, ordered)


def component(raw=None, *, basis="source_field", sentinel=False):
    if raw is None or raw == "" or sentinel and raw in ("-NONE-", "-none-"):
        return IdentityComponent(state=State.ABSENT, original_json=canonical(raw), basis=basis)
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        return IdentityComponent(state=State.MALFORMED, original_json=canonical(raw), basis=basis)
    return IdentityComponent(state=State.VALID, original_json=canonical(raw), basis=basis, value=raw)


def agency_component(value):
    # FPDS dictionaries specify a four-character code. No top-tier/sub-tier
    # crosswalk, numeric coercion, padding, or case folding is justified here.
    if value.state is State.VALID and (len(value.value) != 4 or not value.value.isascii() or not value.value.isalnum()):
        return replace(value, state=State.MALFORMED, value=None)
    return value


def decode_usa_id(raw):
    """Pinned Treasury CONT_TX rule; ambiguous separators/unknown formats fail closed.

    No splitting of generated award request IDs or assumed agency crosswalks.
    Sentinel components mean unavailable, never asserted parent absence.
    """
    empty = component(basis="unavailable")
    result = dict.fromkeys(("agency", "parent_agency", "piid", "modification", "parent_piid", "transaction"), empty)
    native = component(raw)
    if native.state is not State.VALID:
        return result, ("missing_or_malformed_native_transaction_id",)
    if not raw.startswith("CONT_TX_"):
        return result, ("unsupported_native_transaction_id_format",)
    tokens = raw[len("CONT_TX_"):].split("_")
    if len(tokens) != 6:
        return result, ("ambiguous_native_transaction_id_separators",)
    result = {name: component(value, basis="usa_cont_tx_v1", sentinel=True)
              for name, value in zip(result, tokens)}
    return result, ()


def identify(source, row, evidence, content_sha256):
    """Only called with validated C3 rows and verified evidence references."""
    issues = []
    if source == "usaspending":
        fields, issue = decode_usa_id(row.get("id"))
        native_action_id = component(row.get("id"))
        if issue and native_action_id.state is State.VALID:
            native_action_id = replace(native_action_id, state=State.UNSUPPORTED, value=None)
        issues.extend(issue)
        mod = component(row.get("modification_number"))
        if fields["modification"].value is not None and mod.value is not None and fields["modification"].value != mod.value:
            fields["modification"] = replace(mod, state=State.CONFLICTING, value=None)
            issues.append("native_id_and_modification_field_conflict")
        elif mod.state is not State.VALID:
            fields["modification"] = mod
            issues.append("missing_or_malformed_modification_field")
        values = [("id", row.get("id")), ("modification_number", row.get("modification_number"))]
        context = {k: row[k] for k in ("action_date", "action_type", "action_type_description") if k in row}
    else:
        native_action_id = component(row.get("atom_id"))
        fields = {key: component(row.get(native)) for key, native in
                  (("piid", "PIID"), ("agency", "agencyID"), ("modification", "modNumber"), ("transaction", "transactionNumber"))}
        parents = row.get("parent_context", [])
        for key, name in (("parent_piid", "PIID"), ("parent_agency", "agencyID")):
            fields[key] = component(parents[0].get(name)) if len(parents) == 1 else component(basis="unavailable")
            if len(parents) > 1:
                fields[key] = IdentityComponent(state=State.CONFLICTING, original_json=canonical(parents), basis="source_field")
        if len(parents) > 1:
            issues.append("conflicting_parent_contexts")
        values = [(key, row.get(key)) for key in ("atom_id", "PIID", "agencyID", "modNumber", "transactionNumber")]
        context = {k: row[k] for k in ("updated", "effectiveDate", "signedDate") if k in row}
    for name in ("agency", "parent_agency"):
        fields[name] = agency_component(fields[name])
    native_ids = ordered(SourceIdentifier(source=source, namespace=k, value=v) for k, v in values if component(v).state is State.VALID)
    return SourceRecordIdentity(source=source, content_sha256=content_sha256,
                                native_identifiers=native_ids, native_action_id=native_action_id, evidence=ordered(evidence),
                                issues=tuple(sorted(issues)), context_json=canonical(context), **fields)


AWARD_FIELDS = ("piid", "agency", "parent_piid", "parent_agency")
ACTION_FIELDS = AWARD_FIELDS + ("modification", "transaction")


def key_for(record, fields):
    values = tuple(getattr(record, f).value for f in fields)
    return values if all(v is not None for v in values) else None


def relationship(left, right, fields):
    conflicts, unknown = [], []
    for name in fields:
        a, b = getattr(left, name), getattr(right, name)
        if State.CONFLICTING in (a.state, b.state):
            conflicts.append("internally_conflicting_" + name)
        elif a.value is None or b.value is None:
            unknown.append(name)
        elif a.value != b.value:
            conflicts.append(name)
    if conflicts:
        return Relation.CONFLICT, tuple("conflicting_" + k for k in conflicts)
    if unknown:
        return Relation.POSSIBLE, tuple("unknown_" + k for k in unknown)
    return Relation.EXACT, ("exact_documented_native_components",)


def group_candidates(subject, targets, fields, candidate_type):
    groups = {}
    for record in targets:
        # Missing components never group unrelated records by a partial key.
        key = key_for(record, fields) or (record.record_id,)
        groups.setdefault(key, []).append(record)
    result = []
    for records in groups.values():
        relation, reasons = relationship(subject, records[0], fields)
        result.append(candidate_type(record_ids=tuple(sorted(r.record_id for r in records)),
                                     relation=relation, reasons=reasons,
                                     evidence=ordered(e for r in records for e in r.evidence)))
    return ordered(result)


def decide(candidates):
    plausible = [c for c in candidates if c.relation is not Relation.CONFLICT]
    if len(plausible) > 1:
        return Status.AMBIGUOUS_MATCH, ("multiple_plausible_candidates",)
    if any("internally_conflicting" in reason for c in candidates for reason in c.reasons):
        return Status.UNRESOLVED_DISCREPANCY, ("internally_conflicting_candidate_identifiers",)
    if len(plausible) == 1:
        if plausible[0].relation is Relation.EXACT:
            return Status.VERIFIED_MATCH, ("unique_exact_identity_in_observed_candidates",)
        return Status.INSUFFICIENT_EVIDENCE, ("incomplete_identifier_context",)
    if candidates:
        return Status.UNRESOLVED_DISCREPANCY, ("observed_candidate_identifier_conflict",)
    return Status.INSUFFICIENT_EVIDENCE, ("no_observed_counterpart_not_evidence_of_absence",)


def match_records(records, *, input_manifest_sha256, limits=None, coverage=(), excluded_artifacts=()):
    """Pure typed-record engine; filesystem workflow revalidates all references first.

    Exceeding any limit fails the entire run, never selects/truncates candidates.
    """
    limits = limits or MatchLimits()
    if len(records) > limits.max_records:
        raise EvidenceError("matching_record_limit")
    # Identical retrieval content can consolidate observations, never amounts.
    merged = {}
    for record in records:
        prior = merged.get(record.record_id)
        if prior:
            if replace(prior, evidence=record.evidence) != record:
                raise EvidenceError("conflicting_record_integrity_metadata")
            record = replace(record, evidence=ordered(prior.evidence + record.evidence))
        merged[record.record_id] = record
    records = ordered(merged.values())
    work = 8 * sum(r.source == "usaspending" for r in records) * sum(r.source == "fpds" for r in records)
    if work > limits.max_comparisons:
        raise EvidenceError("matching_comparison_limit")
    decisions, work = evaluate_decisions(records, limits=limits)
    return MatchRunSummary(input_manifest_sha256=input_manifest_sha256, records=records, decisions=decisions,
                           coverage=ordered(coverage), excluded_artifacts=ordered(excluded_artifacts), comparisons=work, limits=limits)


def evaluate_decisions(records, *, limits=None):
    """Four pair stages, charged twice to include run-schema rule validation."""
    limits = limits or MatchLimits(max_records=10000, max_candidates=1000, max_comparisons=100000)
    if len(records) > limits.max_records:
        raise EvidenceError("matching_record_limit")
    usa = [r for r in records if r.source == "usaspending"]
    fpds = [r for r in records if r.source == "fpds"]
    work = 8 * len(usa) * len(fpds)
    if work > limits.max_comparisons:
        raise EvidenceError("matching_comparison_limit")
    decisions = []
    # Contradictory observed versions of a native action cannot be silently picked.
    native_groups = {}
    for r in records:
        k = key_for(r, ACTION_FIELDS)
        if k:
            native_groups.setdefault((r.source, k), set()).add(r.record_id)
        for native in r.native_identifiers:
            if native.namespace in ("id", "atom_id"):
                native_groups.setdefault((r.source, native.namespace, native.value), set()).add(r.record_id)

    # Conflict evidence expansion can exceed the ordinary cross-source pair
    # traversal. Charge a conservative bound before expanding any such group,
    # including the second evaluation in MatchRunSummary validation.
    work += 16 * max(1, len(usa)) * sum(len(ids) ** 2 for ids in native_groups.values() if len(ids) > 1)
    if work > limits.max_comparisons:
        raise EvidenceError("matching_comparison_limit")

    by_id = {r.record_id: r for r in records}

    def conflict_records(r, *, award_only=False):
        keys = [(r.source, key_for(r, ACTION_FIELDS))]
        keys.extend((r.source, n.namespace, n.value) for n in r.native_identifiers if n.namespace in ("id", "atom_id"))
        ids = {rid for k in keys if len(native_groups.get(k, ())) > 1 for rid in native_groups[k]}
        if award_only:
            ids = {rid for rid in ids if key_for(by_id[rid], AWARD_FIELDS) != key_for(r, AWARD_FIELDS)}
        return [by_id[rid] for rid in sorted(ids)]

    for subject in usa:
        # A known different PIID is outside this claim. Keep every source record
        # in the report, but never call PIID equality alone a match.
        targets = [r for r in fpds if subject.piid.value is None or r.piid.value is None or r.piid.value == subject.piid.value]
        awards = group_candidates(subject, targets, AWARD_FIELDS, AwardIdentityCandidate)
        if len(awards) > limits.max_candidates:
            raise EvidenceError("matching_candidate_limit")
        award_status, reasons = decide(awards)
        award_conflicts = [other for r in [subject] + targets for other in conflict_records(r, award_only=True)]
        if award_conflicts:
            award_status, reasons = Status.UNRESOLVED_DISCREPANCY, ("native_record_identifier_has_conflicting_award_contexts",)
        evidence = ordered(subject.evidence + tuple(e for c in awards for e in c.evidence)
                           + tuple(e for r in award_conflicts for e in r.evidence))
        decisions.append(MatchDecision(subject_record_id=subject.record_id, claim="award_association",
                                       status=award_status, reasons=reasons, evidence=evidence, award_candidates=awards))
        # Different known modifications are different actions, not a discrepancy.
        actions = [r for r in targets if relationship(subject, r, AWARD_FIELDS)[0] is not Relation.CONFLICT
                   and (subject.modification.value is None or r.modification.value is None or subject.modification.value == r.modification.value)]
        candidates = group_candidates(subject, actions, ACTION_FIELDS, ActionIdentityCandidate)
        if len(candidates) > limits.max_candidates:
            raise EvidenceError("matching_candidate_limit")
        status, reasons = decide(candidates)
        action_conflicts = [other for r in [subject] + actions for other in conflict_records(r)]
        if award_status is not Status.VERIFIED_MATCH:
            status, reasons = Status.INSUFFICIENT_EVIDENCE, ("award_identity_not_established",)
        elif State.CONFLICTING in (subject.modification.state, subject.transaction.state) or action_conflicts:
            status, reasons = Status.UNRESOLVED_DISCREPANCY, ("conflicting_native_action_fields_or_observed_versions",)
        evidence = ordered(subject.evidence + tuple(e for c in candidates for e in c.evidence)
                           + tuple(e for r in action_conflicts for e in r.evidence))
        # Award evidence establishes the action's prerequisite even when absent.
        evidence = ordered(evidence + tuple(e for c in awards if c.relation is Relation.EXACT for e in c.evidence))
        decisions.append(MatchDecision(subject_record_id=subject.record_id, claim="action_equivalence", status=status,
                                       reasons=reasons, evidence=evidence, action_candidates=candidates))
    return ordered(decisions), work
