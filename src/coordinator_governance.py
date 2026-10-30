"""Prospective scope-bound approval checks, not approval or identity verification."""
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
import hashlib
import re

from .evidence import Schema, _hash
from .evidence_io import EvidenceError, digest, strict_json
from .pilot_taskset import preparation, governance_sha

DOCS = Path(__file__).resolve().parents[1] / 'docs'
PROTOCOL_SHA = 'c8e54d22a0b459cd0b2a6a9d586d0d527c7ebf5c1749b383c4e95fb940b8683f'
CHECKLIST_SHA = 'bed7b2fb4fea0402a87ef679f79519526ade73bcb6b5e184c5d6e37714de91f8'
SCOPES = ('consent_documents', 'study_authorization', 'storage', 'retention',
          'deletion_responsibility', 'participant_eligibility', 'privacy_disclosure')


class ApprovalState(str, Enum):
    UNKNOWN = 'UNKNOWN'
    APPROVED = 'APPROVED'
    REJECTED = 'REJECTED'


class ApprovalOrigin(str, Enum):
    PROSPECTIVE = 'EXTERNAL_ADMINISTRATIVE_ATTESTATION'
    SIMULATED = 'SIMULATED'
    UNKNOWN = 'UNKNOWN'


def day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('explicit_ISO_date_required')
    return date.fromisoformat(value)


def protocol():
    value = strict_json((DOCS / 'coordinator-rehearsal-protocol-v1.json').read_bytes())
    if digest(value) != PROTOCOL_SHA:
        raise EvidenceError('coordinator_preregistration_changed')
    preparation(); governance_sha()
    if hashlib.sha256((DOCS / 'coordinator-checklist-v1.json').read_bytes()).hexdigest() != CHECKLIST_SHA:
        raise EvidenceError('coordinator_checklist_specification_changed')
    for name, sha in value['frozen_protocols'].items():
        if hashlib.sha256((DOCS / name).read_bytes()).hexdigest() != sha:
            raise EvidenceError('frozen_protocol_changed')
    return value


def document_digest():
    return digest({'frozen': protocol()['frozen_protocols'], 'coordinator_checklist': CHECKLIST_SHA})


@dataclass(frozen=True, kw_only=True)
class ApprovalRecord(Schema):
    scope: str
    state: ApprovalState = ApprovalState.UNKNOWN
    origin: ApprovalOrigin = ApprovalOrigin.UNKNOWN
    reference: str | None = None
    approved_on: str | None = None
    expires_on: str | None = None

    def validate(self):
        if self.scope not in SCOPES:
            raise ValueError('unsupported_approval_scope')
        if self.state is ApprovalState.UNKNOWN:
            if self.origin is not ApprovalOrigin.UNKNOWN or any(x is not None for x in (self.reference, self.approved_on, self.expires_on)):
                raise ValueError('unknown_approval_cannot_fabricate_metadata')
        else:
            if self.origin is ApprovalOrigin.UNKNOWN or not re.fullmatch(r'APPROVAL-[a-f0-9]{16}', self.reference or ''):
                raise ValueError('separate_opaque_approval_reference_required')
            if day(self.expires_on) < day(self.approved_on):
                raise ValueError('approval_dates_reordered')


@dataclass(frozen=True, kw_only=True)
class CoordinatorChecklist(Schema):
    protocol_id: str
    task_set_digest: str
    governance_sha256: str
    documents_sha256: str
    approvals: tuple[ApprovalRecord, ...]

    def validate(self):
        if not re.fullmatch(r'study-protocol:v1:[a-f0-9]{64}', self.protocol_id):
            raise ValueError('exact_protocol_required')
        for value in (self.task_set_digest, self.governance_sha256, self.documents_sha256):
            _hash(value)
        if tuple(a.scope for a in self.approvals) != SCOPES:
            raise ValueError('all_separate_approval_scopes_in_fixed_order_required')
        refs = [a.reference for a in self.approvals if a.reference is not None]
        if len(refs) != len(set(refs)):
            raise ValueError('independent_scope_references_required')


def pending_checklist(study_protocol):
    return CoordinatorChecklist(protocol_id=study_protocol.protocol_id,
        task_set_digest=study_protocol.task_set_digest, governance_sha256=study_protocol.governance_sha256,
        documents_sha256=document_digest(), approvals=tuple(ApprovalRecord(scope=s) for s in SCOPES))


def assess(checklist, study_protocol, as_of):
    today = day(as_of)
    if (checklist.protocol_id != study_protocol.protocol_id or checklist.task_set_digest != study_protocol.task_set_digest
            or checklist.governance_sha256 != study_protocol.governance_sha256 or checklist.documents_sha256 != document_digest()):
        raise EvidenceError('approval_scope_or_documents_conflict')
    rows = []
    for a in checklist.approvals:
        effective = (a.state is ApprovalState.APPROVED and a.origin is ApprovalOrigin.PROSPECTIVE
            and day(a.approved_on) <= today <= day(a.expires_on))
        rows.append({'scope': a.scope, 'declared_state': a.state.value, 'origin': a.origin.value,
                     'effective_external_attestation': effective})
    complete = all(r['effective_external_attestation'] for r in rows)
    return {'schema_type': 'CoordinatorGovernanceAssessment', 'schema_version': 1,
        'approval_completeness': 'ATTESTATIONS_COMPLETE' if complete else 'BLOCKED', 'scopes': rows,
        'missing_or_ineffective_scopes': [r['scope'] for r in rows if not r['effective_external_attestation']],
        'independent_approval_authenticity': 'UNKNOWN_local_references_are_not_independent_verification',
        'actual_enrollment_supported': False, 'actual_enrollment_authorized': False,
        'participant_eligibility_observed': 'NOT_EVALUATED_no_participants',
        'financial_authorization': False, 'production_screening_authorized': False}


def require_approvals(checklist, study_protocol, as_of):
    value = assess(checklist, study_protocol, as_of)
    if value['approval_completeness'] != 'ATTESTATIONS_COMPLETE':
        raise EvidenceError('independent_governance_approvals_missing_or_ineffective')
    # C6 never bridges this assessment into C5 enrollment or financial authority.
    return value
