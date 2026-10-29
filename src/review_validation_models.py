"""Opt-in v1 review tasks and structured assertions; no source authority changes."""
from dataclasses import dataclass
from enum import Enum

from .evidence import Schema, ComparisonStatus, _hash, _text
from .evidence_io import canonical, digest, strict_json
from .matching_models import _ComputedIdentity, ordered
from .review_packet_models import EvidenceCitation, ReviewPacketManifest, RecommendedVerificationAction
from .review_events import ReviewWorkflowEvent
from .history_models import HistoryVerificationRun
from .parent_scope import ParentScopeRun

RULE = 'review-task-v1'
WORKFLOW_SHA = 'cae0e8df3c73ac52f966c6eb233d485fd928c6c5884a0759377b2ff2f9b8549f'


def workflow_spec():
    from pathlib import Path
    value=strict_json((Path(__file__).resolve().parents[1]/'docs'/'review-workflow-v1.json').read_bytes())
    if digest(value)!=WORKFLOW_SHA:
        raise ValueError('review_workflow_specification_changed')
    return value


class EvidenceStatus(str, Enum):
    VERIFIED = 'VERIFIED'
    CONFLICTING = 'CONFLICTING'
    INSUFFICIENT = 'INSUFFICIENT'
    UNSUPPORTED = 'UNSUPPORTED'
    NOT_EVALUATED = 'NOT_EVALUATED'


class ReviewDecision(str, Enum):
    ACCEPT = 'ACCEPT_EVIDENCE'
    REJECT = 'REJECT_EVIDENCE'
    MORE = 'NEEDS_MORE_EVIDENCE'
    NA = 'NOT_APPLICABLE'
    ESCALATE = 'ESCALATE_FOR_REVIEW'


class ReviewKind(str, Enum):
    SIMULATED = 'SIMULATED_REVIEW'
    HUMAN = 'ACTUAL_HUMAN_REVIEW'


@dataclass(frozen=True, kw_only=True)
class ReviewDimension(Schema):
    name: str
    status: EvidenceStatus
    rationale: str
    citation_ids: tuple[str, ...]

    def validate(self):
        if self.name not in ('claim', 'identity', 'parent', 'instrument', 'pagination', 'history', 'revision',
                'monetary_observations', 'financial_authorization', 'traceability'):
            raise ValueError('unsupported_review_dimension')
        _text(self.rationale, 'dimension rationale')
        if self.status is EvidenceStatus.VERIFIED and not self.citation_ids:
            raise ValueError('verified_dimension_requires_citations')


@dataclass(frozen=True, kw_only=True)
class ReviewObservedField(Schema):
    citation_id: str
    path: str
    original_json: str
    basis: str

    def validate(self):
        _text(self.path, 'field path')
        if canonical(strict_json(self.original_json.encode())) != self.original_json:
            raise ValueError('canonical_original_value_required')
        if self.basis not in ('source_native_value', 'C4_component_interpretation', 'derived_source_context'):
            raise ValueError('unsupported_observation_basis')


@dataclass(frozen=True, kw_only=True)
class ReviewerTask(_ComputedIdentity):
    _computed_name = 'task_id'
    packet_id: str
    claim_id: str
    source_snapshot_sha256: str
    claim: str
    rule_versions: tuple[str, ...]
    citations: tuple[EvidenceCitation, ...]
    packet_citation_ids: tuple[str, ...]
    context_citation_ids: tuple[str, ...]
    observed_fields: tuple[ReviewObservedField, ...]
    dimensions: tuple[ReviewDimension, ...]
    limitations: tuple[str, ...]
    missing_proof_obligations: tuple[str, ...]
    permitted_decisions: tuple[ReviewDecision, ...] = tuple(ReviewDecision)
    rule_version: str = RULE
    review_can_authorize_finances: bool = False
    initial_reviewer_attribution: str | None = None
    initial_review_timestamp: str | None = None
    initial_decision_rationale: str | None = None

    @property
    def task_id(self):
        return 'review-task:v1:'+digest({'packet':self.packet_id,'snapshot':self.source_snapshot_sha256,'rule':self.rule_version})

    def validate(self):
        _hash(self.source_snapshot_sha256)
        if not self.packet_id.startswith('review-packet:v1:') or self.rule_version!=RULE:
            raise ValueError('versioned_packet_task_required')
        _hash(self.packet_id.removeprefix('review-packet:v1:'))
        if (self.review_can_authorize_finances is not False or self.permitted_decisions!=tuple(ReviewDecision)
                or any(v is not None for v in (self.initial_reviewer_attribution,self.initial_review_timestamp,self.initial_decision_rationale))):
            raise ValueError('automated_task_cannot_invent_review_or_authorize_finances')
        ids={c.citation_id for c in self.citations}
        if not ids or len(ids)!=len(self.citations) or not self.observed_fields or not self.limitations:
            raise ValueError('complete_cited_task_required')
        if (set(self.packet_citation_ids)&set(self.context_citation_ids) or set(self.packet_citation_ids)|set(self.context_citation_ids)!=ids
                or not self.packet_citation_ids):
            raise ValueError('packet_and_context_citation_roles_required')
        if self.dimensions!=ordered(self.dimensions) or len({d.name for d in self.dimensions})!=10:
            raise ValueError('separate_complete_review_dimensions_required')
        if any(c not in ids for d in self.dimensions for c in d.citation_ids) or any(f.citation_id not in ids for f in self.observed_fields):
            raise ValueError('dangling_review_task_reference')
        if self.missing_proof_obligations!=tuple(sorted(d.name for d in self.dimensions if d.status not in (EvidenceStatus.VERIFIED,EvidenceStatus.NOT_EVALUATED))):
            raise ValueError('missing_proof_obligations_cannot_be_hidden')


@dataclass(frozen=True, kw_only=True)
class ReviewerTaskManifest(Schema):
    source_inventory_json: str
    packets: ReviewPacketManifest
    parent: ParentScopeRun
    history: HistoryVerificationRun
    tasks: tuple[ReviewerTask, ...]
    rule_version: str = RULE

    @property
    def substantive_sha256(self): return digest(self.to_dict(substantive=True))

    def validate(self):
        inventory=strict_json(self.source_inventory_json.encode())
        if not isinstance(inventory,dict) or canonical(inventory)!=self.source_inventory_json or self.rule_version!=RULE:
            raise ValueError('canonical_review_source_inventory_required')
        for sha in inventory.values(): _hash(sha)
        if not 1<=len(self.tasks)<=100:
            raise ValueError('one_to_100_review_tasks_required')
        if (len(self.history.inputs)!=1 or self.history.scope.requested!=self.parent.requested
                or strict_json(self.parent.input_inventories_json.encode())!=[inventory]
                or self.history.inputs[0].input_manifest_sha256!=self.packets.financial_run.identity_run.input_manifest_sha256):
            raise ValueError('review_source_contexts_must_agree')
        from .review_validation_tasks import project_tasks
        if self.tasks!=project_tasks(self.packets,self.parent,self.history,self.source_inventory_json):
            raise ValueError('review_tasks_must_preserve_source_projections')


@dataclass(frozen=True, kw_only=True)
class DecisionRationale(Schema):
    interpretation: str
    scope_explanation: str
    uncertainty: str
    citation_ids: tuple[str, ...]
    acknowledged_obligations: tuple[str, ...]

    def validate(self):
        for text in (self.interpretation,self.scope_explanation,self.uncertainty):
            _text(text,'structured_decision_rationale')
            if len(text)>2048: raise ValueError('bounded_decision_rationale_required')
        if not self.citation_ids or self.citation_ids!=tuple(sorted(set(self.citation_ids))):
            raise ValueError('explicit_cited_rationale_required')
        if self.acknowledged_obligations!=tuple(sorted(set(self.acknowledged_obligations))):
            raise ValueError('canonical_obligation_acknowledgment_required')


@dataclass(frozen=True, kw_only=True)
class ReviewerDecisionEvent(_ComputedIdentity):
    _computed_name = 'decision_event_id'
    task_manifest_sha256: str
    task_id: str
    previous_decision_event_id: str | None
    decision: ReviewDecision
    rationale: DecisionRationale
    kind: ReviewKind
    attribution_label: str
    workflow_event: ReviewWorkflowEvent
    financial_authorization: bool = False
    follow_up: tuple[RecommendedVerificationAction, ...] = ()

    @property
    def decision_event_id(self): return 'review-decision:v1:'+digest(Schema.to_dict(self))

    def validate(self):
        _hash(self.task_manifest_sha256)
        for value,prefix in ((self.task_id,'review-task:v1:'),(self.previous_decision_event_id,'review-decision:v1:')):
            if value is not None:
                if not value.startswith(prefix): raise ValueError('constructed_review_reference_required')
                _hash(value.removeprefix(prefix))
        _text(self.attribution_label,'reviewer_provided_label')
        if len(self.attribution_label)>128 or self.attribution_label!=self.workflow_event.reviewer or self.financial_authorization is not False:
            raise ValueError('unverified_attribution_and_no_financial_authority_required')
        from .sam_validation_capture import secret_free
        if not secret_free({'label':self.attribution_label,'rationale':self.rationale.to_dict(),'follow_up':[a.to_dict() for a in self.follow_up]}):
            raise ValueError('credential_like_review_text_not_preserved')
        if len(self.follow_up)>8:
            raise ValueError('bounded_review_follow_up_required')
        if (self.kind is ReviewKind.SIMULATED)!=(self.attribution_label.startswith('SIMULATED:')):
            raise ValueError('simulations_cannot_be_labeled_as_actual_people')


@dataclass(frozen=True, kw_only=True)
class ReviewerDecisionInput(Schema):
    task_id: str
    decision: ReviewDecision
    rationale: DecisionRationale
    kind: ReviewKind
    attribution_label: str
    timestamp_utc: str
    follow_up: tuple[RecommendedVerificationAction, ...] = ()

    def validate(self):
        from .evidence import _timestamp
        _timestamp(self.timestamp_utc)
        if not self.task_id.startswith('review-task:v1:'):
            raise ValueError('explicit_task_reference_required')
