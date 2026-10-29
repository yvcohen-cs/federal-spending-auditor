"""SAM research schema v1: native observations, never C4/C5 inputs or assurances."""
from dataclasses import dataclass, replace
from enum import Enum

from .evidence import Schema, _hash, _text
from .evidence_io import canonical, digest, strict_json
from .identity_matching import component, agency_component
from .review_packet_models import EvidenceCitation
from .scope_models import ScopeRequest, ObservedIdentity, ScopeStatus, conclusion

RULE = 'sam-research-record-v1'
# Source fields, not aliases into financial comparison. Parsed JSON values are
# canonical derived representations; exact numeric lexemes remain in body bytes.
PATHS = {
    'contractId.piid':'identifier', 'contractId.subtier.code':'identity_agency',
    'contractId.referencedIDVPiid':'parent_identifier','contractId.referencedIDVSubtier.code':'parent_agency',
    'contractId.modificationNumber':'modification','contractId.transactionNumber':'transaction',
    'contractId.referencedIDVModificationNumber':'parent_modification',
    'coreData.coreVersionId':'schema_version','coreData.awardOrIDV':'award_class',
    'coreData.awardOrIDVType.code':'instrument_type',
    'coreData.federalOrganization.contractingInformation.contractingSubtier.code':'contracting_agency',
    'coreData.federalOrganization.fundingInformation.fundingSubtier.code':'funding_agency',
    'awardDetails.dollars.actionObligation':'money','awardDetails.dollars.baseDollarsObligated':'money',
    'awardDetails.dollars.baseAndAllOptionsValue':'money','awardDetails.totalContractDollars.totalActionObligation':'money',
    'awardDetails.totalContractDollars.totalBaseAndAllOptionsValue':'money',
    'awardDetails.dates.dateSigned':'signed','awardDetails.dates.periodOfPerformanceStartDate':'performance_start',
    'awardDetails.transactionData.createdDate':'created','awardDetails.transactionData.approvedDate':'approved',
    'awardDetails.transactionData.lastModifiedDate':'last_modified','awardDetails.transactionData.closedDate':'closed',
    'awardDetails.transactionData.version':'document_version',
    'awardDetails.transactionData.status':'native_status',
    'oldContractId':'prior_identifier_context',
}
IDENTITY_PATHS = {'piid':'contractId.piid','agency':'contractId.subtier.code',
    'parent_piid':'contractId.referencedIDVPiid','parent_agency':'contractId.referencedIDVSubtier.code',
    'modification':'contractId.modificationNumber','transaction':'contractId.transactionNumber'}


class Presence(str, Enum):
    OMITTED = 'omitted'
    NULL = 'null'
    EMPTY = 'empty'
    VALUE = 'value'
    UNSUPPORTED = 'unsupported'


def lookup(row,path):
    node = row
    for name in path.split('.'):
        if not isinstance(node,dict):
            return Presence.UNSUPPORTED,node
        if name not in node:
            return Presence.OMITTED,None
        node = node[name]
    if node is None: return Presence.NULL,None
    if node == '': return Presence.EMPTY,''
    if isinstance(node,str): return Presence.VALUE,node
    # Objects are retained for status/prior identity context, never coerced.
    return Presence.UNSUPPORTED,node


@dataclass(frozen=True,kw_only=True)
class SAMField(Schema):
    path: str
    meaning: str
    presence: Presence
    original_json: str
    units: str|None = None

    def validate(self):
        if PATHS.get(self.path) != self.meaning:
            raise ValueError('unsupported SAM field mapping')
        value = strict_json(self.original_json.encode())
        if canonical(value) != self.original_json:
            raise ValueError('canonical parsed source value required')
        if (self.presence in (Presence.OMITTED,Presence.NULL) and value is not None
                or self.presence is Presence.EMPTY and value != ''
                or self.presence is Presence.VALUE and (not isinstance(value,str) or not value)):
            raise ValueError('contradictory field presence')
        expected = 'source_dollars_label_currency_and_basis_unverified' if self.meaning=='money' else None
        if self.units != expected: raise ValueError('unsupported monetary units assertion')


def fields_for(row):
    return tuple(SAMField(path=path,meaning=PATHS[path],presence=lookup(row,path)[0],
        original_json=canonical(lookup(row,path)[1]),
        units='source_dollars_label_currency_and_basis_unverified' if PATHS[path]=='money' else None) for path in sorted(PATHS))


def native_identity(fields):
    from .matching_models import IdentifierState
    values={f.path:f for f in fields};components={}
    for name,path in IDENTITY_PATHS.items():
        field=values[path]
        raw=strict_json(field.original_json.encode())
        c=component(raw) if field.presence is not Presence.OMITTED else component(basis='unavailable')
        if name in ('parent_piid','parent_agency') and isinstance(raw,str) and raw in ('-NONE-','-none-','NONE','N/A','NULL'):
            c=replace(c,state=IdentifierState.UNSUPPORTED,value=None)
        if name in ('agency','parent_agency'):c=agency_component(c)
        components[name]=c
    return ObservedIdentity(**components)


@dataclass(frozen=True,kw_only=True)
class SAMNativeAward(Schema):
    piid: str|None
    identity_subtier: str|None
    parent_piid: str|None
    parent_subtier: str|None
    award_class: str|None
    instrument_type: str|None

    def validate(self):
        for v in (self.piid,self.identity_subtier,self.parent_piid,self.parent_subtier,self.award_class,self.instrument_type):
            if v is not None: _text(v,'native component')


@dataclass(frozen=True,kw_only=True)
class SAMNativeAction(Schema):
    modification: str|None
    transaction: str|None
    parent_modification: str|None
    document_version: str|None
    revision_relationship: str = 'unknown_no_cross_source_revision_certificate'
    deletion_relationship: str = 'unknown_no_record_deletion_indicator_validated'
    correction_relationship: str = 'unknown_prior_identity_is_not_correction_lineage'

    def validate(self):
        for v in (self.modification,self.transaction,self.parent_modification,self.document_version):
            if v is not None: _text(v,'native action component')
        if (self.revision_relationship!='unknown_no_cross_source_revision_certificate'
            or self.deletion_relationship!='unknown_no_record_deletion_indicator_validated'
            or self.correction_relationship!='unknown_prior_identity_is_not_correction_lineage'):
            raise ValueError('unsupported revision/correction/deletion guarantee')


def derive(requested,fields):
    lookup_fields={f.path:f for f in fields}
    def value(path):
        f=lookup_fields[path]
        return strict_json(f.original_json.encode()) if f.presence is Presence.VALUE else None
    observed=native_identity(fields)
    core=value('coreData.coreVersionId'); kind=value('coreData.awardOrIDV'); instrument=value('coreData.awardOrIDVType.code')
    supported = core in ('1.4','1.5') and kind in ('AWARD','IDV') and all(
        lookup_fields[p].presence in (Presence.OMITTED,Presence.NULL,Presence.EMPTY,Presence.VALUE) for p in IDENTITY_PATHS.values())
    legacy=conclusion(requested,observed,source='samgov',supported=all(
        lookup_fields[p].presence is not Presence.UNSUPPORTED for p in IDENTITY_PATHS.values()))[0]
    scope=conclusion(requested,observed,source='samgov',supported=supported)[0]
    pair=(observed.parent_piid.value,observed.parent_agency.value)
    parent='parent_relationship_unknown'
    if not supported: parent='unsupported_parent_semantics'
    elif all(v is not None for v in pair) and kind=='AWARD' and instrument in ('A','C'):
        parent='parent_relationship_conflict' if requested.parent_piid is not None and pair!=(requested.parent_piid,requested.parent_agency) else 'verified_parent_relationship'
    if kind=='IDV' and supported:
        scope=ScopeStatus.OUT_OF_SCOPE # request is explicitly Award, never IDV.
    elif scope is ScopeStatus.IN_SCOPE and parent!='verified_parent_relationship':
        scope=ScopeStatus.AMBIGUOUS
    # No source-specific SAM positive absence rule is claimed in this phase.
    award=SAMNativeAward(piid=observed.piid.value,identity_subtier=observed.agency.value,
        parent_piid=pair[0],parent_subtier=pair[1],award_class=kind,instrument_type=instrument)
    action=SAMNativeAction(modification=observed.modification.value,transaction=observed.transaction.value,
        parent_modification=value('contractId.referencedIDVModificationNumber'),document_version=value('awardDetails.transactionData.version'))
    return observed,award,action,legacy,scope,parent,supported


@dataclass(frozen=True,kw_only=True)
class SAMObservedRecord(Schema):
    requested: ScopeRequest
    citation: EvidenceCitation
    original_record_json: str
    fields: tuple[SAMField,...]
    identity: ObservedIdentity
    award: SAMNativeAward
    action: SAMNativeAction
    previous_scope: ScopeStatus
    scope: ScopeStatus
    parent_status: str
    supported_schema: bool
    content_sha256: str
    rule_version: str = RULE

    @property
    def claim_id(self):
        return 'sam-record-claim:v1:'+digest({'requested':self.requested.to_dict(),
            'citation':self.citation.citation_id,'content':self.content_sha256,'rule':self.rule_version})

    def validate(self):
        row=strict_json(self.original_record_json.encode())
        if self.rule_version!=RULE or self.requested.namespace!='samgov-v1' or self.citation.evidence.reference.source!='samgov':
            raise ValueError('unsupported SAM identity namespace/rule')
        _hash(self.content_sha256)
        if canonical(row)!=self.original_record_json or digest(row)!=self.content_sha256 or self.fields!=fields_for(row):
            raise ValueError('SAM source field/content conflict')
        expected=derive(self.requested,self.fields)
        if (self.identity,self.award,self.action,self.previous_scope,self.scope,self.parent_status,self.supported_schema)!=expected:
            raise ValueError('contradictory or unsupported SAM source assertion')


def record(row,requested,citation):
    fields=fields_for(row)
    identity,award,action,old,new,parent,supported=derive(requested,fields)
    return SAMObservedRecord(requested=requested,citation=citation,original_record_json=canonical(row),fields=fields,
        identity=identity,award=award,action=action,previous_scope=old,scope=new,parent_status=parent,supported_schema=supported,content_sha256=digest(row))


def counter(value):
    if type(value) is int and 0<=value<=100000000: return value
    if isinstance(value,str) and value.isascii() and value.isdigit() and 1<=len(value)<=9 and int(value)<=100000000: return int(value)
    raise ValueError('unsupported_sam_counter')


@dataclass(frozen=True,kw_only=True)
class SAMPage(Schema):
    offset: int
    limit: int
    total: int
    records: tuple[SAMObservedRecord,...]
    bounded_query_terminal: bool|None
    pagination_rule: str
    history_complete: str = 'unknown'
    source_wide_complete: str = 'unknown'
    freshness: str = 'unknown'

    def validate(self):
        if (not 0<=self.offset<=10 or not 1<=self.limit<=10 or not 0<=self.total<=100000000 or len(self.records)>self.limit
                or self.total<len(self.records) or self.pagination_rule not in ('unvalidated','synthetic_row_offset','synthetic_page_index')
                or any(v!='unknown' for v in (self.history_complete,self.source_wide_complete,self.freshness))):
            raise ValueError('invalid SAM page or unsupported coverage claim')
        start=self.offset*self.limit if self.pagination_rule=='synthetic_page_index' else self.offset
        expected=None if self.pagination_rule=='unvalidated' else start+len(self.records)>=self.total
        if self.bounded_query_terminal is not expected:
            raise ValueError('unsupported terminal page assertion')
        if self.pagination_rule!='unvalidated' and (start+len(self.records)>self.total or not self.records and start<self.total):
            raise ValueError('contradictory SAM page count')


def parse_page(raw,requested,artifact,metadata_path,*,offset=0,limit=10,pagination_rule='unvalidated'):
    from .evidence import EvidenceRecordRef
    from .matching_models import MatchEvidenceReference
    import hashlib
    from .sam_contracts import ENDPOINT,public_request
    expected_request=public_request(requested,limit)
    expected_request['parameters'].update(includeSections='contractId,coreData,awardDetails',offset=offset)
    if (artifact.source!='samgov' or artifact.endpoint!=ENDPOINT or artifact.method!='GET'
            or artifact.sha256!=hashlib.sha256(raw).hexdigest() or artifact.request_json!=canonical(expected_request['parameters'])
            or artifact.representation.value!='response_bytes' or artifact.retrieved_at_utc is None
            or artifact.http_status is None or not 200<=artifact.http_status<300):
        raise ValueError('SAM_page_artifact_request_or_body_conflict')
    body=strict_json(raw)
    if (not isinstance(body,dict) or set(body)!={'awardSummary','totalRecords','limit','offset'}
            or not isinstance(body['awardSummary'],list) or len(body['awardSummary'])>limit or counter(body['offset'])!=offset or counter(body['limit'])!=limit):
        raise ValueError('unsupported_sam_response_envelope')
    observation='observation:v1:'+digest({'version':1,'source':artifact.source,'endpoint':artifact.endpoint,'method':artifact.method,
        'request_json':artifact.request_json,'retrieved_at_utc':artifact.retrieved_at_utc,'representation':artifact.representation.value})
    records=tuple(record(row,requested,EvidenceCitation(evidence=MatchEvidenceReference(
        reference=EvidenceRecordRef(source='samgov',artifact_id=artifact.artifact_id,locator=f'/awardSummary/{i}'),artifact=artifact,
        observation_id=observation,metadata_paths=('pilot-plan.json',metadata_path)))) for i,row in enumerate(body['awardSummary']))
    total=counter(body['totalRecords']);start=offset*limit if pagination_rule=='synthetic_page_index' else offset
    terminal=None if pagination_rule=='unvalidated' else start+len(records)>=total
    return SAMPage(offset=offset,limit=limit,total=total,records=records,bounded_query_terminal=terminal,pagination_rule=pagination_rule)
