"""C6 v1 projections; automated status and human workflow are independent."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .evidence import ComparisonStatus, Schema, _text, _timestamp
from .evidence_io import digest
from .financial_models import FinancialComparison, FinancialObservation, FinancialRun
from .matching_models import MatchDecision, MatchEvidenceReference, SourceRecordIdentity, _ComputedIdentity, ordered


PACKET_RULE_VERSION = "review-packet-v1"


class ExplanationState(str, Enum):
    SUPPORTED = "supported"
    RULED_OUT = "ruled_out"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


CATALOG = (
    "amendments_modifications", "deobligations_corrections", "reporting_publication_delay",
    "fiscal_year_lifetime_scope", "incremental_cumulative_fields", "agency_parent_context",
    "missing_history", "pagination_api_coverage", "source_schema_changes", "rounding_precision",
)


@dataclass(frozen=True, kw_only=True)
class EvidenceCitation(_ComputedIdentity):
    _computed_name = "citation_id"
    evidence: MatchEvidenceReference
    kind: str = "direct_preserved_source_observation"

    @property
    def citation_id(self):
        return "citation:v1:" + digest(self.evidence.to_dict())

    def validate(self):
        if self.kind != "direct_preserved_source_observation":
            raise ValueError("reviewer assertions cannot become primary citations")


@dataclass(frozen=True, kw_only=True)
class SourceObservationSummary(Schema):
    identity: SourceRecordIdentity
    monetary_observations: tuple[FinancialObservation, ...]
    citation_ids: tuple[str, ...]

    def validate(self):
        if any(o.record_id != self.identity.record_id for o in self.monetary_observations):
            raise ValueError("source observation identity conflict")
        if self.monetary_observations != ordered(self.monetary_observations):
            raise ValueError("canonical monetary summaries required")
        expected = tuple(sorted(EvidenceCitation(evidence=e).citation_id for e in self.identity.evidence))
        if self.citation_ids != expected:
            raise ValueError("citation/observation conflict")


@dataclass(frozen=True, kw_only=True)
class ComparisonExplanation(Schema):
    scope: str
    compatibility: str
    reasoning: tuple[str, ...]
    agreement: str
    difference_usa_minus_fpds: str | None = None
    tolerance: str | None = None

    def validate(self):
        if not self.reasoning:
            raise ValueError("comparison reasoning required")
        for value in (self.scope, self.compatibility, self.agreement):
            _text(value, "explanation")


@dataclass(frozen=True, kw_only=True)
class AlternativeExplanation(Schema):
    code: str
    state: ExplanationState
    rationale: str
    citation_ids: tuple[str, ...] = ()

    def validate(self):
        if self.code not in CATALOG:
            raise ValueError("unsupported alternative explanation")
        _text(self.rationale, "rationale")
        if self.state in (ExplanationState.SUPPORTED, ExplanationState.RULED_OUT) and not self.citation_ids:
            raise ValueError("positive/negative explanation assertions need evidence")


@dataclass(frozen=True, kw_only=True)
class EvidenceLimitation(Schema):
    code: str
    detail: str
    citation_ids: tuple[str, ...] = ()

    def validate(self):
        _text(self.code, "limitation")
        _text(self.detail, "detail")


@dataclass(frozen=True, kw_only=True)
class RecommendedVerificationAction(Schema):
    instruction: str
    citation_ids: tuple[str, ...] = ()

    def validate(self):
        _text(self.instruction, "instruction")
        if len(self.instruction) > 4096:
            raise ValueError("oversized instruction")


@dataclass(frozen=True, kw_only=True)
class ReviewedClaim(Schema):
    """A reviewable automated claim, not a declaration that human review occurred."""
    claim_id: str
    status: ComparisonStatus
    identity_result: MatchDecision | None = None
    financial_result: FinancialComparison | None = None

    def validate(self):
        results = [r for r in (self.identity_result, self.financial_result) if r is not None]
        if len(results) != 1 or self.claim_id != results[0].claim_id or self.status is not results[0].status:
            raise ValueError("claim/status must preserve exactly one automated result")


@dataclass(frozen=True, kw_only=True)
class ReviewPacket(_ComputedIdentity):
    _computed_name = "packet_id"
    input_financial_sha256: str
    claim: ReviewedClaim
    sources: tuple[SourceObservationSummary, ...]
    citations: tuple[EvidenceCitation, ...]
    comparison: ComparisonExplanation
    alternatives: tuple[AlternativeExplanation, ...]
    limitations: tuple[EvidenceLimitation, ...]
    unresolved_questions: tuple[str, ...]
    recommended_actions: tuple[RecommendedVerificationAction, ...]
    rule_version: str = PACKET_RULE_VERSION

    @property
    def packet_id(self):
        return "review-packet:v1:" + digest({"claim": self.claim.claim_id,
              "input": self.input_financial_sha256, "rules": self.rule_version})

    def validate(self):
        from .evidence import _hash
        _hash(self.input_financial_sha256)
        if self.rule_version != PACKET_RULE_VERSION:
            raise ValueError("unsupported packet rules")
        for sequence in (self.sources, self.citations, self.alternatives, self.limitations, self.recommended_actions):
            if sequence != ordered(sequence):
                raise ValueError("canonical packet members required")
        citations = {c.citation_id for c in self.citations}
        if not citations or len(citations) != len(self.citations):
            raise ValueError("unique source citations required")
        for obj in self.sources + self.alternatives + self.limitations + self.recommended_actions:
            if any(c not in citations for c in obj.citation_ids):
                raise ValueError("dangling packet citation")
        if {a.code for a in self.alternatives} != set(CATALOG) or len(self.alternatives) != len(CATALOG):
            raise ValueError("complete nonfraud explanation catalog required")
        if not self.limitations or not self.unresolved_questions or not self.recommended_actions:
            raise ValueError("uncertainty and next actions required")


@dataclass(frozen=True, kw_only=True)
class ReviewPacketManifest(Schema):
    financial_run: FinancialRun
    selected_claim_ids: tuple[str, ...]
    packets: tuple[ReviewPacket, ...]
    total_available_claims: int
    rule_version: str = PACKET_RULE_VERSION
    generated_at_utc: str | None = field(default=None, metadata={"execution": True})

    def validate(self):
        _timestamp(self.generated_at_utc)
        if self.rule_version != PACKET_RULE_VERSION or self.selected_claim_ids != tuple(sorted(set(self.selected_claim_ids))):
            raise ValueError("unsupported rules/noncanonical claim selection")
        from .review_packet_builder import project_packets
        packets, total = project_packets(self.financial_run, self.selected_claim_ids)
        if self.packets != packets or self.total_available_claims != total:
            raise ValueError("packets must be exact conservative projections of findings")

    @property
    def substantive_sha256(self):
        return digest(self.to_dict(substantive=True))

    @property
    def exit_code(self):
        return 0 if self.packets and not self.financial_run.identity_run.excluded_artifacts and all(p.claim.status is ComparisonStatus.VERIFIED_MATCH for p in self.packets) else 1
