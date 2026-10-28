"""Versioned narrow record-scope assertions, independent of review/fraud labels."""
from dataclasses import dataclass
from enum import Enum

from .evidence import Schema, _hash, _text
from .evidence_io import digest,canonical,strict_json
from .identity_matching import component, agency_component
from .matching_models import IdentityComponent, MatchEvidenceReference, SourceRecordIdentity, _ComputedIdentity

FIELDS=("piid","agency","parent_piid","parent_agency","modification","transaction")
RULE="record-scope-v1"
PARSERS={"usaspending":"usa-cont-tx-v1","fpds":"fpds-award-v1","samgov":"sam-contract-id-v1"}


class ScopeStatus(str,Enum):
    IN_SCOPE="verified_in_scope"
    OUT_OF_SCOPE="verified_out_of_scope"
    AMBIGUOUS="ambiguous_scope"
    INSUFFICIENT="insufficient_identity"
    UNSUPPORTED="unsupported_schema"


@dataclass(frozen=True,kw_only=True)
class ScopeRequest(Schema):
    piid:str
    agency:str
    parent_piid:str|None=None
    parent_agency:str|None=None
    modification:str|None=None
    transaction:str|None=None
    namespace:str="usa-fpds-v1"

    def validate(self):
        if self.namespace not in ("usa-fpds-v1","samgov-v1"):
            raise ValueError("unsupported requested identity namespace")
        for f in FIELDS:
            v=getattr(self,f)
            if v is not None:
                _text(v,f)
                if len(v)>256: raise ValueError("bounded native identifier required")
        if agency_component(component(self.agency)).value is None:
            raise ValueError("explicit native four-character identity agency required")
        if (self.parent_piid is None)!=(self.parent_agency is None):
            raise ValueError("paired parent context required")
        if self.parent_agency is not None and agency_component(component(self.parent_agency)).value is None:
            raise ValueError("unsupported parent agency")


@dataclass(frozen=True,kw_only=True)
class ObservedIdentity(Schema):
    piid:IdentityComponent
    agency:IdentityComponent
    parent_piid:IdentityComponent
    parent_agency:IdentityComponent
    modification:IdentityComponent
    transaction:IdentityComponent

    @classmethod
    def from_record(cls,record):
        return cls(**{f:getattr(record,f) for f in FIELDS})

    @classmethod
    def missing(cls):
        return cls(**{f:component(basis="unavailable") for f in FIELDS})


@dataclass(frozen=True,kw_only=True)
class ScopeField(Schema):
    name:str
    requested:str|None
    observed:IdentityComponent
    result:str


def conclusion(request,observed,*,supported=True,conflicting=False,source="fpds"):
    fields=[]
    for name in FIELDS:
        wanted,actual=getattr(request,name),getattr(observed,name)
        result=("not_requested" if wanted is None else "conflict" if actual.value is not None and actual.value!=wanted
                else "exact" if actual.value==wanted else "unsupported" if actual.state.value in ("unsupported","malformed","conflicting") else "missing")
        fields.append(ScopeField(name=name,requested=wanted,observed=actual,result=result))
    namespace="samgov-v1" if source=="samgov" else "usa-fpds-v1"
    missing=tuple(f.name for f in fields if f.result in ("missing","unsupported"))
    parents=[f for f in fields if f.name.startswith('parent_')]
    parent=('unknown_omitted' if request.parent_piid is None else 'present_conflicting' if any(f.result=='conflict' for f in parents)
        else 'present_compatible' if all(f.result=='exact' for f in parents) else 'unsupported_or_ambiguous' if any(f.result=='unsupported' for f in parents) else 'unknown_omitted')
    if not supported or namespace!=request.namespace:
        return ScopeStatus.UNSUPPORTED,tuple(fields),("unsupported_source_schema_or_namespace",),missing,"unsupported_or_ambiguous"
    if any(f.result=="conflict" for f in fields):
        return ScopeStatus.OUT_OF_SCOPE,tuple(fields),("known_requested_native_component_conflict",),missing,parent
    if conflicting or any(getattr(observed,f).state.value=="conflicting" for f in FIELDS):
        return ScopeStatus.AMBIGUOUS,tuple(fields),("conflicting_native_identity_versions",),missing,parent
    if missing:
        return ScopeStatus.INSUFFICIENT,tuple(fields),("requested_native_identity_prerequisite_missing",),missing,parent
    if request.parent_piid is None:
        return ScopeStatus.AMBIGUOUS,tuple(fields),("requested_parent_context_unknown_not_asserted_absent",),("requested_parent_context",),"unknown_omitted"
    return ScopeStatus.IN_SCOPE,tuple(fields),("exact_requested_native_context_only",),(),"present_compatible"


@dataclass(frozen=True,kw_only=True)
class ScopeAssessment(_ComputedIdentity):
    _computed_name="assessment_id"
    requested:ScopeRequest
    observed:ObservedIdentity
    evidence:MatchEvidenceReference
    content_sha256:str
    parser_version:str
    supported:bool
    conflicting_versions:bool
    status:ScopeStatus
    comparisons:tuple[ScopeField,...]
    reasons:tuple[str,...]
    missing_prerequisites:tuple[str,...]
    parent_state:str
    original_identity_json:str="{}"
    record:SourceRecordIdentity|None=None
    rule_version:str=RULE

    @property
    def assessment_id(self):
        return "scope-assessment:v1:"+digest({"request":self.requested.to_dict(),"observation":self.evidence.observation_id,
            "reference":self.evidence.reference.to_dict(),"content":self.content_sha256,"rule":self.rule_version})

    def validate(self):
        _hash(self.content_sha256)
        source=self.evidence.reference.source
        original=strict_json(self.original_identity_json.encode())
        if not isinstance(original,dict) or canonical(original)!=self.original_identity_json:
            raise ValueError("canonical original field-presence context required")
        if self.rule_version!=RULE or self.parser_version!=PARSERS.get(source):
            raise ValueError("unsupported scope rule/parser")
        if self.record is not None and (self.record.source!=source or self.evidence not in self.record.evidence
                or self.observed!=ObservedIdentity.from_record(self.record) or self.record.content_sha256!=self.content_sha256):
            raise ValueError("scope/native record provenance conflict")
        if source in ("fpds","usaspending") and self.supported and self.record is None:
            raise ValueError("supported C4 record required")
        expected=conclusion(self.requested,self.observed,supported=self.supported,conflicting=self.conflicting_versions,source=source)
        if (self.status,self.comparisons,self.reasons,self.missing_prerequisites,self.parent_state)!=expected:
            raise ValueError("scope result contradicts field evidence")


def assessment(request,observed,evidence,content_sha,*,record=None,supported=True,conflicting=False,original_identity_json="{}"):
    source=evidence.reference.source
    status,fields,reasons,missing,parent=conclusion(request,observed,supported=supported,conflicting=conflicting,source=source)
    return ScopeAssessment(requested=request,observed=observed,evidence=evidence,content_sha256=content_sha,
        parser_version=PARSERS[source],supported=supported,conflicting_versions=conflicting,status=status,
        comparisons=fields,reasons=reasons,missing_prerequisites=missing,parent_state=parent,record=record,original_identity_json=original_identity_json)


def conflicting_occurrences(values):
    groups={}
    for a in values:
        keys=[]
        components=tuple(getattr(a.observed,f).value for f in FIELDS)
        if all(v is not None for v in components): keys.append((a.evidence.reference.source,"action",components))
        if a.record:
            keys.extend((a.record.source,n.namespace,n.value) for n in a.record.native_identifiers if n.namespace in ("id","atom_id"))
        for key in keys: groups.setdefault(key,[]).append(a)
    return {a.assessment_id for values in groups.values() if len({a.content_sha256 for a in values})>1 for a in values}


@dataclass(frozen=True,kw_only=True)
class ScopeRun(Schema):
    requested:ScopeRequest
    input_manifest_sha256:str
    assessments:tuple[ScopeAssessment,...]
    artifact_issues:tuple[str,...]=()
    rule_version:str=RULE

    def validate(self):
        _hash(self.input_manifest_sha256)
        if self.rule_version!=RULE or any(a.requested!=self.requested for a in self.assessments):
            raise ValueError("scope run context conflict")
        ids=[a.assessment_id for a in self.assessments]
        if ids!=sorted(set(ids)):
            raise ValueError("canonical unique occurrence assessments required")
        conflicts=conflicting_occurrences(self.assessments)
        if any(a.conflicting_versions!=(a.assessment_id in conflicts) for a in self.assessments):
            raise ValueError("scope conflict flags contradict preserved native versions")

    @property
    def substantive_sha256(self):
        return digest(self.to_dict(substantive=True))

    @property
    def metrics(self):
        from .pilot_evaluation import rate
        counts={s.value:sum(a.status is s for a in self.assessments) for s in ScopeStatus}
        return {"version":"scope-metrics-v1","returned_record_occurrences":len(self.assessments),"counts":counts,
            "by_source":{source:{s.value:sum(a.evidence.reference.source==source and a.status is s for a in self.assessments) for s in ScopeStatus} for source in sorted({a.evidence.reference.source for a in self.assessments})},
            "returned_occurrence_count_complete":not self.artifact_issues,
            "in_scope_fraction":rate(counts[ScopeStatus.IN_SCOPE.value],len(self.assessments)),
            "distinct_record_contents":len({(a.evidence.reference.source,a.content_sha256) for a in self.assessments}),
            "retrieval_observations":len({a.evidence.observation_id for a in self.assessments}),
            "unparsed_or_unusable_artifacts":len(self.artifact_issues),"history":"unknown","freshness":"unknown"}
