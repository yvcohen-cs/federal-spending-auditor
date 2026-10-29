"""Phase 4C5 strict local study contracts; no source or financial authority."""
from dataclasses import dataclass, field
from enum import Enum
import re

from .evidence import Schema, _hash, _timestamp
from .evidence_io import digest
from .matching_models import _ComputedIdentity
from .review_validation_models import ReviewerTask, DecisionRationale, ReviewDecision

PREPARATION_SHA='364b3ff0166b964b064aae4c1e5ff200bba947127201425cc5ff697c538094ef'


class MeasurementKind(str,Enum):
    HUMAN='OBSERVED_HUMAN'
    SIMULATED='SIMULATED'
    NONE='NOT_MEASURED'
    INVALID='INVALID'


class SessionState(str,Enum):
    NOT_STARTED='NOT_STARTED'
    IN_PROGRESS='IN_PROGRESS'
    COMPLETED='COMPLETED'
    WITHDRAWN='WITHDRAWN'
    INVALIDATED='INVALIDATED'


class ConsentState(str,Enum):
    NOT_REQUESTED='NOT_REQUESTED'
    GRANTED='GRANTED'
    DECLINED='DECLINED'
    WITHDRAWN='WITHDRAWN'


class SessionAction(str,Enum):
    CONSENT='CONSENT'
    START='START'
    PRESENT='PRESENT'
    BEGIN_RESPONSE='BEGIN_RESPONSE'
    RESPOND='RESPOND'
    INVALID_SUBMISSION='INVALID_SUBMISSION'
    SUSPEND='SUSPEND'
    RESUME='RESUME'
    COMPLETE='COMPLETE'
    WITHDRAW='WITHDRAW'
    INVALIDATE='INVALIDATE'


REASONS={
    'narrow_support':'Selected source evidence supports this saved narrow claim.',
    'counterevidence':'Returned counterevidence requires independent resolution.',
    'missing_proof':'Additional primary evidence is required.',
    'unsupported_scope':'The requested interpretation is unsupported.',
    'not_applicable':'The claim is not applicable within the stated evidence scope.',
}
FOLLOW_UP={
    'none':'No additional action selected; missing proof obligations remain unresolved.',
    'native_context':'Obtain authoritative native identity and parent context.',
    'complete_capture':'Obtain the missing preserved pages or historical counterpart.',
    'revision_lineage':'Establish authoritative revision, correction and publication lineage.',
    'independent_review':'Escalate the preserved conflicting evidence for independent review.',
}


@dataclass(frozen=True,kw_only=True)
class TaskBinding(Schema):
    logical_root: str
    source_root: str = field(metadata={'execution':True})
    source_inventory_json: str
    selected_claim_ids: tuple[str,...]
    task: ReviewerTask
    origin: str
    reference_decision: ReviewDecision | None = None
    reference_scope: str = 'NOT_MEASURED_no_reliable_reference_answer'

    def validate(self):
        from .evidence_io import canonical,strict_json,parts
        parts(self.logical_root)
        if not self.source_root.startswith('/') or self.origin not in ('authored_synthetic_control','preserved_public_unverified'):
            raise ValueError('explicit_local_source_binding_required')
        value=strict_json(self.source_inventory_json.encode())
        if not isinstance(value,dict) or canonical(value)!=self.source_inventory_json: raise ValueError('canonical_inventory_required')
        for path,sha in value.items():parts(path);_hash(sha)
        if self.selected_claim_ids!=(self.task.claim_id,):raise ValueError('exact_task_claim_selection_required')
        if self.reference_decision is not None and (self.origin!='authored_synthetic_control' or self.reference_scope!='authored_narrow_property_only_not_award_truth'):
            raise ValueError('no_invented_public_ground_truth')
        if self.reference_decision is not None and not any(d.name=='identity' and d.status.value=='VERIFIED' for d in self.task.dimensions):
            raise ValueError('reference_requires_verified_authored_narrow_property')


@dataclass(frozen=True,kw_only=True)
class PilotTaskSet(Schema):
    entries: tuple[TaskBinding,...]
    selection_version: str = 'pilot-controls-v1'

    @property
    def task_set_digest(self):return digest(self.to_dict(substantive=True))
    @property
    def evidence_inventory_digest(self):
        return digest({e.logical_root:e.source_inventory_json for e in self.entries})

    def validate(self):
        if self.selection_version not in ('pilot-controls-v1','pilot-mixed-v1') or not 1<=len(self.entries)<=12:
            raise ValueError('bounded_frozen_task_selection_required')
        if len({e.logical_root for e in self.entries})!=len(self.entries) or len({e.task.task_id for e in self.entries})!=len(self.entries):
            raise ValueError('duplicate_task_or_logical_root')
        for e in self.entries:
            public=e.logical_root=='preserved_public'
            if e.origin!=('preserved_public_unverified' if public else 'authored_synthetic_control'):
                raise ValueError('task_origin_conflicts_with_frozen_plan')
            expected=ReviewDecision.ACCEPT if e.logical_root=='verified_identity' else None
            if e.reference_decision is not expected:
                raise ValueError('reference_answers_cannot_be_invented_or_changed')
        from .pilot_taskset import expected_order
        if tuple(e.logical_root for e in self.entries)!=expected_order(self.selection_version):
            raise ValueError('altered_task_order_or_selection')


@dataclass(frozen=True,kw_only=True)
class StudyProtocol(_ComputedIdentity):
    _computed_name='protocol_id'
    task_set_digest: str
    evidence_inventory_digest: str
    governance_sha256: str
    measurement_kind: MeasurementKind
    instance_id: str
    timing_enabled: bool
    selection_version: str
    preparation_sha256: str = PREPARATION_SHA
    version: str = 'local-study-protocol-v1'
    financial_authorization: bool = False
    production_screening_authorized: bool = False

    @property
    def protocol_id(self):return 'study-protocol:v1:'+digest(Schema.to_dict(self))

    def validate(self):
        for sha in (self.task_set_digest,self.evidence_inventory_digest,self.governance_sha256):_hash(sha)
        if not re.fullmatch(r'BATCH-[a-f0-9]{16}',self.instance_id):raise ValueError('opaque_batch_id_required')
        if self.measurement_kind is MeasurementKind.HUMAN and self.selection_version!='pilot-mixed-v1':raise ValueError('actual_human_protocol_requires_frozen_mixed_plan')
        if (self.preparation_sha256!=PREPARATION_SHA or self.version!='local-study-protocol-v1'
                or self.measurement_kind not in (MeasurementKind.HUMAN,MeasurementKind.SIMULATED)
                or self.selection_version not in ('pilot-controls-v1','pilot-mixed-v1')
                or self.financial_authorization is not False or self.production_screening_authorized is not False):
            raise ValueError('unsupported_study_protocol_or_authority')


@dataclass(frozen=True,kw_only=True)
class StudyAuthorization(Schema):
    protocol_id: str
    task_set_digest: str
    governance_sha256: str
    reference: str
    owner_authorized: bool
    privacy_storage_ready: bool
    voluntary_recruitment_ready: bool

    def validate(self):
        if not re.fullmatch(r'APP-[a-f0-9]{16}',self.reference) or not self.protocol_id.startswith('study-protocol:v1:'):
            raise ValueError('opaque_external_authorization_reference_required')
        _hash(self.task_set_digest);_hash(self.governance_sha256)
        if not all((self.owner_authorized,self.privacy_storage_ready,self.voluntary_recruitment_ready)):
            raise ValueError('separate_owner_and_governance_authorization_required')


@dataclass(frozen=True,kw_only=True)
class StudySession(_ComputedIdentity):
    _computed_name='session_id'
    protocol: StudyProtocol
    pseudonym: str
    resume_capability_sha256: str = field(metadata={'execution':True})
    authorization: StudyAuthorization | None = None
    state: SessionState = SessionState.NOT_STARTED
    consent: ConsentState = ConsentState.NOT_REQUESTED

    @property
    def session_id(self):
        return 'study-session:v1:'+digest({'protocol':self.protocol.protocol_id,'label':self.pseudonym})

    def validate(self):
        prefix='SIM-' if self.protocol.measurement_kind is MeasurementKind.SIMULATED else 'P-'
        if not re.fullmatch(prefix+r'[a-f0-9]{16}',self.pseudonym) or not re.search('[a-f]',self.pseudonym[len(prefix):]):
            raise ValueError('opaque_pseudonym_only_no_identifying_fields')
        _hash(self.resume_capability_sha256)
        if self.state is not SessionState.NOT_STARTED or self.consent is not ConsentState.NOT_REQUESTED:
            raise ValueError('initial_state_and_consent_cannot_be_fabricated')
        if self.protocol.measurement_kind is MeasurementKind.HUMAN:
            a=self.authorization
            if (a is None or a.protocol_id!=self.protocol.protocol_id or a.task_set_digest!=self.protocol.task_set_digest
                    or a.governance_sha256!=self.protocol.governance_sha256 or self.protocol.selection_version!='pilot-mixed-v1'):
                raise ValueError('human_study_requires_separate_exact_authorization_and_mixed_plan')
        elif self.authorization is not None:raise ValueError('simulations_cannot_claim_actual_authorization')


@dataclass(frozen=True,kw_only=True)
class ConsentReceipt(Schema):
    protocol_id: str
    governance_sha256: str
    kind: MeasurementKind
    state: ConsentState
    voluntary: bool
    purpose_understood: bool
    withdrawal_understood: bool
    timing_acknowledged: bool

    def validate(self):
        _hash(self.governance_sha256)
        if self.kind not in (MeasurementKind.HUMAN,MeasurementKind.SIMULATED) or self.state not in (ConsentState.GRANTED,ConsentState.DECLINED):
            raise ValueError('explicit_consent_receipt_required')
        if self.state is ConsentState.GRANTED and not all((self.voluntary,self.purpose_understood,self.withdrawal_understood)):
            raise ValueError('informed_voluntary_consent_required')


@dataclass(frozen=True,kw_only=True)
class ClockObservation(Schema):
    timestamp_utc: str | None
    kind: MeasurementKind
    monotonic_ns: int | None = None
    epoch: str | None = None

    def validate(self):
        _timestamp(self.timestamp_utc)
        if self.kind in (MeasurementKind.NONE,MeasurementKind.INVALID):
            if self.monotonic_ns is not None or self.epoch is not None or self.timestamp_utc is not None:raise ValueError('missing_invalid_clock_must_not_invent_values')
        elif self.timestamp_utc is None or self.monotonic_ns is None or not 0<=self.monotonic_ns<10**20 or not isinstance(self.epoch,str) or not re.fullmatch('[a-f0-9]{16}',self.epoch):
            raise ValueError('bounded_monotonic_epoch_required')


@dataclass(frozen=True,kw_only=True)
class TaskPresentation(_ComputedIdentity):
    _computed_name='presentation_id'
    session_id: str
    task_id: str
    position: int
    event_sequence: int
    clock: ClockObservation

    @property
    def presentation_id(self):return 'task-presentation:v1:'+digest(Schema.to_dict(self))
    def validate(self):
        if not self.session_id.startswith('study-session:v1:') or not self.task_id.startswith('review-task:v1:') or not 0<=self.position<12 or not 0<=self.event_sequence<256:
            raise ValueError('bounded_exact_task_presentation_required')


def derived_rationale(task,reason_code,uncertainty_codes,citation_ids):
    return DecisionRationale(interpretation=REASONS[reason_code],scope_explanation='Selected scope: '+task.claim+'; evidence quality only; no financial authorization.',
        uncertainty='Explicitly selected uncertainty: '+','.join(uncertainty_codes),citation_ids=citation_ids,
        acknowledged_obligations=task.missing_proof_obligations)


@dataclass(frozen=True,kw_only=True)
class ReviewerResponse(_ComputedIdentity):
    _computed_name='response_id'
    presentation_id: str
    task_id: str
    decision: ReviewDecision
    reason_code: str
    uncertainty_codes: tuple[str,...]
    citation_ids: tuple[str,...]
    proof_acknowledged: bool
    follow_up_code: str
    rationale: DecisionRationale
    clock: ClockObservation
    financial_authorization: bool = False

    @property
    def response_id(self):return 'reviewer-response:v1:'+digest(Schema.to_dict(self))
    def validate(self):
        if (not self.presentation_id.startswith('task-presentation:v1:') or not self.task_id.startswith('review-task:v1:')
                or self.reason_code not in REASONS or self.follow_up_code not in FOLLOW_UP
                or self.proof_acknowledged is not True or self.financial_authorization is not False):
            raise ValueError('closed_structured_rationale_and_no_financial_authority_required')
        if self.uncertainty_codes!=tuple(sorted(set(self.uncertainty_codes))) or not self.uncertainty_codes:
            raise ValueError('explicit_uncertainty_required')
        if self.decision in (ReviewDecision.MORE,ReviewDecision.ESCALATE) and self.follow_up_code=='none':
            raise ValueError('follow_up_required')


@dataclass(frozen=True,kw_only=True)
class SessionEvent(_ComputedIdentity):
    _computed_name='event_id'
    session_id: str
    protocol_id: str
    task_set_digest: str
    sequence: int
    previous_event_id: str | None
    action: SessionAction
    state_after: SessionState
    clock: ClockObservation
    consent: ConsentReceipt | None = None
    presentation: TaskPresentation | None = None
    response: ReviewerResponse | None = None
    invalid_code: str | None = None

    @property
    def event_id(self):return 'session-event:v1:'+digest(Schema.to_dict(self))
    def validate(self):
        _hash(self.task_set_digest)
        if not 0<=self.sequence<256 or self.invalid_code not in (None,'invalid_choice','invalid_rationale','replayed_submission','evidence_integrity','coordinator_invalidated'):
            raise ValueError('bounded_session_event_no_raw_invalid_input')


@dataclass(frozen=True,kw_only=True)
class SessionSummary(Schema):
    session_id: str
    state: SessionState
    consent: ConsentState
    kind: MeasurementKind
    tasks_attempted: int
    tasks_completed: int
    needs_more_evidence: int
    escalations: int
    invalid_submissions: int
    uncertainty_responses: int
    reference_agreements: int
    reference_denominator: int
    measured_responses: int
    not_measured_responses: int
    invalid_timing_responses: int
    presentation_duration_ns: int | None
    decision_duration_ns: int | None
    eligible_for_aggregation: bool
    financial_authorization: bool = False

    def validate(self):
        counts=(self.tasks_attempted,self.tasks_completed,self.needs_more_evidence,self.escalations,self.invalid_submissions,
            self.uncertainty_responses,self.reference_agreements,self.reference_denominator,self.measured_responses,
            self.not_measured_responses,self.invalid_timing_responses)
        if (self.financial_authorization is not False or any(n<0 for n in counts) or not self.tasks_completed<=self.tasks_attempted<=12
                or self.needs_more_evidence+self.escalations>self.tasks_completed or self.uncertainty_responses>self.tasks_completed
                or not self.reference_agreements<=self.reference_denominator<=self.tasks_completed
                or self.measured_responses+self.not_measured_responses+self.invalid_timing_responses!=self.tasks_completed):
            raise ValueError('invalid_summary_or_financial_authority')
        values=(self.presentation_duration_ns,self.decision_duration_ns)
        if self.measured_responses==0 and any(v is not None for v in values) or self.measured_responses>0 and any(v is None or v<0 for v in values):
            raise ValueError('timing_measurements_cannot_be_fabricated')
        eligible=self.state in (SessionState.IN_PROGRESS,SessionState.COMPLETED) and self.consent is ConsentState.GRANTED
        if self.eligible_for_aggregation!=eligible:
            raise ValueError('withdrawn_invalid_or_unstarted_cannot_enter_statistics')
