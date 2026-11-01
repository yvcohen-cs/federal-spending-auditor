"""C11 bounded source-specific plans, reconstructed from C10 primary evidence."""
from dataclasses import dataclass
from enum import Enum

from .collection import SelectedAward
from .collection_sources import request_for, USA, FPDS
from .evidence import Schema, _hash
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .history_qualification import HistoricalInterval, qualify, documentation, QualificationStatus
from .history_qualification_reporting import verify_report
from .sam_contracts import ENDPOINT as SAM
from .sam_validation_capture import public_request as sam_request, secret_free
from .scope_models import ScopeRequest

RULE='targeted-acquisition-v1'


class QuerySupport(str,Enum):
    DOCUMENTED_SUBSET='documented_adapter_subset_not_live_scope_certification'
    VALIDATION_REQUIRED='additional_source_validation_required'
    BLOCKED='native_selection_unavailable_or_ambiguous'


@dataclass(frozen=True,kw_only=True)
class AcquisitionLimits(Schema):
    max_jobs:int=8
    max_requests:int=16
    max_pages:int=2
    page_size:int=2
    retries:int=0
    max_response_bytes:int=1048576

    def validate(self):
        if not (1<=self.max_jobs<=32 and 1<=self.max_requests<=64 and 1<=self.max_pages<=4
            and 1<=self.page_size<=10 and 0<=self.retries<=1 and 1024<=self.max_response_bytes<=1048576):
            raise ValueError('bounded_acquisition_limits_required')


@dataclass(frozen=True,kw_only=True)
class RequirementTarget(Schema):
    case_id:str
    contract_id:str
    plan_id:str
    dimension:str
    original_requirement_json:str

    def validate(self):
        _hash(self.case_id)
        from .history_qualification import ProofRequirement
        value=strict_json(self.original_requirement_json.encode())
        req=ProofRequirement.from_dict(value)
        if req.dimension!=self.dimension or req.status is QualificationStatus.QUALIFIED or canonical(value)!=self.original_requirement_json:
            raise ValueError('original_requirement_binding_conflict')
        if not self.plan_id.startswith('evidence-resolution:v1:') or not self.contract_id.startswith('qualified-contract:v1:'):
            raise ValueError('constructed_plan_contract_references_required')


@dataclass(frozen=True,kw_only=True)
class SourceRequestSpec(Schema):
    source:str
    target_kind:str
    native_context_json:str
    selection_json:str|None
    historical_interval:HistoricalInterval
    requested_fields:tuple[str,...]
    documentation_dependencies:tuple[str,...]
    requirements:tuple[RequirementTarget,...]
    limits:AcquisitionLimits
    evidence_profile:str
    query_support:QuerySupport
    request_json:str|None
    blockers:tuple[str,...]
    pagination_requirement:str
    expected_evidence:str='original_capture_representation_request_controls_native_fields_hashes_locators_and_historical_timestamps'
    stop_conditions:tuple[str,...]=('authorization_or_access_unverified','scope_or_native_identity_conflict','unsafe_or_unsupported_pagination','request_page_or_byte_budget_exhausted','unavailable_incomplete_or_changed_primary_evidence','requested_historical_interval_or_asof_unestablished')
    verified_live_API_behavior:str='none_claimed_offline_phase_only'
    validated_offline_behavior:tuple[str,...]=('existing_schema_parser_subset','literal_native_identifier_serialization','preserved_control_and_body_hash_replay')
    validation_assumptions:tuple[str,...]=('native_query_scope_enforcement','parent_IDV_mapping','historical_interval_and_asof_coverage','revision_correction_deletion_lineage','freshness_and_snapshot_consistency','SAM_live_offset_continuation')
    live_request_authorized:bool=False
    rule_version:str=RULE

    @property
    def request_id(self):
        return 'evidence-request:v1:'+digest(self.to_dict())

    def validate(self):
        if self.source not in ('usaspending','fpds','samgov') or self.target_kind not in ('award_history','parent_idv'):
            raise ValueError('source_native_request_kind_required')
        if self.evidence_profile not in ('synthetic','live') or self.live_request_authorized is not False or self.rule_version!=RULE or self.verified_live_API_behavior!='none_claimed_offline_phase_only':
            raise ValueError('request_does_not_authorize_live_collection')
        native=strict_json(self.native_context_json.encode())
        if not isinstance(native,dict) or set(native)!={'piid','agency','parent_piid','parent_agency'} or any(v is not None and type(v) is not str for v in native.values()) or canonical(native)!=self.native_context_json or not secret_free(native):
            raise ValueError('safe_canonical_native_context_required')
        for seq in (self.requested_fields,self.documentation_dependencies,self.blockers):
            if seq!=tuple(sorted(set(seq))):raise ValueError('canonical_request_fields_required')
        if not self.requirements or len(self.requirements)>4000 or tuple(canonical(t.to_dict()) for t in self.requirements)!=tuple(sorted({canonical(t.to_dict()) for t in self.requirements})):
            raise ValueError('canonical_bounded_requirement_targets_required')
        expected=_query(self.source,self.target_kind,native,self.selection_json,self.limits)
        if (self.query_support,self.request_json,self.blockers,self.pagination_requirement)!=expected:
            raise ValueError('query_specification_contradicts_native_selection_or_adapter')
        if self.requested_fields!=tuple(sorted(FIELDS[self.source])) or not self.documentation_dependencies or not set(self.documentation_dependencies)<=set(documentation(('usaspending','fpds','samgov'))) or not secret_free(self.to_dict()):
            raise ValueError('source_documentation_dependencies_required')
        if self.request_json is not None and not secret_free(strict_json(self.request_json.encode())):
            raise ValueError('credential_material_forbidden_in_request')


@dataclass(frozen=True,kw_only=True)
class AcquisitionQueue(Schema):
    case_sha256:tuple[str,...]
    requests:tuple[SourceRequestSpec,...]
    excluded_plan_ids:tuple[str,...]
    deferred_plan_ids:tuple[str,...]
    limits:AcquisitionLimits
    rule_version:str=RULE

    @property
    def queue_sha256(self):return digest(self.to_dict())

    def validate(self):
        if self.rule_version!=RULE or not 1<=len(self.case_sha256)<=24 or self.case_sha256!=tuple(sorted(set(self.case_sha256))):
            raise ValueError('bounded_unique_primary_cases_required')
        for v in self.case_sha256:_hash(v)
        if len(self.requests)>self.limits.max_jobs or len({r.request_id for r in self.requests})!=len(self.requests):
            raise ValueError('bounded_unique_acquisition_queue_required')
        for r in self.requests:
            if r.limits!=self.limits or any(t.case_id not in self.case_sha256 for t in r.requirements):
                raise ValueError('queue_budget_or_primary_case_conflict')
        for ids in (self.excluded_plan_ids,self.deferred_plan_ids):
            if len(ids)>4000 or ids!=tuple(sorted(set(ids))):raise ValueError('bounded_canonical_plan_backlog_required')
        covered={t.plan_id for r in self.requests for t in r.requirements}
        if covered.intersection(self.excluded_plan_ids) or covered.intersection(self.deferred_plan_ids) or set(self.excluded_plan_ids).intersection(self.deferred_plan_ids):
            raise ValueError('contradictory_plan_disposition')


def _query(source,kind,native,selection_json,limits):
    blockers=[];request=None
    pagination=('validated_same_endpoint_FPDS_next_link_only' if source=='fpds' else 'one_origin_USAspending_page_and_hasNext' if source=='usaspending' else 'frozen_first_page_only_live_offset_contract_unverified')
    if kind=='parent_idv':
        blockers.append('parent_IDV_query_and_primary_record_mapping_require_separate_validation')
        if native.get('piid') is None or native.get('agency') is None:blockers.append('missing_source_native_parent_pair')
        # No Award query is relabeled as IDV evidence. No generated USA parent
        # award ID or SAM/FPDS namespace is inferred from a child reference.
        return (QuerySupport.VALIDATION_REQUIRED if len(blockers)==1 else QuerySupport.BLOCKED,None,tuple(sorted(blockers)),pagination)
    if selection_json is None:
        return QuerySupport.BLOCKED,None,('missing_or_ambiguous_source_native_query_selection',),pagination
    value=strict_json(selection_json.encode())
    if canonical(value)!=selection_json:raise ValueError('canonical_source_selection_required')
    if source in ('usaspending','fpds'):
        selected=SelectedAward.from_dict(value)
        if (selected.piid,selected.agency_id,selected.parent_piid,selected.parent_agency_id)!=(native.get('piid'),native.get('agency'),native.get('parent_piid'),native.get('parent_agency')):
            raise ValueError('selection_native_context_conflict')
        if source=='usaspending' and selected.generated_id is None:raise ValueError('observed_USA_query_award_id_required')
        request=request_for(source,selected.to_dict(),1,limits.page_size)
    else:
        selected=ScopeRequest.from_dict(value)
        if selected.namespace!='samgov-v1' or (selected.piid,selected.agency,selected.parent_piid,selected.parent_agency)!=(native.get('piid'),native.get('agency'),native.get('parent_piid'),native.get('parent_agency')):
            raise ValueError('SAM_native_selection_conflict')
        request=sam_request(selected,limits.page_size,0)
    return QuerySupport.DOCUMENTED_SUBSET,canonical(request),(),pagination


def native_context(contract):
    q=contract['qualification'];context=strict_json(q['native_context_json'].encode())
    if q['source']=='samgov':
        a=context['award']
        return {'piid':a['piid'],'agency':a['identity_subtier'],'parent_piid':a['parent_piid'],'parent_agency':a['parent_subtier']}
    return {k:context.get(k) for k in ('piid','agency','parent_piid','parent_agency')}


def selection(source,native,contract):
    if native['piid'] is None or native['agency'] is None or (native['parent_piid'] is None)!=(native['parent_agency'] is None):return None
    if source=='samgov':
        return canonical(ScopeRequest(namespace='samgov-v1',**native).to_dict())
    generated=None
    if source=='usaspending':
        values=set()
        for row in contract['observed_occurrences']:
            if row['source']!='usaspending':continue
            params=strict_json(row['citation']['artifact']['request_json'].encode())
            if isinstance(params.get('award_id'),str):values.add(params['award_id'])
        if len(values)!=1:return None
        generated=next(iter(values)) # Original request selection, not a constructed crosswalk.
    return canonical(SelectedAward(generated_id=generated,piid=native['piid'],agency_id=native['agency'],
        parent_piid=native['parent_piid'],parent_agency_id=native['parent_agency']).to_dict())


def case_report(case):
    """Paths are runtime inputs, never serialized into the public work queue."""
    collections=tuple(case.get('collections',()));sam=tuple(case.get('sam_captures',()))
    scope=case.get('scope')
    if isinstance(scope,dict):scope=ScopeRequest.from_dict(scope)
    interval=case.get('interval')
    if isinstance(interval,dict):interval=HistoricalInterval.from_dict(interval)
    if case.get('report'):
        return verify_report(case['report'],collections,scope,sam_captures=sam,interval=interval)
    return qualify(collections,scope,sam_captures=sam,interval=interval)


PRIORITY={'native_identity':0,'parent_identity':0,'source_completeness':1,'revision_completeness':1,'counterpart_coverage':2,
          'as_of_alignment':2,'monetary_semantics':3,'currency_amount':3,'provenance_integrity':0,'freshness':4}
FIELDS={'usaspending':('action_date','award_id','federal_action_obligation','id','modification_number'),
        'fpds':('awardID','contractData/contractActionType','dollarValues','relevantContractDates','transactionInformation'),
        'samgov':('awardDetails','contractId','coreData')}


def prepare(cases,*,limits=None):
    cases=tuple(cases);limits=limits or AcquisitionLimits()
    if not 1<=len(cases)<=24 or not isinstance(limits,AcquisitionLimits):raise EvidenceError('bounded_typed_acquisition_cases_required')
    reports=[];size=0
    from .history_reporting import bounded_json
    for case in cases:
        report=case_report(case);size+=len(bounded_json(report))
        if size>32*1024*1024:raise EvidenceError('primary_case_report_byte_limit')
        reports.append(report)
    case_ids=tuple(sorted(digest(r) for r in reports))
    if len(set(case_ids))!=len(case_ids):raise EvidenceError('duplicate_primary_acquisition_case')
    groups={};excluded=set();all_plans=set()
    for report in reports:
        case_id=digest(report);contracts={c['qualification']['contract_id']:c for c in report['contracts']}
        if report['profile'] not in ('synthetic','live'):raise EvidenceError('unrevalidated_capture_cannot_prepare_requests')
        for plan in report['resolution_plans']:
            all_plans.add(plan['plan_id'])
            if len(all_plans)>4000:raise EvidenceError('acquisition_plan_count_limit')
            contract=contracts[plan['contract_id']]
            if contract['selection_status']=='outside_requested_context_not_evaluated':
                excluded.add(plan['plan_id']);continue
            dimension=plan['requirement']['dimension'];native=native_context(contract)
            kind='parent_idv' if dimension=='parent_identity' else 'award_history'
            for source in plan['relevant_sources']:
                # Only the existing complete USA/FPDS component mapping permits
                # counterpart planning. SAM always remains source-local.
                if source!=contract['qualification']['source'] and (source=='samgov' or any(v is None for v in native.values()) or any(r['action'] is None for r in contract['observed_occurrences'])):
                    continue
                target_native=({'piid':native['parent_piid'],'agency':native['parent_agency'],'parent_piid':None,'parent_agency':None} if kind=='parent_idv' else native)
                selected=selection(source,target_native,contract) if kind=='award_history' else None
                key=canonical({'source':source,'kind':kind,'native':target_native,'selection':selected,'interval':plan['historical_interval'],'profile':report['profile'],
                    'unresolved_contract':plan['contract_id'] if target_native['piid'] is None or target_native['agency'] is None else None})
                entry=groups.setdefault(key,{'source':source,'kind':kind,'native':target_native,'selection':selected,'interval':HistoricalInterval.from_dict(plan['historical_interval']),
                    'profile':report['profile'],'requirements':{},'docs':set()})
                t=RequirementTarget(case_id=case_id,contract_id=plan['contract_id'],plan_id=plan['plan_id'],dimension=dimension,original_requirement_json=canonical(plan['requirement']))
                entry['requirements'][canonical(t.to_dict())]=t;entry['docs'].update(plan['documentation_dependencies'])
    specs=[]
    for entry in groups.values():
        support,query,blockers,pagination=_query(entry['source'],entry['kind'],entry['native'],entry['selection'],limits)
        specs.append(SourceRequestSpec(source=entry['source'],target_kind=entry['kind'],native_context_json=canonical(entry['native']),selection_json=entry['selection'],
            historical_interval=entry['interval'],requested_fields=tuple(sorted(FIELDS[entry['source']])),documentation_dependencies=tuple(sorted(entry['docs'])),
            requirements=tuple(entry['requirements'][k] for k in sorted(entry['requirements'])),limits=limits,evidence_profile=entry['profile'],
            query_support=support,request_json=query,blockers=blockers,pagination_requirement=pagination))
    def rank(s):return (min(PRIORITY[t.dimension] for t in s.requirements),-len(s.requirements),s.source,s.native_context_json,s.request_id)
    supported=sorted((s for s in specs if s.query_support is QuerySupport.DOCUMENTED_SUBSET),key=rank)
    validation=sorted((s for s in specs if s.query_support is not QuerySupport.DOCUMENTED_SUBSET),key=rank)
    # Interleave executable offline subsets with explicit validation dependencies;
    # an unresolved parent query cannot starve every history replay job.
    ordered=[]
    while supported or validation:
        if supported:ordered.append(supported.pop(0))
        if validation:ordered.append(validation.pop(0))
    chosen=tuple(ordered[:limits.max_jobs]);covered={t.plan_id for s in chosen for t in s.requirements}
    return AcquisitionQueue(case_sha256=case_ids,requests=chosen,excluded_plan_ids=tuple(sorted(excluded)),
        deferred_plan_ids=tuple(sorted(all_plans-covered-excluded)),limits=limits)
