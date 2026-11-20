"""Literal proof-dependency assessment; no confidence or financial scoring."""
from collections import Counter
from dataclasses import dataclass
from enum import Enum

from .evidence import Schema, _hash
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .history_qualification import ProofRequirement, QualificationStatus
from .source_verification import VerificationExperiment


class DependencyGroup(str, Enum):
    PARENT_PRIMARY = 'parent_primary_existence'
    PARENT_APPLICABILITY = 'historical_parent_applicability'
    CROSSWALK = 'source_native_crosswalk'
    REVISION = 'revision_correction_authority'
    HISTORY = 'history_completeness'
    FINANCIAL = 'financial_semantics'
    OTHER = 'other_unsupported_dependencies'


OUTSIDE = 'outside_requested_native_context_requires_explicit_reselection_not_source_contradiction'
PARENT = 'parent_award_primary_record_not_observed'
KNOWN = {OUTSIDE,PARENT,'parent_applicability_or_pair_unknown',
    'retrieval_or_declared_update_not_freshness_certificate','no_common_native_revision_or_asof_certificate',
    'requested_asof_unknown','authoritative_history_interval_and_source_coverage_missing',
    'requested_history_interval_unknown','modification_sequence_gaps_not_inferred',
    'no_authoritative_correction_deletion_or_revision_lineage','counterpart_not_observed_not_proven_absent',
    'bounded_terminal_chain_not_history_or_query_recall_proof','nonterminal_observed_chain',
    'native_action_or_award_context_missing','contradictory_components_within_native_record',
    'source_record_identifier_reused_across_contexts_revision_semantics_unverified',
    'missing_invalid_or_unsupported_amount_currency_or_precision',
    'variant_action_values_or_currency_require_revision_resolution',
    'missing_supported_action_obligation_field_no_award_total_substitution',
    'same_native_action_signed_date_variants_revision_unresolved',
    'signed_action_date_missing_or_unsupported_no_effective_date_substitution'}


def classification(requirement, dependencies, native):
    """An outside-context record is never relabeled a monetary/source anomaly."""
    reasons = set(requirement.reasons) | set(dependencies)
    dim = requirement.dimension
    if requirement.status is QualificationStatus.NOT_EVALUATED or OUTSIDE in reasons:
        return DependencyGroup.OTHER, 'explicit_reselection_not_a_discrepancy', 'EXPLICIT_RESELECTION_REQUIRED'
    if reasons-set(KNOWN):
        return DependencyGroup.OTHER, 'unrecognized_dependency_preserved', 'UNSUPPORTED_DEPENDENCY'
    if dim=='parent_identity' and reasons=={PARENT}:
        complete = all(type(native.get(k)) is str and native[k] for k in ('piid','agency','parent_piid','parent_agency'))
        if not complete:
            path = 'EXACT_NATIVE_CHILD_PARENT_CONTEXT_REQUIRED'
        elif native.get('namespace')=='usaspending':
            path = 'PUBLIC_USA_PLAN_REQUIRES_EXACT_CONTEXT_ACCESS_TEST'
        else:
            path = 'SOURCE_NATIVE_PARENT_ADAPTER_OR_CROSSWALK_VALIDATION_REQUIRED'
        return DependencyGroup.PARENT_PRIMARY, 'parent_primary_not_observed', path
    if dim=='parent_identity' and 'parent_applicability_or_pair_unknown' in reasons:
        return DependencyGroup.PARENT_APPLICABILITY, 'parent_pair_or_applicability_unknown', 'NATIVE_PARENT_PAIR_AND_AUTHORITATIVE_APPLICABILITY_REQUIRED'
    if dim in ('revision_completeness','as_of_alignment'):
        return DependencyGroup.REVISION, 'revision_or_asof_certificate_missing', 'EXPLICIT_SCOPE_AND_AUTHORITATIVE_REVISION_EVIDENCE_REQUIRED'
    if dim=='source_completeness':
        return DependencyGroup.HISTORY, 'defined_history_and_coverage_missing', 'DEFINED_INTERVAL_AND_SOURCE_COVERAGE_CERTIFICATE_REQUIRED'
    if dim=='native_identity':
        return DependencyGroup.CROSSWALK, 'native_identifier_conflict_or_missing', 'EXACT_SOURCE_NATIVE_COMPONENT_VALIDATION_REQUIRED'
    if dim=='counterpart_coverage':
        return DependencyGroup.CROSSWALK, 'counterpart_not_observed_not_proven_absent', 'EXACT_SOURCE_NATIVE_COUNTERPART_VALIDATION_REQUIRED'
    if dim in ('currency_amount','monetary_semantics'):
        return DependencyGroup.FINANCIAL, 'compatible_basis_currency_and_revision_missing', 'DOCUMENTED_COMPATIBLE_MONETARY_PROOF_REQUIRED'
    if dim=='freshness':
        return DependencyGroup.OTHER, 'retrieval_time_not_freshness_certificate', 'AUTHORITATIVE_FRESHNESS_CERTIFICATE_REQUIRED'
    return DependencyGroup.OTHER, 'unsupported_original_dependency', 'UNSUPPORTED_DEPENDENCY'


@dataclass(frozen=True, kw_only=True)
class RequirementDependency(Schema):
    original_plan_id: str
    original_case_sha256: str
    dimension: str
    evidence_profile: str
    original_requirement_json: str
    native_context_json: str
    missing_dependencies: tuple[str,...]
    group: DependencyGroup
    blocker: str
    acquisition_path: str
    financial_comparison_authorized: bool = False

    def validate(self):
        if not self.original_plan_id.startswith('evidence-resolution:v1:'):
            raise ValueError('original_requirement_identifier_required')
        _hash(self.original_plan_id.removeprefix('evidence-resolution:v1:'))
        _hash(self.original_case_sha256)
        req = ProofRequirement.from_dict(strict_json(self.original_requirement_json.encode()))
        native = strict_json(self.native_context_json.encode())
        if (canonical(req.to_dict())!=self.original_requirement_json or type(native) is not dict
                or canonical(native)!=self.native_context_json or req.dimension!=self.dimension
                or self.evidence_profile not in ('live','synthetic')
                or req.status is QualificationStatus.QUALIFIED or self.financial_comparison_authorized is not False
                or self.missing_dependencies!=tuple(sorted(set(self.missing_dependencies)))
                or not set(req.reasons)<=set(self.missing_dependencies)
                or (self.group,self.blocker,self.acquisition_path)!=classification(req,self.missing_dependencies,native)):
            raise ValueError('dependency_assessment_contradicts_original_proof')


def _candidate(value, row):
    p = value['plan']
    if (p['original_requirement_id']!=row.original_plan_id or p['original_case_sha256']!=row.original_case_sha256
            or canonical(p['original_requirement'])!=row.original_requirement_json
            or p['profile']!=row.evidence_profile or p['source_allowlist']!=['usaspending']
            or any(type(p[k]) is not int for k in ('maximum_requests','maximum_transaction_rows','maximum_response_bytes','retries'))
            or p['maximum_requests']!=5
            or p['maximum_transaction_rows']!=20 or p['maximum_response_bytes']!=1048576
            or p['retries']!=0 or p['redirects'] is not False or p['financial_comparison_authorized'] is not False
            or type(value['preserved_query_terminal']) is not bool
            or type(value['preserved_record_occurrences']) is not int or not 0<=value['preserved_record_occurrences']<=1000
            or not value['preserved_query_citations']):
        raise EvidenceError('candidate_plan_not_bound_to_original_requirement')
    experiment = VerificationExperiment.from_dict(p['experiment'])
    selected = next(s for s in experiment.queue.requests if s.request_id==experiment.request_id)
    native = strict_json(row.native_context_json.encode())
    if (selected.evidence_profile!=p['profile'] or selected.source!='usaspending'
            or selected.target_kind!='award_history'
            or strict_json(selected.native_context_json.encode())!={k:native.get(k) for k in ('piid','agency','parent_piid','parent_agency')}):
        raise EvidenceError('candidate_profile_conflict')
    return {'original_plan_id':row.original_plan_id,'original_case_sha256':row.original_case_sha256,
        'native_context':strict_json(row.native_context_json.encode()),'plan_sha256':digest(p),
        'source':'usaspending','access_status':'NOT_TESTED_CURRENT_CONTEXT',
        'preserved_query_terminal':value['preserved_query_terminal'],
        'preserved_record_occurrences':value['preserved_record_occurrences'],
        'preserved_query_citations':value['preserved_query_citations'],
        'preserved_query_contract_issues':value.get('preserved_query_contract_issues',[]),
        'bounded_same_budget_candidate':value['preserved_query_terminal'] and 0<value['preserved_record_occurrences']<=10,
        'next_action':'PREREGISTER_EXACT_BOUNDED_SCOPE_TEST' if value['preserved_query_terminal']
                      else 'VALIDATE_CHILD_PAGINATION_CONTRACT_AND_BUDGET_FIRST',
        'source_current_access_verified':False,'original_requirement_resolution_guaranteed':False,
        'financial_comparison_authorized':False}


def assess_dependencies(original_cases, remaining_ids, *, candidates=(), resolved_now=()):
    if (type(original_cases) not in (tuple,list) or not 1<=len(original_cases)<=24
            or type(remaining_ids) not in (tuple,list) or len(remaining_ids)>4000
            or len(set(remaining_ids))!=len(remaining_ids) or len(set(resolved_now))!=len(resolved_now)
            or not set(resolved_now)<=set(remaining_ids) or len(candidates)>24):
        raise EvidenceError('bounded_unique_original_dependency_set_required')
    wanted = set(remaining_ids); rows = {}
    if len({c['profile'] for c in original_cases})!=1:
        raise EvidenceError('mixed_dependency_evidence_profiles')
    for case in original_cases:
        for p in case['original_requirement_impacts']:
            key = p['original_plan_id']
            if key not in wanted:continue
            if key in rows:raise EvidenceError('duplicate_original_requirement_not_independent_proof')
            req = ProofRequirement.from_dict(p['original_requirement'])
            deps = tuple(sorted(set(req.reasons)|set(p['original_remaining_dependencies'])))
            group, blocker, path = classification(req,deps,p['native_context'])
            rows[key] = RequirementDependency(original_plan_id=key,original_case_sha256=case['original_case_sha256'],
                dimension=p['dimension'],evidence_profile=case['profile'],original_requirement_json=canonical(req.to_dict()),
                native_context_json=canonical(p['native_context']),missing_dependencies=deps,
                group=group,blocker=blocker,acquisition_path=path)
    if set(rows)!=wanted:raise EvidenceError('unresolved_IDs_not_exactly_covered_by_primary_requirements')
    options=[];seen=set()
    for candidate in candidates:
        key=candidate['plan']['original_requirement_id'];row=rows.get(key)
        if key in seen or row is None or row.group is not DependencyGroup.PARENT_PRIMARY or row.acquisition_path!='PUBLIC_USA_PLAN_REQUIRES_EXACT_CONTEXT_ACCESS_TEST':
            raise EvidenceError('unsupported_or_duplicate_acquisition_candidate')
        seen.add(key);options.append(_candidate(candidate,row))
    options.sort(key=lambda c:(not c['bounded_same_budget_candidate'],c['preserved_record_occurrences'],c['original_case_sha256'],c['original_plan_id']))
    shortlist = [c for c in options if c['original_plan_id'] not in resolved_now][:2]
    counts=Counter(r.group.value for r in rows.values());status=Counter(strict_json(r.original_requirement_json.encode())['status'] for r in rows.values())
    dimensions={dim:dict(sorted(Counter(strict_json(r.original_requirement_json.encode())['status']
        for r in rows.values() if r.dimension==dim).items())) for dim in sorted({r.dimension for r in rows.values()})}
    return {'schema_type':'EvidenceDependencyAssessment','schema_version':1,'rule_version':'literal-proof-dependencies-v1',
        'baseline_unresolved_count':len(wanted),'baseline_unresolved_IDs_sha256':digest(sorted(wanted)),
        'exclusive_group_counts':{g.value:counts[g.value] for g in DependencyGroup},
        'original_status_counts':dict(sorted(status.items())),
        'dimension_counts':dict(sorted(Counter(r.dimension for r in rows.values()).items())),
        'dimension_status_counts':dimensions,
        'not_evaluated_is_not_a_source_discrepancy':True,
        'zero_financial_dependency_count_is_not_financial_eligibility':True,
        'requirements':[rows[k].to_dict() for k in sorted(rows)],'candidate_plans':options,
        'next_acquisition_shortlist':shortlist,'resolved_in_current_phase':sorted(resolved_now),
        'current_remaining_ids':sorted(wanted-set(resolved_now)),
        'current_remaining_count':len(wanted-set(resolved_now)),
        'SAM_access':'REQUIRES_LEGITIMATE_CONFIGURED_AUTHORIZATION_NOT_READ_BY_OFFLINE_TOOL',
        'completeness':'TERMINAL_OBSERVATIONS_DO_NOT_CERTIFY_HISTORY_OR_COMMON_ASOF',
        'financial_comparison_authorized':False,'production_readiness_changed':False}
