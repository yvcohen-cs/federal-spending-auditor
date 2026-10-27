"""C4 v1 companion contracts. Identity association is never financial verification."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .evidence import (ComparisonStatus, Completeness, EvidenceArtifact,
                       EvidenceRecordRef, Schema, SourceIdentifier, _hash, _text,
                       _timestamp)
from .evidence_io import canonical, digest, strict_json


RULE_VERSION = "identity-v1"


@dataclass(frozen=True, kw_only=True)
class MatchLimits(Schema):
    max_records: int = 1000
    max_candidates: int = 100
    max_comparisons: int = 10000

    def validate(self):
        if not 1 <= self.max_records <= 10000 or not 1 <= self.max_candidates <= 1000 or not 1 <= self.max_comparisons <= 100000:
            raise ValueError("matching limits exceed supported bounds")


class IdentifierState(str, Enum):
    VALID = "valid"
    ABSENT = "absent"
    MALFORMED = "malformed"
    UNSUPPORTED = "unsupported"
    CONFLICTING = "conflicting"


class Relation(str, Enum):
    EXACT = "exact"
    POSSIBLE = "possible"
    CONFLICT = "conflict"


class _ComputedIdentity(Schema):
    """Expose constructed link IDs on the wire and verify their declarations."""
    _computed_name = ""

    def to_dict(self, *, substantive=False):
        return {**super().to_dict(substantive=substantive),
                self._computed_name: getattr(self, self._computed_name)}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or cls._computed_name not in value:
            raise ValueError("explicit constructed identifier required")
        result = super().from_dict({k: v for k, v in value.items() if k != cls._computed_name})
        if value[cls._computed_name] != getattr(result, cls._computed_name):
            raise ValueError("constructed identifier conflicts with contents")
        return result


@dataclass(frozen=True, kw_only=True)
class IdentityComponent(Schema):
    """Original field or decoded native-ID component; never a fabricated native ID."""
    state: IdentifierState
    original_json: str
    basis: str
    value: str | None = None

    def validate(self):
        original = strict_json(self.original_json.encode())
        if canonical(original) != self.original_json:
            raise ValueError("canonical original required")
        if self.basis not in ("source_field", "usa_cont_tx_v1", "unavailable"):
            raise ValueError("unsupported identity basis")
        if self.state is IdentifierState.VALID:
            if not isinstance(original, str) or self.value != original or self.basis == "unavailable":
                raise ValueError("valid component must preserve exact source text")
            _text(self.value, "identifier")
            if len(self.value) > 256:
                raise ValueError("oversized identifier")
        elif self.value is not None:
            raise ValueError("unusable identifier cannot have a comparison value")
        if self.state is IdentifierState.ABSENT and original is not None and original not in ("", "-NONE-", "-none-"):
            raise ValueError("absent must retain null, blank, or documented sentinel")


@dataclass(frozen=True, kw_only=True)
class MatchEvidenceReference(Schema):
    reference: EvidenceRecordRef
    artifact: EvidenceArtifact
    observation_id: str
    metadata_paths: tuple[str, ...]

    def validate(self):
        from .evidence_io import parts
        if (self.reference.artifact_id != self.artifact.artifact_id
                or self.reference.source != self.artifact.source
                or not self.observation_id.startswith("observation:v1:")):
            raise ValueError("evidence provenance conflict")
        _hash(self.observation_id.removeprefix("observation:v1:"))
        if not self.metadata_paths or self.metadata_paths != tuple(sorted(set(self.metadata_paths))):
            raise ValueError("verified metadata paths required")
        for path in self.metadata_paths:
            parts(path)
        if any(x is None for x in (self.artifact.endpoint, self.artifact.method,
                                   self.artifact.request_json, self.artifact.retrieved_at_utc)):
            raise ValueError("documented observation provenance required")
        a = self.artifact
        expected = "observation:v1:" + digest({"version": 1, "source": a.source, "endpoint": a.endpoint,
                     "method": a.method, "request_json": a.request_json,
                     "retrieved_at_utc": a.retrieved_at_utc, "representation": a.representation.value})
        if self.observation_id != expected:
            raise ValueError("observation ID contradicts provenance")


def ordered(values):
    """Canonical ordering/deduplication of typed objects, independent of input order."""
    return tuple(sorted(set(values), key=lambda v: v.to_json()))


@dataclass(frozen=True, kw_only=True)
class SourceRecordIdentity(_ComputedIdentity):
    _computed_name = "record_id"
    source: str
    content_sha256: str
    native_identifiers: tuple[SourceIdentifier, ...]
    native_action_id: IdentityComponent
    evidence: tuple[MatchEvidenceReference, ...]
    piid: IdentityComponent
    agency: IdentityComponent
    parent_piid: IdentityComponent
    parent_agency: IdentityComponent
    modification: IdentityComponent
    transaction: IdentityComponent
    issues: tuple[str, ...] = ()
    context_json: str = "{}"

    @property
    def record_id(self):
        # Retrieval grouping only, never real-world or contractor identity.
        return "record:v1:" + digest({"source": self.source, "content": self.content_sha256})

    def validate(self):
        _hash(self.content_sha256)
        if self.source not in ("usaspending", "fpds") or not self.evidence:
            raise ValueError("supported source and evidence required")
        if self.evidence != ordered(self.evidence) or self.native_identifiers != ordered(self.native_identifiers):
            raise ValueError("canonical unique evidence/identifiers required")
        if any(r.reference.source != self.source for r in self.evidence) or any(i.source != self.source for i in self.native_identifiers):
            raise ValueError("source conflict")
        if len({n.namespace for n in self.native_identifiers}) != len(self.native_identifiers):
            raise ValueError("conflicting native identifier namespaces")
        if self.issues != tuple(sorted(set(self.issues))):
            raise ValueError("canonical issues required")
        context = strict_json(self.context_json.encode())
        if not isinstance(context, dict) or canonical(context) != self.context_json:
            raise ValueError("canonical context required")


@dataclass(frozen=True, kw_only=True)
class AwardIdentityCandidate(_ComputedIdentity):
    _computed_name = "candidate_id"
    record_ids: tuple[str, ...]
    relation: Relation
    reasons: tuple[str, ...]
    evidence: tuple[MatchEvidenceReference, ...]

    @property
    def candidate_id(self):
        return "candidate:v1:" + digest({"kind": type(self).__name__, "records": self.record_ids})

    def validate(self):
        if not self.record_ids or self.record_ids != tuple(sorted(set(self.record_ids))) or not self.reasons or not self.evidence:
            raise ValueError("candidate needs records, rationale and evidence")
        for value in self.record_ids:
            if not value.startswith("record:v1:"):
                raise ValueError("constructed record reference required")
            _hash(value.removeprefix("record:v1:"))
        if self.evidence != ordered(self.evidence):
            raise ValueError("canonical evidence required")


@dataclass(frozen=True, kw_only=True)
class ActionIdentityCandidate(AwardIdentityCandidate):
    pass


@dataclass(frozen=True, kw_only=True)
class MatchDecision(_ComputedIdentity):
    _computed_name = "claim_id"
    subject_record_id: str
    claim: str
    status: ComparisonStatus
    reasons: tuple[str, ...]
    evidence: tuple[MatchEvidenceReference, ...]
    award_candidates: tuple[AwardIdentityCandidate, ...] = ()
    action_candidates: tuple[ActionIdentityCandidate, ...] = ()
    rule_version: str = RULE_VERSION

    @property
    def claim_id(self):
        return "identity-claim:v1:" + digest({"subject": self.subject_record_id, "claim": self.claim, "rules": self.rule_version})

    def validate(self):
        if not self.subject_record_id.startswith("record:v1:"):
            raise ValueError("constructed subject reference required")
        _hash(self.subject_record_id.removeprefix("record:v1:"))
        if self.claim not in ("award_association", "action_equivalence") or self.rule_version != RULE_VERSION:
            raise ValueError("unsupported identity claim/rules")
        if not self.reasons or not self.evidence or self.evidence != ordered(self.evidence):
            raise ValueError("decision evidence and rationale required")
        if self.claim == "award_association" and self.action_candidates or self.claim == "action_equivalence" and self.award_candidates:
            raise ValueError("claim/candidate dimension conflict")
        candidates = self.award_candidates or self.action_candidates
        if candidates != ordered(candidates):
            raise ValueError("canonical candidates required")
        if any(e not in self.evidence for c in candidates for e in c.evidence):
            raise ValueError("candidate evidence missing from decision")
        plausible = [c for c in candidates if c.relation is not Relation.CONFLICT]
        if self.status is ComparisonStatus.VERIFIED_MATCH:
            if len(plausible) != 1 or plausible[0].relation is not Relation.EXACT or len({e.reference.source for e in self.evidence}) != 2:
                raise ValueError("verified identity requires unique exact cross-source candidate")
        if self.status is ComparisonStatus.AMBIGUOUS_MATCH and len(plausible) < 2:
            raise ValueError("ambiguity needs distinct plausible candidates")
        if self.status is ComparisonStatus.EXPLAINABLE_DIFFERENCE:
            raise ValueError("no documented identity equivalence explanation rule in v1")


@dataclass(frozen=True, kw_only=True)
class MatchCoverage(Schema):
    artifact: EvidenceArtifact
    observation_id: str | None
    has_next: bool | None
    pagination: Completeness = Completeness.UNKNOWN
    transaction_history: Completeness = Completeness.UNKNOWN
    source_wide: Completeness = Completeness.UNKNOWN
    freshness: Completeness = Completeness.UNKNOWN
    query_scope: Completeness = Completeness.UNKNOWN

    def validate(self):
        if self.observation_id is not None:
            if not self.observation_id.startswith("observation:v1:"):
                raise ValueError("constructed observation reference required")
            _hash(self.observation_id.removeprefix("observation:v1:"))
        if self.pagination is not (Completeness.PARTIAL if self.has_next is True else Completeness.UNKNOWN):
            raise ValueError("a single terminal response cannot establish complete traversal")
        if any(v is not Completeness.UNKNOWN for v in (self.transaction_history, self.source_wide, self.freshness, self.query_scope)):
            raise ValueError("unsupported coverage assurance")


@dataclass(frozen=True, kw_only=True)
class ExcludedArtifact(Schema):
    relative_path: str
    reason: str

    def validate(self):
        from .evidence_io import parts
        parts(self.relative_path)
        _text(self.reason, "reason")


@dataclass(frozen=True, kw_only=True)
class MatchRunSummary(Schema):
    input_manifest_sha256: str
    records: tuple[SourceRecordIdentity, ...]
    decisions: tuple[MatchDecision, ...]
    coverage: tuple[MatchCoverage, ...] = ()
    excluded_artifacts: tuple[ExcludedArtifact, ...] = ()
    comparisons: int = 0
    limits: MatchLimits = field(default_factory=MatchLimits)
    rule_version: str = RULE_VERSION
    limitations: tuple[str, ...] = ("identity_association_only_not_financial_verification",
                                    "histories_freshness_and_query_scope_unknown")
    executed_at_utc: str | None = field(default=None, metadata={"execution": True})

    def validate(self):
        _hash(self.input_manifest_sha256)
        _timestamp(self.executed_at_utc)
        if self.rule_version != RULE_VERSION or self.comparisons < 0:
            raise ValueError("unsupported run rules/count")
        for sequence in (self.records, self.decisions, self.coverage, self.excluded_artifacts):
            if sequence != ordered(sequence):
                raise ValueError("canonical unique run members required")
        records = {r.record_id: r for r in self.records}
        if len(records) != len(self.records) or len({d.claim_id for d in self.decisions}) != len(self.decisions):
            raise ValueError("duplicate record/claim IDs")
        all_evidence = {e for r in self.records for e in r.evidence}
        for d in self.decisions:
            if d.subject_record_id not in records or records[d.subject_record_id].source != "usaspending":
                raise ValueError("unknown subject")
            if any(e not in all_evidence for e in d.evidence):
                raise ValueError("unregistered evidence")
            if any(e not in d.evidence for e in records[d.subject_record_id].evidence):
                raise ValueError("subject evidence missing from decision")
            for c in d.award_candidates + d.action_candidates:
                if any(r not in records or records[r].source != "fpds" for r in c.record_ids):
                    raise ValueError("unregistered candidate")
                expected = ordered(e for r in c.record_ids for e in records[r].evidence)
                if c.evidence != expected:
                    raise ValueError("candidate evidence/records conflict")
        # A serialized status cannot upgrade unresolved action identity merely
        # by replacing an enum. Recompute the deterministic rules on readback.
        from .identity_matching import evaluate_decisions
        expected, work = evaluate_decisions(self.records, limits=self.limits)
        if self.decisions != expected or self.comparisons != work:
            raise ValueError("decisions/count contradict deterministic identity rules")

    @property
    def substantive_sha256(self):
        return digest(self.to_dict(substantive=True))

    @property
    def counts(self):
        return {claim: {s.value: sum(d.claim == claim and d.status is s for d in self.decisions)
                        for s in ComparisonStatus} for claim in ("award_association", "action_equivalence")}

    @property
    def exit_code(self):
        return 0 if self.decisions and not self.excluded_artifacts and all(d.status is ComparisonStatus.VERIFIED_MATCH for d in self.decisions) else 1
