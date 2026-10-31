"""C10 offline, source-local contract-history qualification; no money gate."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum

from .award_validation import validate as diagnose, snapshot
from .evidence import Schema, _text
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .financial_models import USA_ACTION, FPDS_ACTION, AmountBasis, FinancialScope
from .financial_values import has_cent_precision, NumericState
from .history_ingestion import reconstruct
from .parent_identity import assess_parent, ParentStatus, SOURCES
from .scope_models import FIELDS

RULE = 'contract-history-qualification-v1'
DIMENSIONS = ('native_identity', 'parent_identity', 'source_completeness', 'revision_completeness',
              'monetary_semantics', 'as_of_alignment', 'currency_amount', 'counterpart_coverage', 'provenance_integrity', 'freshness')


class QualificationStatus(str, Enum):
    QUALIFIED = 'QUALIFIED_EVIDENCE'
    INSUFFICIENT = 'INSUFFICIENT_EVIDENCE'
    CONFLICTING = 'CONFLICTING_EVIDENCE'
    NOT_EVALUATED = 'NOT_EVALUATED'


class EvidenceKind(str, Enum):
    OBSERVED = 'observed_support'
    MISSING = 'missing_evidence'
    CONTRADICTORY = 'contradictory_observations'
    NOT_EVALUATED = 'not_evaluated'


class GapCategory(str, Enum):
    PAGINATION = 'incomplete_pagination_or_source_coverage'
    COUNTERPART = 'missing_observed_counterparts'
    IDENTITY = 'unresolved_native_identity'
    PARENT = 'unknown_parent_relationship_or_parent_award'
    REVISION = 'incomplete_revision_history'
    FRESHNESS = 'unverified_source_freshness'
    MONEY = 'incompatible_or_unverified_monetary_observations'
    CONFLICT = 'conflicting_source_records'
    PROVENANCE = 'provenance_integrity'


@dataclass(frozen=True, kw_only=True)
class HistoricalInterval(Schema):
    """Requested scope only; never evidence that this interval was captured."""
    start_date: str | None = None
    end_date: str | None = None
    as_of_date: str | None = None

    def validate(self):
        for v in (self.start_date, self.end_date, self.as_of_date):
            if v is not None and (type(v) is not str or date.fromisoformat(v).isoformat() != v):
                raise ValueError('exact_calendar_date_required')
        if (self.start_date is None) != (self.end_date is None):
            raise ValueError('paired_requested_interval_required')
        if self.start_date is not None and self.start_date > self.end_date:
            raise ValueError('reversed_requested_interval')


@dataclass(frozen=True, kw_only=True)
class ProofRequirement(Schema):
    dimension: str
    status: QualificationStatus
    evidence_kind: EvidenceKind
    reasons: tuple[str, ...]
    citation_ids: tuple[str, ...]

    def validate(self):
        if self.dimension not in DIMENSIONS or not self.reasons or self.reasons != tuple(sorted(set(self.reasons))):
            raise ValueError('canonical_narrow_requirement_required')
        if self.citation_ids != tuple(sorted(set(self.citation_ids))):
            raise ValueError('canonical_citations_required')
        for v in self.reasons + self.citation_ids:
            _text(v, 'bounded proof reference')
            if len(v) > 256:
                raise ValueError('proof_text_bound')
        expected = {QualificationStatus.QUALIFIED: EvidenceKind.OBSERVED,
            QualificationStatus.INSUFFICIENT: EvidenceKind.MISSING,
            QualificationStatus.CONFLICTING: EvidenceKind.CONTRADICTORY,
            QualificationStatus.NOT_EVALUATED: EvidenceKind.NOT_EVALUATED}[self.status]
        if self.evidence_kind is not expected or (self.status in (QualificationStatus.QUALIFIED, QualificationStatus.CONFLICTING) and not self.citation_ids):
            raise ValueError('status_requires_corresponding_evidence')


def aggregate(requirements):
    states = {r.status for r in requirements}
    for state in (QualificationStatus.CONFLICTING, QualificationStatus.INSUFFICIENT, QualificationStatus.NOT_EVALUATED):
        if state in states:
            return state
    return QualificationStatus.QUALIFIED if states else QualificationStatus.NOT_EVALUATED


@dataclass(frozen=True, kw_only=True)
class ContractQualification(Schema):
    contract_id: str
    source: str
    native_context_json: str
    occurrence_ids: tuple[str, ...]
    requirements: tuple[ProofRequirement, ...]
    status: QualificationStatus
    rule_version: str = RULE
    financial_comparison_authorized: bool = False

    def validate(self):
        if self.source not in ('usaspending', 'fpds', 'samgov') or self.rule_version != RULE or self.financial_comparison_authorized is not False:
            raise ValueError('qualification_cannot_change_financial_authority')
        context = strict_json(self.native_context_json.encode())
        if not isinstance(context, dict) or canonical(context) != self.native_context_json or context.get('namespace') != self.source:
            raise ValueError('canonical_native_context_required')
        expected = 'qualified-contract:v1:' + digest({'source': self.source, 'native_context': context})
        if self.contract_id != expected or not self.occurrence_ids or self.occurrence_ids != tuple(sorted(set(self.occurrence_ids))):
            raise ValueError('contract_binding_or_occurrences_invalid')
        if tuple(r.dimension for r in self.requirements) != DIMENSIONS or self.status is not aggregate(self.requirements):
            raise ValueError('qualification_contradicts_independent_requirements')


CATEGORY = dict(zip(DIMENSIONS, (GapCategory.IDENTITY, GapCategory.PARENT, GapCategory.PAGINATION,
    GapCategory.REVISION, GapCategory.MONEY, GapCategory.REVISION, GapCategory.MONEY, GapCategory.COUNTERPART, GapCategory.PROVENANCE, GapCategory.FRESHNESS)))
OBSERVATIONS = {
    'native_identity': 'Source-native award and action fields that resolve the cited unsupported, missing or conflicting components.',
    'parent_identity': 'Applicable instrument semantics, exact referenced IDV PIID and identity agency, and a separately cited authoritative parent IDV record; or a supported source-specific no-parent rule.',
    'source_completeness': 'All bounded query pages plus authoritative query-scope, recall, action-history and deletion-visibility evidence for the requested historical interval.',
    'revision_completeness': 'Native action revision IDs, correction/replacement direction, deleted/reinstated actions and authoritative history bounds; retain all prior observations.',
    'monetary_semantics': 'Documented source paths defining incremental action obligations versus cumulative award values, units, signs and precision.',
    'as_of_alignment': 'Source-native proof of a common monetary reporting revision and as-of visibility; equal retrieval or signed dates are insufficient.',
    'currency_amount': 'Explicit compatible currencies and exact supported numeric observations for each native action at the same certified revision; no rounding or currency conversion.',
    'counterpart_coverage': 'Primary counterpart records with exact native award, parent and action components in the existing verified namespace mapping; missing observations never establish absence.',
    'provenance_integrity': 'Original permitted capture representation, request controls, source locator and hash-bound provenance that can be independently replayed.',
    'freshness': 'Authoritative source publication/update semantics, timezone, reporting delay and snapshot-consistency evidence for the requested as-of date.'}


@dataclass(frozen=True, kw_only=True)
class EvidenceResolutionPlan(Schema):
    contract_id: str
    requirement: ProofRequirement
    category: GapCategory
    source: str
    relevant_sources: tuple[str, ...]
    native_identifiers_json: str
    observed_action_identifiers_json: str
    historical_interval: HistoricalInterval
    missing_observation: str
    documentation_dependencies: tuple[str, ...]
    verification_procedure: str
    expected_artifact: str
    stop_condition: str

    @property
    def plan_id(self):
        return 'evidence-resolution:v1:' + digest(self.to_dict())

    def validate(self):
        if self.source not in ('usaspending','fpds','samgov') or self.requirement.status is QualificationStatus.QUALIFIED:
            raise ValueError('unresolved_source_requirement_required')
        context = strict_json(self.native_identifiers_json.encode())
        if not isinstance(context,dict) or canonical(context) != self.native_identifiers_json:
            raise ValueError('native_plan_context_required')
        actions=strict_json(self.observed_action_identifiers_json.encode())
        if not isinstance(actions,list) or len(actions)>1000 or canonical(actions)!=self.observed_action_identifiers_json:
            raise ValueError('canonical_observed_action_contexts_required')
        if self.category is not CATEGORY[self.requirement.dimension] or self.missing_observation != OBSERVATIONS[self.requirement.dimension]:
            raise ValueError('resolution_claim_conflict')
        expected_sources=tuple(sorted(('usaspending','fpds'))) if self.requirement.dimension=='counterpart_coverage' and self.source!='samgov' else (self.source,)
        if self.relevant_sources!=expected_sources or self.documentation_dependencies!=documentation(expected_sources):
            raise ValueError('source_bound_documentation_references_required')
        for text in (self.verification_procedure,self.expected_artifact,self.stop_condition):
            _text(text,'explicit_resolution_step')


def requirement(dimension, status, reasons, citations):
    kind = {QualificationStatus.QUALIFIED: EvidenceKind.OBSERVED, QualificationStatus.INSUFFICIENT: EvidenceKind.MISSING,
        QualificationStatus.CONFLICTING: EvidenceKind.CONTRADICTORY, QualificationStatus.NOT_EVALUATED: EvidenceKind.NOT_EVALUATED}[status]
    return ProofRequirement(dimension=dimension,status=status,evidence_kind=kind,reasons=tuple(sorted(set(reasons))),citation_ids=tuple(sorted(set(citations))))


def documentation(sources):
    prefixes=tuple({'usaspending':'usa-', 'fpds':'fpds-', 'samgov':'sam-'}[s] for s in sources)
    extra={'usaspending':('https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/transactions.md',
        'https://www.usaspending.gov/data/about-the-data-download.pdf'),
        'fpds':('https://www.fpds.gov/help/Correct_a_Transaction.htm','https://www.fpds.gov/downloads/Manuals/FPDS-NG_User_Manual_V15.pdf'),
        'samgov':('https://open.gsa.gov/api/contract-awards/v1/openapi.yaml',)}
    return tuple(sorted({url for key,url,_ in SOURCES if key.startswith(prefixes)} | {u for source in sources for u in extra[source]}))


def resolution(qualification, req, interval, rows):
    sources=tuple(sorted(('usaspending','fpds'))) if req.dimension=='counterpart_coverage' and qualification.source!='samgov' else (qualification.source,)
    docs=documentation(sources)
    return EvidenceResolutionPlan(contract_id=qualification.contract_id,requirement=req,category=CATEGORY[req.dimension],
        source=qualification.source,relevant_sources=sources,native_identifiers_json=qualification.native_context_json,
        observed_action_identifiers_json=canonical([strict_json(v.encode()) for v in sorted({canonical({'native_action':r['action'],'source_native_identifiers':r['native_identifiers'],'native_action_fields':r.get('native_action')}) for r in rows})]),historical_interval=interval,
        missing_observation=OBSERVATIONS[req.dimension],documentation_dependencies=docs,
        verification_procedure='Independently inspect the cited native fields and official source documentation; establish the requested interval and source entitlement first. Preserve a new separately versioned permitted capture, revalidate hashes and locators, then replay qualification. No automatic collection or namespace substitution.',
        expected_artifact='Hash-bound primary source capture with original representation, native fields, request scope, capture timestamp, field locators, documentation version and an explicit account of unresolved proof obligations.',
        stop_condition='Stop without upgrading qualification when native context, interval, query support, entitlement, provenance or revision semantics cannot be established, or contradictory observations remain unresolved. Never infer absence or authorize financial arithmetic.')


def _history_records(run, diagnostic, input_indices):
    """Reconstruct source-local identity; supported definitive absence is narrow."""
    by_id={r['observation_id']:r for r in diagnostic['records'] if r['source']!='samgov'}
    index=defaultdict(list)
    for o in run.observations:
        a=o.scope_assessment
        if a.record:
            for n in a.record.native_identifiers:
                if n.namespace in ('id','atom_id'):
                    index[(n.source,n.namespace,n.value)].append(o)
    records=[]
    for o in run.observations:
        a=o.scope_assessment; d=by_id[o.history_observation_id]
        parent=assess_parent(a) # Variant content is a revision question, not by itself parent contradiction.
        native={f:getattr(a.observed,f).value for f in FIELDS}
        peers={p.history_observation_id:p for n in a.record.native_identifiers if n.namespace in ('id','atom_id')
               for p in index[(n.source,n.namespace,n.value)]} if a.record else {}
        reused=any(tuple(getattr(p.scope_assessment.observed,f).value for f in FIELDS)!=tuple(native[f] for f in FIELDS) for p in peers.values())
        context={'namespace':a.evidence.reference.source,'piid':native['piid'],'agency':native['agency'],
                 'parent_piid':native['parent_piid'],'parent_agency':native['parent_agency'],
                 'parent_absence_rule':parent.rule_version if parent.status is ParentStatus.NONE else None}
        complete=all(native[f] is not None for f in ('piid','agency')) and (parent.status is ParentStatus.NONE or all(native[f] is not None for f in ('parent_piid','parent_agency')))
        if not complete:
            context['unresolved_occurrence']=o.history_observation_id
        action=(native['modification'],native['transaction'])
        records.append({'source':a.evidence.reference.source,'id':o.history_observation_id,'context':context,
            'action':list(action) if all(v is not None for v in action) else None,'native_identifiers':[n.to_dict() for n in a.record.native_identifiers] if a.record else [],
            'instrument':parent.instrument_type,'contract_kind':'definitive_contract' if parent.instrument_type=='D' and parent.status is ParentStatus.NONE else 'delivery_order' if parent.instrument_type=='C' and parent.status is ParentStatus.VERIFIED else 'unclassified_native_instrument',
            'parent':parent.to_dict(),'content_sha256':a.content_sha256,'citation':a.evidence.to_dict(),
            'diagnostic_gaps':d['gaps'], 'counterpart_citations':sorted(v['observation_id'] for v in diagnostic['records'] if v['source'] not in (d['source'],'samgov') and v['scope_status']=='verified_in_scope' and v.get('diagnostic_context_status')!='conflicting' and d['action_key'] is not None and v['action_key']==d['action_key']),
            'identity_conflict':reused or any(f.result=='conflict' for f in a.comparisons if f.name in ('piid','agency','modification','transaction')) or d['diagnostic_context_status']=='conflicting',
            'reused_native_identifier':reused,'reused_identifier_peer_ids':sorted(k for k,p in peers.items() if tuple(getattr(p.scope_assessment.observed,f).value for f in FIELDS)!=tuple(native[f] for f in FIELDS)),
            'parent_context_conflict':any(f.result=='conflict' for f in a.comparisons if f.name.startswith('parent_')),
            'input_index':input_indices[o.input_manifest_sha256], 'identity_observed':a.supported and all(native[f] is not None for f in ('piid','agency','modification','transaction')),
            'retrieved_at_utc':o.freshness.retrieved_at_utc,'retrieval_sequence':o.retrieval_sequence,
            'temporal_fields':[f.to_dict() for f in o.freshness.temporal_fields],
            'money':[m.observation.to_dict() for m in o.money], 'input_manifest_sha256':o.input_manifest_sha256})
    return records


def _sam_records(diagnostic, typed_records):
    by_claim={r['observation_id']:r for r in diagnostic['records'] if r['source']=='samgov'}
    records=[]
    for input_index,native in typed_records:
        r=by_claim[native.claim_id]
        inventory=diagnostic['inputs'][input_index]['inventory_sha256']
        context={'namespace':'samgov','award':r['native_award']}
        occurrence='sam-history-occurrence:v1:'+digest({'inventory':inventory,'claim':native.claim_id})
        if any(r['native_award'].get(f) is None for f in ('piid','identity_subtier','parent_piid','parent_subtier','award_class','instrument_type')):
            context['unresolved_occurrence']=occurrence
        action=[native.action.modification,native.action.transaction]
        records.append({'source':'samgov','id':occurrence,'original_claim_id':native.claim_id,'input_index':input_index,
            'context':context,'action':action if all(v is not None for v in action) else None,
            'native_action':r['native_action'],'request_json':native.citation.evidence.artifact.request_json,'native_identifiers':[],'contract_kind':'unclassified_native_instrument',
            'parent':{'status':r['parent_status']},'counterpart_citations':[],'citation':r['citation'],'diagnostic_gaps':r['gaps'],
            'identity_conflict':r['scope_status']=='verified_out_of_scope','identity_observed':r['scope_status']=='verified_in_scope',
            'reused_native_identifier':False,'reused_identifier_peer_ids':[],'parent_context_conflict':r['parent_status']==ParentStatus.CONFLICT.value,
            'money':[],'temporal_fields':[],'content_sha256':native.content_sha256,
            'retrieved_at_utc':native.citation.evidence.artifact.retrieved_at_utc,'retrieval_sequence':None})
    return records


def _qualify(source, rows, context, pages, interval):
    Q=QualificationStatus; citations=tuple(sorted({r['id'] for r in rows}|{p for r in rows for p in r['reused_identifier_peer_ids']})); req=[]
    def add(d,status,*reasons): req.append(requirement(d,status,reasons,citations))
    add('native_identity',Q.CONFLICTING if any(r['identity_conflict'] for r in rows) else Q.QUALIFIED if all(r['identity_observed'] for r in rows) else Q.INSUFFICIENT,
        'conflicting_native_bindings' if any(r['identity_conflict'] for r in rows) else 'observed_source_native_components_only_not_cross_source_certification' if all(r['identity_observed'] for r in rows) else 'native_action_or_award_context_missing')
    parents={r['parent']['status'] for r in rows}
    parent_conflict=ParentStatus.CONFLICT.value in parents or any(r['parent_context_conflict'] for r in rows)
    add('parent_identity',Q.CONFLICTING if parent_conflict else Q.QUALIFIED if parents=={ParentStatus.NONE.value} else Q.INSUFFICIENT,
        'contradictory_parent_or_instrument' if parent_conflict else 'source_specific_definitive_no_parent_rule' if parents=={ParentStatus.NONE.value} else 'parent_award_primary_record_not_observed' if parents=={ParentStatus.VERIFIED.value} else 'parent_applicability_or_pair_unknown')
    page_issues={i for p in pages for i in p['issues']}
    add('source_completeness',Q.CONFLICTING if page_issues & {'contradictory_successful_page_observations','observations_after_terminal_page','contradictory_sam_pagination_metadata'} else Q.INSUFFICIENT,
        *(sorted(page_issues) or ['bounded_terminal_chain_not_history_or_query_recall_proof']), 'authoritative_history_interval_and_source_coverage_missing', *(['requested_history_interval_unknown'] if interval.start_date is None else []))
    add('revision_completeness',Q.INSUFFICIENT,'no_authoritative_correction_deletion_or_revision_lineage','modification_sequence_gaps_not_inferred')
    selected=[m for r in rows for m in r['money'] if m['original_field']==(USA_ACTION if source=='usaspending' else FPDS_ACTION)]
    complete=all(any(m['original_field']==(USA_ACTION if source=='usaspending' else FPDS_ACTION) and m['value']['raw_kind']!='missing' for m in r['money']) for r in rows)
    semantics=complete and all(m['semantics']['documented'] and m['semantics']['basis']==AmountBasis.INCREMENTAL.value and m['semantics']['scope']==FinancialScope.ACTION.value for m in selected)
    add('monetary_semantics',Q.NOT_EVALUATED if source=='samgov' else Q.QUALIFIED if semantics else Q.INSUFFICIENT,
        'sam_monetary_mapping_not_validated' if source=='samgov' else 'observed_incremental_action_obligation_fields_only' if semantics else 'missing_supported_action_obligation_field_no_award_total_substitution')
    date_variants=defaultdict(set)
    for r in rows:
        if r['action'] is not None:
            for m in r['money']:
                if m['original_field']==(USA_ACTION if source=='usaspending' else FPDS_ACTION) and m['action_date'] is not None:
                    date_variants[tuple(r['action'])].add(m['action_date'])
    date_conflict=any(len(v)>1 for v in date_variants.values())
    add('as_of_alignment',Q.CONFLICTING if date_conflict else Q.INSUFFICIENT,'no_common_native_revision_or_asof_certificate',
        *(['same_native_action_signed_date_variants_revision_unresolved'] if date_conflict else []),
        *(['signed_action_date_missing_or_unsupported_no_effective_date_substitution'] if source!='samgov' and (not selected or any(m['action_date'] is None for m in selected)) else []),
        *(['requested_asof_unknown'] if interval.as_of_date is None else []))
    from .financial_models import FinancialObservation
    money=[FinancialObservation.from_dict(m) for m in selected]
    variants=defaultdict(set)
    for r in rows:
        if r['action'] is not None:
            for m in r['money']:
                if m['original_field']==(USA_ACTION if source=='usaspending' else FPDS_ACTION) and m['value']['normalized'] is not None:
                    variants[tuple(r['action'])].add(m['value']['normalized'])
    conflicting=any(m.declared_currency_raw not in (None,'USD','unsupported_amount_attributes','unsupported_currency_element') for m in money) or any(len(v)>1 for v in variants.values())
    valid=complete and all(m.value.state is NumericState.VALID and has_cent_precision(m.value) and m.currency=='USD' for m in money)
    add('currency_amount',Q.NOT_EVALUATED if source=='samgov' else Q.CONFLICTING if conflicting else Q.QUALIFIED if valid else Q.INSUFFICIENT,
        'sam_currency_amount_mapping_not_validated' if source=='samgov' else 'variant_action_values_or_currency_require_revision_resolution' if conflicting else 'exact_supported_observed_values_only_no_total' if valid else 'missing_invalid_or_unsupported_amount_currency_or_precision')
    counterparts=all(r['counterpart_citations'] for r in rows)
    req.append(requirement('counterpart_coverage',Q.NOT_EVALUATED if source=='samgov' else Q.QUALIFIED if counterparts else Q.INSUFFICIENT,
        ['sam_cross_source_mapping_not_verified' if source=='samgov' else 'exact_native_context_counterparts_observed_not_revision_aligned' if counterparts else 'counterpart_not_observed_not_proven_absent'],
        citations+tuple(c for r in rows for c in r['counterpart_citations'])))
    add('provenance_integrity',Q.QUALIFIED,'replayed_local_capture_integrity_not_external_source_authentication')
    add('freshness',Q.INSUFFICIENT,'retrieval_or_declared_update_not_freshness_certificate')
    return ContractQualification(contract_id='qualified-contract:v1:'+digest({'source':source,'native_context':context}),source=source,
        native_context_json=canonical(context),occurrence_ids=tuple(sorted(r['id'] for r in rows)),requirements=tuple(req),status=aggregate(req))


def project_contract(q, rows, interval):
    actions=defaultdict(list)
    for r in rows:
        actions[canonical(r['action']) if r['action'] is not None else canonical({'unresolved_occurrence':r['id']})].append(r)
    action_groups=[{'native_action':strict_json(k.encode()),'occurrence_ids':sorted(r['id'] for r in values),
        'distinct_content_hashes':sorted({r['content_sha256'] for r in values if r['content_sha256'] is not None}),
        'relationship':'variant_content_revision_unknown' if len({r['content_sha256'] for r in values})>1 else 'same_observed_content_not_revision_certificate',
        'occurrence_count':len(values)} for k,values in sorted(actions.items())]
    return {'qualification':q.to_dict(),'contract_kinds':sorted({r['contract_kind'] for r in rows}),
        'actions':action_groups,'observed_occurrences':sorted(rows,key=lambda r:r['id']),
        'historical_order':{'basis':'retrieval_timestamp_then_local_sequence_not_action_or_revision_order',
            'occurrence_ids':[r['id'] for r in sorted(rows,key=lambda r:(r['retrieved_at_utc'] is None,datetime.fromisoformat(r['retrieved_at_utc'].replace('Z','+00:00')).astimezone(timezone.utc) if r['retrieved_at_utc'] is not None else datetime.max.replace(tzinfo=timezone.utc),r['retrieval_sequence'] or 0,r['id']))],
            'authoritative_revision_order':None,'missing_modifications_inferred':False},
        'historical_interval':interval.to_dict(),'parent_award_existence':'not_applicable_under_source_specific_no_parent_rule' if all(r['parent']['status']==ParentStatus.NONE.value for r in rows) else 'not_established_by_child_reference',
        'limitations':['Source-local observed contract only; no cross-source namespace union.',
            'Different content may be a correction or revision; no supersession winner is inferred.',
            'Observed chronology and modification labels do not establish a complete amendment sequence.']}


def project_triage(contracts, plans):
    triage=[]
    for contract in contracts:
        q=ContractQualification.from_dict(contract['qualification'])
        for req in q.requirements:
            if req.status is QualificationStatus.QUALIFIED: continue
            related=[p['plan_id'] for p in plans if p['contract_id']==q.contract_id and p['requirement']['dimension']==req.dimension]
            entry={'category':CATEGORY[req.dimension].value,'contract_id':q.contract_id,'source':q.source,
                'requirement':req.to_dict(),'resolution_plan_ids':related}
            triage.append(entry)
            if req.status is QualificationStatus.CONFLICTING:
                triage.append({**entry,'category':GapCategory.CONFLICT.value})
    return sorted(triage,key=canonical)


def relevant_pages(source, rows, pagination):
    indices={r.get('input_index') for r in rows}
    requests={r.get('request_json') for r in rows}
    return [p for run in pagination for p in run['sources'] if run['input_index'] in indices and p['source']==source
            and (source!='samgov' or requests.intersection(p['request_jsons']))]


def sam_pagination(diagnostic, collection_count):
    result=[]
    if not diagnostic['sam_assessment']: return result
    for i,capture in enumerate(diagnostic['sam_assessment']['captures']):
        pages=[]
        for subject in capture['pagination']:
            a=subject['assessment'];issues=set(a['issues'])
            if a['interpretation']=='contradictory_response_metadata': issues.add('contradictory_sam_pagination_metadata')
            pages.append({'source':'samgov','issues':sorted(issues),'interpretation':a['interpretation'],
                'transaction_history_complete':'unknown','source_wide_complete':'unknown',
                'request_jsons':sorted({o['submitted_parameters_json'] for o in a['observations']}),
                'evidence':{'capture_inventory_sha256':capture['inventory_sha256'],'subject_index':subject['subject_index'],
                            'pagination_observations':a['observations']},
                'semantic_boundary':'bounded_hypotheses_not_API_contract_or_financial_authorization'})
        result.append({'input_index':collection_count+i,'sources':pages})
    return result


def qualify(collections=(), requested=None, *, sam_captures=(), interval=None):
    """Only preserved captures enter the engine; C9 serialized claims are not trusted."""
    interval=HistoricalInterval() if interval is None else interval
    if not isinstance(interval,HistoricalInterval): raise EvidenceError('typed_historical_interval_required')
    collections=tuple(collections);sam_captures=tuple(sam_captures)
    # C9 enforces limits/profiles, metadata hashes and exact native request scope.
    paths=collections+sam_captures
    if len(collections)>8 or len(sam_captures)>3 or not paths: raise EvidenceError('bounded_qualification_inputs_required')
    before=[{n:s.byte_sha256 for n,s in snapshot(p).items()} for p in paths]
    diagnostic=diagnose(collections,requested,sam_captures=sam_captures)
    from .evidence_ingestion import inspect_directory
    input_indices={inspect_directory(p).substantive_sha256:i for i,p in enumerate(collections)}
    records=_history_records(reconstruct(collections,requested),diagnostic,input_indices) if collections else []
    from .sam_semantics_reporting import capture_report
    typed_sam=[(len(collections)+i,r) for i,p in enumerate(sam_captures) for r in capture_report(p)[1]]
    records.extend(_sam_records(diagnostic,typed_sam)); groups=defaultdict(list)
    for r in records: groups[(r['source'],canonical(r['context']))].append(r)
    contracts=[];plans=[]
    pagination=diagnostic['pagination']+sam_pagination(diagnostic,len(collections))
    for (source,text),rows in sorted(groups.items()):
        pages=relevant_pages(source,rows,pagination)
        q=_qualify(source,rows,strict_json(text.encode()),pages,interval)
        contracts.append(project_contract(q,rows,interval))
        for req in q.requirements:
            if req.status is not QualificationStatus.QUALIFIED:
                plan=resolution(q,req,interval,rows);plans.append({'plan_id':plan.plan_id,**plan.to_dict()})
    triage=project_triage(contracts,plans)
    for path,manifest in zip(paths,before):
        if {n:s.byte_sha256 for n,s in snapshot(path).items()}!=manifest: raise EvidenceError('qualification_source_changed')
    return {'schema_type':'ContractHistoryQualificationReport','schema_version':1,'rule_version':RULE,
        'requested_scope':requested.to_dict() if requested is not None else None,'requested_interval':interval.to_dict(),
        'diagnostic_sha256':digest(diagnostic),'inputs':diagnostic['inputs'],'profile':diagnostic['profile'],
        'contracts':contracts,'resolution_plans':sorted(plans,key=lambda p:p['plan_id']),
        'gap_triage':sorted(triage,key=canonical),'pagination_evidence':pagination,
        'unavailable_artifact_issues':diagnostic['artifact_issues'],
        'sam_capture_limitations':diagnostic['sam_assessment']['limitations'] if diagnostic['sam_assessment'] else [],
        'sam_capture_assessments':[{k:c[k] for k in ('state','inventory_sha256','profile','pagination','blockers')} for c in diagnostic['sam_assessment']['captures']] if diagnostic['sam_assessment'] else [],
        'qualification_authorizes_arithmetic':False,'financial_eligibility_changed':False,'production_readiness_changed':False,
        'new_collection_enabled':False,'real_participant_operations_enabled':False,
        'interpretation':'Evidence quality for narrowly scoped future analysis; never an allegation or financial authorization.'}
