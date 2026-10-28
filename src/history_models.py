"""Strict history-v1 companion contracts; no source synchronization assertions."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .evidence import Schema, Completeness, _hash, _text, _timestamp
from .evidence_io import canonical, digest, strict_json
from .financial_models import FinancialObservation, signed_date
from .matching_models import _ComputedIdentity, ordered
from .scope_models import ScopeAssessment, ScopeRequest, ScopeRun, ScopeStatus, FIELDS
from .review_packet_models import EvidenceCitation, EvidenceLimitation, RecommendedVerificationAction

RULE = 'history-v1'
CONTROL = 'history-control-v1'


def temporal_parse(raw):
    if raw is None: return None
    if not isinstance(raw, str) or len(raw)>128: return None
    # Do not assign a zone to local source times, or truncate arbitrary times.
    if signed_date(raw) is not None: return signed_date(raw)
    try:
        value = datetime.fromisoformat(raw.replace('Z','+00:00'))
    except ValueError: return None
    if len(raw)<19 or raw[10] not in ('T',' '): return None
    return value.isoformat()


@dataclass(frozen=True, kw_only=True)
class TemporalField(Schema):
    path: str
    meaning: str
    original_json: str
    parsed: str | None

    def validate(self):
        _text(self.path,'temporal field')
        if len(self.path)>256 or len(self.original_json)>4096:
            raise ValueError('bounded temporal evidence required')
        if self.meaning not in ('signed','effective','updated','published','created','approved','http_last_modified','unknown'):
            raise ValueError('unsupported temporal meaning')
        raw = strict_json(self.original_json.encode())
        if canonical(raw)!=self.original_json or self.parsed!=temporal_parse(raw):
            raise ValueError('temporal interpretation contradicts original')


def temporal(path, meaning, raw):
    return TemporalField(path=path,meaning=meaning,original_json=canonical(raw),parsed=temporal_parse(raw))


@dataclass(frozen=True, kw_only=True)
class ContractHistoryScope(Schema):
    requested: ScopeRequest
    rule_version: str = RULE
    claim_scope: str = 'observed_actions_and_revision_conditioned_values_only'

    def validate(self):
        if self.rule_version!=RULE or self.claim_scope!='observed_actions_and_revision_conditioned_values_only':
            raise ValueError('unsupported history scope')
        if self.requested.modification is not None or self.requested.transaction is not None:
            raise ValueError('history request must retain all observed actions')
        if self.requested.namespace!='usa-fpds-v1':
            raise ValueError('SAM temporal and financial mappings not supported')


@dataclass(frozen=True, kw_only=True)
class ModificationIdentity(Schema):
    native: str | None
    transaction: str | None
    original_modification_json: str
    original_transaction_json: str

    def validate(self):
        from .identity_matching import component
        for value,raw in ((self.native,self.original_modification_json),(self.transaction,self.original_transaction_json)):
            decoded=strict_json(raw.encode())
            if canonical(decoded)!=raw or value is not None and component(decoded).value!=value:
                raise ValueError('modification/transaction identity conflicts with native evidence')


@dataclass(frozen=True, kw_only=True)
class FinancialObservationContext(Schema):
    observation: FinancialObservation
    accounting_interpretation: str = 'C5_field_semantics_no_aggregation_or_payment_inference'

    def validate(self):
        if self.accounting_interpretation!='C5_field_semantics_no_aggregation_or_payment_inference':
            raise ValueError('unsupported accounting interpretation')


@dataclass(frozen=True, kw_only=True)
class SourceRevisionEvidence(Schema):
    update_markers: tuple[TemporalField,...] = ()
    synthetic_control_revision: str | None = None
    basis: str = 'source_update_markers_not_revision_certificate'

    def validate(self):
        if self.update_markers!=ordered(self.update_markers) or any(t.meaning!='updated' for t in self.update_markers):
            raise ValueError('canonical source update markers required')
        if len({t.path for t in self.update_markers})!=len(self.update_markers):
            raise ValueError('contradictory update fields')
        if self.basis!='source_update_markers_not_revision_certificate':
            raise ValueError('unsupported revision authority')
        if self.synthetic_control_revision is not None:
            _text(self.synthetic_control_revision,'fictional control revision')
            if len(self.synthetic_control_revision)>128: raise ValueError('bounded control revision required')


@dataclass(frozen=True, kw_only=True)
class FreshnessAssessment(Schema):
    retrieved_at_utc: str | None
    temporal_fields: tuple[TemporalField,...] = ()
    content_freshness: str = 'unknown'
    reason: str = 'no_authoritative_record_freshness_criterion'

    def validate(self):
        _timestamp(self.retrieved_at_utc)
        if self.temporal_fields!=ordered(self.temporal_fields) or len({t.path for t in self.temporal_fields})!=len(self.temporal_fields):
            raise ValueError('canonical distinct temporal fields required')
        if self.content_freshness!='unknown' or self.reason!='no_authoritative_record_freshness_criterion':
            raise ValueError('retrieval/update dates cannot certify freshness')


@dataclass(frozen=True, kw_only=True)
class ContractActionObservation(_ComputedIdentity):
    _computed_name = 'history_observation_id'
    input_manifest_sha256: str
    scope_assessment: ScopeAssessment
    modification: ModificationIdentity
    freshness: FreshnessAssessment
    revision: SourceRevisionEvidence
    money: tuple[FinancialObservationContext,...]
    retrieval_sequence: int
    source_page: int
    issues: tuple[str,...] = ()

    @property
    def history_observation_id(self):
        return 'history-observation:v1:'+digest({'input':self.input_manifest_sha256,'assessment':self.scope_assessment.assessment_id})

    @property
    def eligible(self):
        return self.scope_assessment.status is ScopeStatus.IN_SCOPE

    @property
    def action_key(self):
        if not self.eligible: return None
        values=tuple(getattr(self.scope_assessment.observed,f).value for f in FIELDS)
        return values if all(v is not None for v in values) else None

    def validate(self):
        _hash(self.input_manifest_sha256)
        a=self.scope_assessment
        if self.modification!=ModificationIdentity(native=a.observed.modification.value,transaction=a.observed.transaction.value,
                original_modification_json=a.observed.modification.original_json,original_transaction_json=a.observed.transaction.original_json):
            raise ValueError('action components contradict source scope evidence')
        if self.freshness.retrieved_at_utc!=a.evidence.artifact.retrieved_at_utc:
            raise ValueError('retrieval provenance conflict')
        if self.revision.update_markers!=ordered(t for t in self.freshness.temporal_fields if t.meaning=='updated'):
            raise ValueError('revision markers contradict temporal fields')
        if self.revision.synthetic_control_revision is not None and 'synthetic_fixture_only' not in a.evidence.artifact.limitations:
            raise ValueError('fictional revision control cannot authorize live evidence')
        if self.money!=ordered(self.money) or len({m.observation.original_field for m in self.money})!=len(self.money):
            raise ValueError('canonical unique monetary fields required')
        if any(a.record is None or m.observation.record_id!=a.record.record_id or m.observation.evidence!=a.evidence for m in self.money):
            raise ValueError('historical money/provenance conflict')
        signed=[t for t in self.freshness.temporal_fields if t.meaning=='signed']
        if self.money and any(m.observation.action_date_raw!=(strict_json(signed[0].original_json.encode()) if signed else None) for m in self.money):
            raise ValueError('monetary signed date contradicts timeline evidence')
        if not 0<=self.retrieval_sequence<1000000 or not 1<=self.source_page<=10000 or self.issues!=tuple(sorted(set(self.issues))):
            raise ValueError('bounded observation order/issues required')


@dataclass(frozen=True, kw_only=True)
class HistoryCoverageAssessment(Schema):
    source: str
    input_manifest_sha256: str
    pagination: Completeness
    observed_action_count: int
    issues: tuple[str,...] = ()
    historical_completeness: Completeness = Completeness.UNKNOWN
    source_wide_completeness: Completeness = Completeness.UNKNOWN
    authoritative_sequence_rule: str | None = None

    def validate(self):
        _hash(self.input_manifest_sha256)
        if self.source not in ('usaspending','fpds') or not 0<=self.observed_action_count<=1000:
            raise ValueError('unsupported history coverage source/count')
        if self.pagination is Completeness.NOT_APPLICABLE or self.historical_completeness is not Completeness.UNKNOWN or self.source_wide_completeness is not Completeness.UNKNOWN or self.authoritative_sequence_rule is not None:
            raise ValueError('no authoritative full-history or gap rule supported')


class Alignment(str,Enum):
    SAME = 'same_verified_action_compatible_revision'
    DIFFERENT_REVISION = 'same_action_different_declared_reporting_states'
    UNKNOWN = 'same_action_revision_relationship_unknown'
    DIFFERENT_ACTION = 'different_actions'
    INSUFFICIENT = 'insufficient_identity_or_temporal_evidence'
    UNSUPPORTED = 'unsupported_source_semantics'


@dataclass(frozen=True, kw_only=True)
class RevisionAlignmentDecision(Schema):
    left: ContractActionObservation
    right: ContractActionObservation
    status: Alignment
    reason: str
    rule_version: str = RULE

    def validate(self):
        from .history_rules import alignment
        if self.rule_version!=RULE or (self.status,self.reason)!=alignment(self.left,self.right):
            raise ValueError('revision decision contradicts identity/temporal evidence')


class HistoricalStatus(str,Enum):
    AGREEMENT = 'exact_observed_agreement'
    UNEQUAL = 'unequal_comparable_observations'
    REVISION_DIFFERENCE = 'different_known_reporting_states'
    REVISION_UNKNOWN = 'revision_relationship_unknown'
    INCOMPATIBLE = 'incompatible_financial_scope'
    HISTORY_INSUFFICIENT = 'insufficient_history'
    UNSUPPORTED = 'unsupported_semantics'
    SCOPE_UNCERTAIN = 'scope_uncertainty'


@dataclass(frozen=True, kw_only=True)
class HistoricalFinancialComparison(_ComputedIdentity):
    _computed_name = 'claim_id'
    left: ContractActionObservation
    right: ContractActionObservation | None
    left_field: str
    right_field: str
    alignment: RevisionAlignmentDecision | None
    status: HistoricalStatus
    reasons: tuple[str,...]
    difference_left_minus_right: str | None
    context_conflict: bool = False
    rule_version: str = RULE

    @property
    def claim_id(self):
        return 'history-claim:v1:'+digest({'left':self.left.history_observation_id,'right':self.right.history_observation_id if self.right else None,
            'fields':[self.left_field,self.right_field],'rule':self.rule_version})

    def validate(self):
        from .history_rules import comparison_values
        if self.rule_version!=RULE or (self.status,self.reasons,self.difference_left_minus_right)!=comparison_values(self.left,self.right,self.left_field,self.right_field,context_conflict=self.context_conflict):
            raise ValueError('historical comparison contradicts authorized prerequisites')
        if self.right is None:
            if self.alignment is not None: raise ValueError('missing counterpart has no revision alignment')
        elif self.alignment is None or (self.alignment.left,self.alignment.right)!=(self.left,self.right):
            raise ValueError('alignment must preserve both comparison observations')


@dataclass(frozen=True, kw_only=True)
class HistoryVerificationRun(Schema):
    scope: ContractHistoryScope
    inputs: tuple[ScopeRun,...]
    observations: tuple[ContractActionObservation,...]
    coverage: tuple[HistoryCoverageAssessment,...]
    comparisons: tuple[HistoricalFinancialComparison,...]
    executed_at_utc: str | None = field(default=None,metadata={'execution':True})
    rule_version: str = RULE

    def validate(self):
        from .history_rules import compare_observations
        _timestamp(self.executed_at_utc)
        if self.rule_version!=RULE or not 1<=len(self.inputs)<=8 or len(self.observations)>1000:
            raise ValueError('unsupported history limits/rules')
        if any(s.requested!=self.scope.requested for s in self.inputs) or self.inputs!=ordered(self.inputs) or len({s.input_manifest_sha256 for s in self.inputs})!=len(self.inputs):
            raise ValueError('canonical unique history inputs/context required')
        expected={(s.input_manifest_sha256,a.assessment_id):a for s in self.inputs for a in s.assessments}
        actual={(o.input_manifest_sha256,o.scope_assessment.assessment_id):o.scope_assessment for o in self.observations}
        if actual!=expected or len(actual)!=len(self.observations) or self.observations!=ordered(self.observations):
            raise ValueError('every source occurrence must remain preserved exactly once')
        if self.coverage!=ordered(self.coverage) or len({(c.input_manifest_sha256,c.source) for c in self.coverage})!=len(self.coverage):
            raise ValueError('canonical coverage required')
        for c in self.coverage:
            if c.input_manifest_sha256 not in {s.input_manifest_sha256 for s in self.inputs} or c.observed_action_count!=len({o.action_key for o in self.observations if o.input_manifest_sha256==c.input_manifest_sha256 and o.scope_assessment.evidence.reference.source==c.source and o.action_key is not None}):
                raise ValueError('history coverage action count conflict')
        if self.comparisons!=compare_observations(self.observations):
            raise ValueError('historical results contradict deterministic rules')

    @property
    def substantive_sha256(self):
        return digest(self.to_dict(substantive=True))
