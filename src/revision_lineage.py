"""C13 deterministic source-bound observation graph; never a revision winner."""
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from itertools import combinations

from .evidence import Schema, _hash, _text
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .history_models import temporal_parse

RULE='historical-lineage-v1'
FACETS=('award_identity','parent_identity','pagination','modification_coverage','historical_interval','correction_lineage','freshness','monetary_semantics','provenance_integrity')
NATIVE=('piid','agency','parent_piid','parent_agency','modification','transaction')


class CoverageState(str,Enum):
    COMPLETE='OBSERVED_COMPLETE_FOR_DEFINED_SCOPE'
    PARTIAL='PARTIALLY_OBSERVED'
    CONFLICT='CONFLICTING_EVIDENCE'
    INSUFFICIENT='INSUFFICIENT_EVIDENCE'
    NOT_EVALUATED='NOT_EVALUATED'


class RelationKind(str,Enum):
    DUPLICATE='same_source_same_native_action_same_observed_content'
    VARIANT='same_source_same_native_action_competing_content'
    REUSED='same_source_native_identifier_reused_across_contexts'
    DATE_ORDER='action_date_before_not_revision_precedence'
    CROSS_SOURCE='existing_USA_FPDS_exact_native_components_only'


@dataclass(frozen=True,kw_only=True)
class LineageObservation(Schema):
    source:str
    profile:str
    original_occurrence_id:str
    native_context_json:str
    native_identifiers_json:str
    native_action_id:str|None
    action_date:str|None
    update_metadata_json:str
    monetary_fields_json:str
    citation_json:str
    provenance_sha256:str
    content_sha256:str
    parent_assertion_basis:str
    identity_supported:bool
    outside_requested_context:bool
    issues:tuple[str,...]=()
    existing_native_scope_verified:bool=False

    @property
    def node_id(self):return 'revision-node:v1:'+digest(self.to_dict())

    def validate(self):
        if self.source not in ('usaspending','fpds','samgov') or self.profile not in ('live','synthetic'):raise ValueError('source_profile_required')
        _text(self.original_occurrence_id,'original occurrence')
        if len(self.original_occurrence_id)>256 or self.native_action_id is not None and len(self.native_action_id)>256:raise ValueError('bounded_native_and_constructed_identifiers_required')
        for name in ('provenance_sha256','content_sha256'):_hash(getattr(self,name))
        for name,kind in (('native_context_json',dict),('native_identifiers_json',list),('update_metadata_json',list),('monetary_fields_json',list),('citation_json',dict)):
            raw=getattr(self,name);v=strict_json(raw.encode())
            if type(v) is not kind or canonical(v)!=raw or len(raw)>131072:raise ValueError('bounded_canonical_source_fields_required')
        citation=strict_json(self.citation_json.encode())
        if self.provenance_sha256!=digest(citation):raise ValueError('citation_provenance_digest_conflict')
        ids=strict_json(self.native_identifiers_json.encode())
        if any(type(n) is not dict or n.get('source')!=self.source or type(n.get('value')) is not str or not n['value'].strip() or len(n['value'])>256 for n in ids):raise ValueError('source_native_identifiers_cannot_change_namespaces')
        if self.source=='samgov' and self.native_action_id is not None:raise ValueError('SAM_immutable_action_identifier_not_validated')
        context=strict_json(self.native_context_json.encode())
        if set(context)!=set(NATIVE) or any(v is not None and (type(v) is not str or not v.strip() or len(v)>256 or any(ord(c)<32 or ord(c)==127 for c in v)) for v in context.values()):raise ValueError('literal_source_native_components_required')
        if self.native_action_id is not None:_text(self.native_action_id,'native action')
        if self.action_date is not None and (len(self.action_date)!=10 or temporal_parse(self.action_date)!=self.action_date):raise ValueError('supported_ISO_action_date_required')
        if self.parent_assertion_basis != {'usaspending':'encoded_USA_native_transaction_components','fpds':'direct_FPDS_referenced_IDV_fields','samgov':'direct_SAM_contractId_fields'}[self.source]:raise ValueError('source_specific_parent_assertion_required')
        if self.issues!=tuple(sorted(set(self.issues))):raise ValueError('canonical_issues_required')
        if self.identity_supported and not all(context[k] is not None for k in ('piid','agency','modification','transaction')):raise ValueError('supported_action_requires_native_components')


@dataclass(frozen=True,kw_only=True)
class LineageRelation(Schema):
    left:str
    right:str
    kind:RelationKind
    rationale:str
    revision_precedence_established:bool=False
    financial_comparison_authorized:bool=False

    def validate(self):
        if self.left==self.right or any(not n.startswith('revision-node:v1:') for n in (self.left,self.right)):raise ValueError('distinct_observation_nodes_required')
        if self.revision_precedence_established is not False or self.financial_comparison_authorized is not False:raise ValueError('no_revision_or_financial_certificate_supported')
        _text(self.rationale,'relation rationale')


@dataclass(frozen=True,kw_only=True)
class HistoryFacet(Schema):
    dimension:str
    status:CoverageState
    defined_scope:str
    reasons:tuple[str,...]
    node_ids:tuple[str,...]
    financial_comparison_authorized:bool=False

    def validate(self):
        if self.dimension not in FACETS or self.financial_comparison_authorized is not False:raise ValueError('independent_history_dimension_required')
        if self.status is CoverageState.COMPLETE and self.dimension not in ('award_identity','pagination','provenance_integrity'):raise ValueError('unsupported_historical_completeness_certificate')
        if not self.reasons or self.reasons!=tuple(sorted(set(self.reasons))) or self.node_ids!=tuple(sorted(set(self.node_ids))):raise ValueError('explicit_canonical_proof_required')
        if self.status is CoverageState.COMPLETE and (not self.node_ids or self.defined_scope!='finite_revalidated_observations_not_universal_history'):raise ValueError('bounded_complete_claim_requires_citations')


def native(node):return strict_json(node.native_context_json.encode())


def action_key(node,*,cross=False):
    c=native(node)
    if not node.identity_supported or node.outside_requested_context or not all(c[k] is not None for k in NATIVE):return None
    if cross and (node.source=='samgov' or not node.existing_native_scope_verified):return None
    return tuple(c[k] for k in NATIVE)


def _money_signature(node):
    # Equality/variation of original reported values only. Never subtract, sum,
    # round, substitute award totals, choose revisions or compare currencies.
    out=[]
    for m in strict_json(node.monetary_fields_json.encode()):
        if 'original_field' in m:
            out.append({k:m.get(k) for k in ('original_field','value','semantics','action_date_raw','declared_currency_raw')})
        else:out.append(m)
    return canonical(sorted(out,key=canonical))


def graph(observations):
    nodes=tuple(observations)
    if any(not isinstance(n,LineageObservation) for n in nodes) or len(nodes)>1000 or sum(len(n.to_json()) for n in nodes)>16*1024*1024:raise EvidenceError('bounded_typed_lineage_nodes_required')
    byid={n.node_id:n for n in nodes}
    if len(byid)!=len(nodes):raise EvidenceError('duplicate_occurrence_is_not_independent_evidence')
    if len({n.profile for n in nodes})>1:raise EvidenceError('synthetic_and_live_lineage_must_not_mix')
    pairs=set();identifiers=defaultdict(list);actions=defaultdict(list);dates=defaultdict(list)
    for n in nodes:
        if n.native_action_id is not None:identifiers[(n.source,n.native_action_id)].append(n.node_id)
        key=action_key(n,cross=True)
        if key is not None:actions[key].append(n.node_id)
        if action_key(n) is not None and n.action_date is not None:
            c=native(n);dates[(n.source,tuple(c[k] for k in NATIVE[:4]))].append(n)
    for values in list(identifiers.values())+list(actions.values()):
        for a,b in combinations(sorted(values),2):
            if len(pairs)>=10000 and (a,b) not in pairs:raise EvidenceError('lineage_candidate_work_limit')
            pairs.add((a,b))
    relations=[];ambiguities=[];cross=[]
    def edge(a,b,kind,reason):
        if len(relations)>=10000:raise EvidenceError('lineage_relation_limit')
        relations.append(LineageRelation(left=a.node_id,right=b.node_id,kind=kind,rationale=reason).to_dict())
    for a,b in sorted(pairs):
        a,b=byid[a],byid[b];ka,kb=action_key(a),action_key(b)
        if a.source==b.source:
            same_native=a.native_action_id is not None and a.native_action_id==b.native_action_id
            if same_native and a.native_context_json!=b.native_context_json:
                edge(a,b,RelationKind.REUSED,'Competing parent/action contexts for one source identifier; correction or reused identity is unresolved, not a historical parent transition.')
                ambiguities.append({'left':a.node_id,'right':b.node_id,'kind':'native_identifier_context_variants'})
            elif ka is not None and ka==kb or same_native:
                kind=RelationKind.DUPLICATE if a.content_sha256==b.content_sha256 and _money_signature(a)==_money_signature(b) else RelationKind.VARIANT
                edge(a,b,kind,'Retain both occurrences; changed content or update markers do not establish correction direction.')
                if kind is RelationKind.VARIANT:ambiguities.append({'left':a.node_id,'right':b.node_id,'kind':'competing_source_content','monetary_fields_differ':_money_signature(a)!=_money_signature(b),'update_metadata_differ':a.update_metadata_json!=b.update_metadata_json})
        elif {a.source,b.source}=={'usaspending','fpds'} and ka is not None and ka==kb:
            edge(a,b,RelationKind.CROSS_SOURCE,'Existing usa-fpds-v1 exact six-component association; no common reporting revision or independent lineage certificate.')
            cross.append({'left':a.node_id,'right':b.node_id,'mapping':'existing_usa-fpds-v1','native_components':list(ka),
                'action_date_relationship':'unknown' if a.action_date is None or b.action_date is None else 'consistent_observed_dates' if a.action_date==b.action_date else 'conflicting_observed_dates_revision_unresolved',
                'money_relationship':'not_compared_common_revision_and_financial_authorization_missing'})
    for values in dates.values():
        ordered=sorted(values,key=lambda n:(n.action_date,n.node_id))
        # Adjacent distinct dates establish only an observed display ordering;
        # ties and modifications never create a correction-precedence edge.
        groups=defaultdict(list)
        for n in ordered:groups[n.action_date].append(n)
        ds=sorted(groups)
        for left,right in zip(ds,ds[1:]):edge(groups[left][0],groups[right][0],RelationKind.DATE_ORDER,'ISO action date precedes another observed date; not revision precedence, gap proof or modification-number ordering.')
    parent_candidates=[];childgroups=defaultdict(list)
    for n in nodes:
        c=native(n)
        if n.identity_supported and not n.outside_requested_context:childgroups[(n.source,c['piid'],c['agency'])].append(n)
    for key,values in sorted(childgroups.items()):
        parents={tuple(native(n)[k] for k in ('parent_piid','parent_agency')) for n in values}
        if len(parents)>1:parent_candidates.append({'source':key[0],'child_piid':key[1],'child_agency':key[2],'candidate_node_ids':sorted(n.node_id for n in values),'status':'ambiguous_child_reuse_or_parent_variation_not_established_change','historical_transition_established':False})
    present={k:{byid[i].source for i in ids} for k,ids in actions.items()}
    missing=[{'node_id':n.node_id,'status':'unsupported_cross_source_mapping' if n.source=='samgov' or action_key(n,cross=True) is None else 'missing_observed_exact_counterpart_not_absence'} for n in nodes if n.source=='samgov' or action_key(n,cross=True) is None or present[action_key(n,cross=True)]!={'usaspending','fpds'}]
    return {'rule_version':RULE,'nodes':[{'node_id':n.node_id,**n.to_dict()} for n in sorted(nodes,key=lambda n:n.node_id)],
        'relations':sorted(relations,key=canonical),'competing_observations':sorted(ambiguities,key=canonical),
        'cross_source_observations':sorted(cross,key=canonical),'possible_parent_variations':parent_candidates,
        'counterpart_obligations':sorted(missing,key=canonical),'correction_winners':[],
        'missing_modifications':{'status':'not_inferred_no_authoritative_contiguous_sequence','identifiers':[]},
        'financial_comparison_authorized':False,'historical_completeness_certified':False}


def facets(nodes,*,pagination_verified=False,pagination_conflicting=False,interval_known=False):
    ids=tuple(sorted(n.node_id for n in nodes));supported=bool(nodes) and all(n.identity_supported and not n.outside_requested_context for n in nodes)
    states={
        'award_identity':(CoverageState.CONFLICT if any('within_record_native_component_conflict' in n.issues for n in nodes) else CoverageState.COMPLETE if supported else CoverageState.INSUFFICIENT,'source_native_observed_components_only_not_cross_source_identity_certification'),
        'parent_identity':(CoverageState.CONFLICT if any('within_record_parent_component_conflict' in n.issues for n in nodes) else CoverageState.PARTIAL if any(all(native(n)[k] is not None for k in ('parent_piid','parent_agency')) for n in nodes) else CoverageState.INSUFFICIENT,'record_assertions_and_current_parent_do_not_establish_historical_applicability_intervals'),
        'pagination':(CoverageState.CONFLICT if pagination_conflicting else CoverageState.COMPLETE if pagination_verified and supported else CoverageState.PARTIAL if nodes else CoverageState.INSUFFICIENT,'defined_observed_query_window_not_source_recall_or_transaction_history'),
        'modification_coverage':(CoverageState.PARTIAL if nodes else CoverageState.INSUFFICIENT,'observed_modifications_only_missing_identifiers_not_manufactured'),
        'historical_interval':(CoverageState.PARTIAL if interval_known and nodes else CoverageState.INSUFFICIENT,'requested_interval_not_certified_by_minimum_maximum_observed_dates'),
        'correction_lineage':(CoverageState.INSUFFICIENT,'updates_versions_old_identifiers_and_content_variants_do_not_establish_directed_replacement'),
        'freshness':(CoverageState.INSUFFICIENT,'no_authoritative_asof_or_publication_delay_certificate'),
        'monetary_semantics':(CoverageState.PARTIAL if any(strict_json(n.monetary_fields_json.encode()) for n in nodes) else CoverageState.INSUFFICIENT,'source_specific_fields_retained_no_aggregation_substitution_or_common_revision_authorization'),
        'provenance_integrity':(CoverageState.COMPLETE if nodes else CoverageState.INSUFFICIENT,'revalidated_local_primary_integrity_not_independent_upstream_authentication')}
    return [HistoryFacet(dimension=d,status=states[d][0],defined_scope='finite_revalidated_observations_not_universal_history',reasons=(states[d][1],),node_ids=ids).to_dict() for d in FACETS]
