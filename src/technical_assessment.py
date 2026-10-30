"""C7 engineering evidence, not external approval or human study authorization."""
from dataclasses import dataclass
from pathlib import Path
from enum import Enum
import hashlib

from .evidence import Schema
from .evidence_io import EvidenceError, digest, strict_json
from .coordinator_governance import CoordinatorChecklist, ApprovalState, ApprovalOrigin, SCOPES, assess

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_SHA = '3e54d41cf582cfb7506d747618950f9a60e14147f7a6e0ce8d087f529ce57c30'


class FindingKind(str, Enum):
    DEFECT = 'CONFIRMED_DEFECT'
    LIMITATION = 'DESIGN_LIMITATION'
    ASSUMPTION = 'UNVERIFIED_ASSUMPTION'
    CONTROL = 'VERIFIED_CONTROL'
    NOT_EVALUATED = 'NOT_EVALUATED'


@dataclass(frozen=True, kw_only=True)
class ApprovalDossier(Schema):
    """Immutable declaration set. C6 v1 snapshots remain unchanged and visible.

    No implicit replacement, winner or supersession rule is supplied. A new
    external resolution protocol is required before actual participant use.
    """
    declarations: tuple[CoordinatorChecklist, ...]

    def validate(self):
        if not 1 <= len(self.declarations) <= 16:
            raise ValueError('bounded_approval_declarations_required')
        ids=[digest(c.to_dict()) for c in self.declarations]
        if len(set(ids))!=len(ids):raise ValueError('duplicate_approval_snapshot')
        first=self.declarations[0]
        for c in self.declarations:
            if (c.protocol_id,c.task_set_digest,c.governance_sha256,c.documents_sha256)!=(first.protocol_id,
                    first.task_set_digest,first.governance_sha256,first.documents_sha256):
                raise ValueError('approval_scope_expansion_or_replay')


def assess_dossier(dossier, study_protocol, as_of):
    assessed=[assess(c,study_protocol,as_of) for c in dossier.declarations]
    reference_scopes={}
    for c in dossier.declarations:
        for r in c.approvals:
            if r.reference is not None:reference_scopes.setdefault(r.reference,set()).add(r.scope)
    rows=[]
    for index,scope in enumerate(SCOPES):
        records=[c.approvals[index] for c in dossier.declarations]
        states={r.state for r in records if r.state is not ApprovalState.UNKNOWN}
        ref_bindings={}
        for r in records:
            if r.reference is not None:ref_bindings.setdefault(r.reference,set()).add(digest(r.to_dict()))
        conflict=(len(states)>1 or any(len(v)>1 for v in ref_bindings.values())
            or any(len(reference_scopes[r.reference])>1 for r in records if r.reference is not None))
        # Every declaration is retained. Unknown or ineffective declarations do
        # not disappear behind a favorable snapshot. No most-recent winner.
        complete=not conflict and all(a['scopes'][index]['effective_external_attestation'] for a in assessed)
        rows.append({'scope':scope,'status':'CONFLICTING_DECLARATIONS' if conflict else 'ATTESTATIONS_COMPLETE' if complete else 'BLOCKED',
            'declaration_count':len(records),'states':[r.state.value for r in records],
            'origins':[r.origin.value for r in records]})
    return {'schema_type':'ApprovalDossierAssessment','schema_version':1,
        'scope_results':rows,'approval_completeness':'ATTESTATIONS_COMPLETE' if all(r['status']=='ATTESTATIONS_COMPLETE' for r in rows) else 'BLOCKED',
        'declaration_digests':[digest(c.to_dict()) for c in dossier.declarations],
        'independent_approval_authenticity':'UNKNOWN','actual_enrollment_authorized':False,
        'conflict_resolution':'NO_AUTOMATIC_WINNER_EXTERNAL_RESOLUTION_REQUIRED','financial_authorization':False}


def protocol():
    value=strict_json((ROOT/'docs'/'technical-assessment-protocol-v1.json').read_bytes())
    if digest(value)!=PROTOCOL_SHA:raise EvidenceError('technical_assessment_protocol_changed')
    for name,sha in value['frozen_documents'].items():
        if hashlib.sha256((ROOT/'docs'/name).read_bytes()).hexdigest()!=sha:
            raise EvidenceError('frozen_assessment_document_changed')
    return value


def documents():
    result={}
    for name,schema in (('technical-findings-v1.json','TechnicalFindingsRegister'),('pre-pilot-checklist-v1.json','PrePilotChecklist')):
        value=strict_json((ROOT/'docs'/name).read_bytes())
        if value.get('schema_type')!=schema or type(value.get('schema_version')) is not int or value['schema_version']!=1:
            raise EvidenceError('unsupported_assessment_document')
        result[name]=value
    findings=result['technical-findings-v1.json']['findings']
    ids=[f['finding_id'] for f in findings]
    if len(ids)!=len(set(ids)) or ids!=sorted(ids):raise EvidenceError('duplicate_or_reordered_findings')
    for f in findings:
        FindingKind(f['category'])
        if f['severity'] not in ('HIGH','MEDIUM','LOW','INFO'):raise EvidenceError('unsupported_severity')
        for key in ('affected','claim','code_evidence','practical_impact','assumptions','reproduction','remediation','verification_status','residual_limitations','tests'):
            if not f.get(key):raise EvidenceError('incomplete_finding')
    for row in result['pre-pilot-checklist-v1.json']['requirements']:
        if set(row)!={'id','REQUIREMENT','CURRENT_EVIDENCE','EVIDENCE_GAP','RESPONSIBLE_ROLE','VERIFICATION_METHOD','STATUS'}:
            raise EvidenceError('incomplete_pre_pilot_requirement')
        if row['STATUS'] not in ('SATISFIED_BY_SOFTWARE','REQUIRES_EXTERNAL_VERIFICATION','BLOCKED','NOT_EVALUATED'):
            raise EvidenceError('unsupported_requirement_status')
    return result


def code_digest():
    p=protocol()
    names=['src/'+n for n in p['reviewed_modules']]+['src/technical_assessment.py','src/technical_assessment_reporting.py',
        'tests/test_technical_assessment.py']
    names+=['docs/technical-findings-v1.json','docs/pre-pilot-checklist-v1.json','docs/real-data-deletion-design-v1.md','docs/technical-assessment.md']
    return digest({name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(names)})
