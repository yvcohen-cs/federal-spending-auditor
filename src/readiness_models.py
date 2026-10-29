"""Readiness-v1 typed evidence and categorical decisions; never a risk score."""
from dataclasses import dataclass, field, MISSING
from enum import Enum

from .evidence import Schema, _hash, _text, _timestamp, _url
from .evidence_io import digest, parts
from .matching_models import _ComputedIdentity, ordered
from .review_packet_models import EvidenceCitation

VERSION='readiness-protocol-v1'
DIMENSIONS=('operational_integrity','source_access_api_stability','query_precision','record_identity',
    'historical_coverage','revision_alignment','financial_comparability','evidence_provenance',
    'reproducibility','human_review_usability','security_bounded_collection','source_modernization')
CONTROLS=('approved_endpoints_only','no_credential_disclosure','bounded_pagination','no_source_evidence_mutation',
    'no_fabricated_identity','no_unsupported_financial_comparisons','no_silent_checkpoint_upgrades',
    'no_misleading_completeness','no_automatic_accusations','no_false_independent_corroboration')
CAUSES=('query_imprecision','identifier_mismatch','parent_context_ambiguity','missing_source_counterpart',
    'partial_source_coverage','unsupported_schema','revision_relationship_unknown','incompatible_financial_basis',
    'source_access_failure','stale_or_unverified_update_status','unverified_historical_completeness','evidence_integrity_failure')
MODES=('offline_reanalysis','bounded_research_30','validation_100','screening_500','screening_5000_plus')
FROZEN={
    'baseline_main_commit':'f0bc3e4fd22e403d5c92eb5e6215565075d00a03',
    'preregistration_implementation_sha256':'5105866093d4e9c039e3020af1a2f61ceb849404c29699a65fb0dea12791e312',
    'original_implementation_sha256':'c29ecb013ff8a62e097fafb91e52d1dddc1cbc060ecadb1ba4eb085cde7287c9',
    'frozen_sample_sha256':'a37d71044603966ce9124b93790ac99a0c0484f481175cab096defaffcbc6557',
    'frozen_inventory_sha256':'02b45a4c059b48a798689b842bef949a44b48996cba20da9fd3a7ee047fd0a1f',
    'frozen_pilot_plan_sha256':'e1e39590e9f8caa35522cd7ef6a80a584e669322601ba2ca34e68092fbff1af0'}
FINANCIAL_STATUSES=('exact_observed_agreement','unequal_comparable_observations','different_known_reporting_states',
    'revision_relationship_unknown','incompatible_financial_scope','insufficient_history','unsupported_semantics','scope_uncertainty')
AUDIT_UNITS={**{k:'selected_slots' for k in ('operational_slots','provenance_slots','collection_complete_slots','slots_with_actions','replay_consistent_slots')},
    'source_http_success':'preserved_HTTP_attempts','source_parsed_tasks':'expected_source_tasks','returned_occurrences':'enumerated_record_occurrences',
    **{k:'enumerated_record_occurrences' for k in ('scope_verified','scope_out','scope_ambiguous','scope_insufficient','scope_unsupported')},
    'eligible_action_identities':'distinct_native_keys_within_slot','modifications':'distinct_modification_strings_within_slot',
    'observed_modification_records':'distinct_source_record_contents_with_native_modification',
    **{k:'observed_record_pair_results' for k in ('revision_aligned','revision_unknown')},
    **{k:'input_source_assessments' for k in ('history_known_complete','history_unknown')},
    'financial_authorized':'revision_conditioned_record_pair_results',
    **{'financial_'+k:'observed_record_pair_results' for k in FINANCIAL_STATUSES},
    **{k:'record_occurrences' for k in ('freshness_supported','freshness_unknown')},
    'review_traceable':'record_occurrences_with_C6_citation_and_locator',
    'all_holdout_HTTP_success':'all_holdout_HTTP_requests_including_frame_and_discovery'}


class Result(str,Enum):
    PASS='PASS'
    CONDITIONAL='CONDITIONAL'
    FAIL='FAIL'
    UNKNOWN='UNKNOWN'
    NOT_APPLICABLE='NOT_APPLICABLE'


class Decision(str,Enum):
    GO='GO'
    CONDITIONAL_GO='CONDITIONAL GO'
    NO_GO='NO-GO'


@dataclass(frozen=True,kw_only=True)
class ReadinessProtocol(Schema):
    baseline_main_commit:str
    preregistration_implementation_sha256:str
    original_implementation_sha256:str
    frozen_sample_sha256:str
    frozen_inventory_sha256:str
    frozen_pilot_plan_sha256:str
    version:str=VERSION
    profile:str='frozen-live-pilot'
    holdout_award_limit:int=3
    holdout_frame_limit:int=6
    holdout_http_limit:int=10
    holdout_fiscal_year:int=2023
    holdout_award_type:str='D'
    holdout_selection:str='sorted_native_generated_id_excluding_frozen_cohort_no_replacements'
    holdout_stop:str='first_scope_conflict_unsupported_schema_unsafe_continuation_integrity_failure_or_source_error'
    dimension_rule:str='all_observed_requirements_or_explicit_conditional_unknown_no_weighting'
    mode_rule:str='offline_scoped_research_only_progressively_stricter_all_required_dimensions'
    hard_gate_rule:str='any_observed_violation_blocks_every_mode_unknown_never_passes_as_proof'

    def validate(self):
        import re
        if re.fullmatch('[0-9a-f]{40}',self.baseline_main_commit) is None: raise ValueError('exact base commit required')
        for v in (self.preregistration_implementation_sha256,self.original_implementation_sha256,self.frozen_sample_sha256,self.frozen_inventory_sha256,self.frozen_pilot_plan_sha256): _hash(v)
        defaults={k:f.default for k,f in type(self).__dataclass_fields__.items() if k not in ('schema_version','profile') and f.default is not MISSING}
        if any(getattr(self,k)!=v for k,v in defaults.items()) or self.profile not in ('frozen-live-pilot','synthetic-control'):
            raise ValueError('protocol v1 criteria are frozen; use a new protocol version')
        if self.profile=='frozen-live-pilot' and any(getattr(self,k)!=v for k,v in FROZEN.items()):
            raise ValueError('live protocol cohort/implementation lineage is preregistered')

    @property
    def protocol_sha256(self): return digest(self.to_dict())


@dataclass(frozen=True,kw_only=True)
class ReadinessEvidenceRef(_ComputedIdentity):
    _computed_name='evidence_id'
    logical_root:str
    relative_path:str
    sha256:str|None
    kind:str
    detail:str
    source_url:str|None=None
    citation:EvidenceCitation|None=None

    @property
    def evidence_id(self): return 'readiness-evidence:v1:'+digest(Schema.to_dict(self))

    def validate(self):
        parts(self.logical_root);parts(self.relative_path);_text(self.detail,'evidence detail');_url(self.source_url)
        if self.kind not in ('source_fact','derived_measurement','documentation','assumption','unknown','human_verification'):
            raise ValueError('explicit fact/measurement/assumption/unknown/review kind required')
        if self.sha256 is not None: _hash(self.sha256)
        elif self.kind in ('source_fact','derived_measurement'): raise ValueError('preserved or derived evidence requires digest')
        if self.citation is not None:
            e=self.citation.evidence
            if self.sha256!=e.artifact.sha256 or self.relative_path!=e.artifact.relative_path or self.source_url!=(e.reference.source_record_url or e.artifact.endpoint):
                raise ValueError('C6 citation must preserve actual source provenance')


@dataclass(frozen=True,kw_only=True)
class Measurement(Schema):
    name:str
    numerator:int|None
    denominator:int|None
    unit:str
    complete:bool=True

    def validate(self):
        _text(self.name,'measurement');_text(self.unit,'unit')
        if self.name not in DIMENSIONS+CONTROLS and (self.name not in AUDIT_UNITS or self.unit!=AUDIT_UNITS[self.name]):
            raise ValueError('unsupported measurement name/unit; definitions are versioned')
        if self.numerator is not None and self.numerator<0 or self.denominator is not None and self.denominator<0:
            raise ValueError('negative count')
        if self.numerator is not None and self.denominator is not None and self.numerator>self.denominator:
            raise ValueError('numerator exceeds declared denominator')
        if self.numerator is None and self.complete: raise ValueError('unknown observation cannot be complete')


@dataclass(frozen=True,kw_only=True)
class CauseOccurrence(Schema):
    subject_key:str
    unit:str
    codes:tuple[str,...]
    evidence_ids:tuple[str,...]
    interpretation:str='observed_contributors_not_proven_upstream_root_causality'

    def validate(self):
        _text(self.subject_key,'cause subject')
        if self.unit not in ('record_content','source_task','artifact','slot'): raise ValueError('explicit causal count unit required')
        if not self.codes or self.codes!=tuple(sorted(set(self.codes))) or any(c not in CAUSES for c in self.codes): raise ValueError('unknown/duplicate taxonomy code')
        if not self.evidence_ids or self.evidence_ids!=tuple(sorted(set(self.evidence_ids))): raise ValueError('cause evidence required')
        if self.interpretation!='observed_contributors_not_proven_upstream_root_causality': raise ValueError('unsupported causal assertion')


@dataclass(frozen=True,kw_only=True)
class SlotAudit(Schema):
    slot:int
    selected_native_id:str|None
    processed:bool
    measurements:tuple[Measurement,...]
    evidence:tuple[ReadinessEvidenceRef,...]
    causes:tuple[CauseOccurrence,...]
    violations:tuple[str,...]=()
    unknown_controls:tuple[str,...]=()
    replay_first_sha256:str|None=None
    replay_second_sha256:str|None=None
    semantic_sha256:str|None=None

    def validate(self):
        if not 0<=self.slot<100: raise ValueError('bounded slot required')
        if self.selected_native_id is not None:
            _text(self.selected_native_id,'preserved selected ID')
            if len(self.selected_native_id)>256: raise ValueError('bounded native selection')
        if self.measurements!=ordered(self.measurements) or len({m.name for m in self.measurements})!=len(self.measurements): raise ValueError('unique canonical measurements required')
        if self.evidence!=ordered(self.evidence) or self.causes!=ordered(self.causes): raise ValueError('canonical source references/causes required')
        refs={r.evidence_id for r in self.evidence}
        if any(set(c.evidence_ids)-refs for c in self.causes): raise ValueError('unregistered cause evidence')
        if len({(c.unit,c.subject_key) for c in self.causes})!=len(self.causes): raise ValueError('contributors must share one subject occurrence; no double counting')
        for values in (self.violations,self.unknown_controls):
            if values!=tuple(sorted(set(values))) or set(values)-set(CONTROLS): raise ValueError('unknown control code')
        for v in (self.replay_first_sha256,self.replay_second_sha256,self.semantic_sha256):
            if v is not None: _hash(v)
        if self.processed and (not self.evidence or self.replay_first_sha256 is None or self.replay_second_sha256 is None or self.semantic_sha256 is None):
            raise ValueError('processed slot requires preserved evidence and two replays')
        if self.processed:
            values={m.name:m for m in self.measurements}
            if set(values)!=set(AUDIT_UNITS)-{'all_holdout_HTTP_success'}: raise ValueError('all versioned slot measurements must remain explicit')
            rows=values['returned_occurrences'].numerator
            names=('scope_verified','scope_out','scope_ambiguous','scope_insufficient','scope_unsupported')
            if any(values[n].denominator!=rows for n in names) or sum(values[n].numerator for n in names)!=rows:
                raise ValueError('scope counts must partition enumerated occurrences')
            pairs=values['financial_authorized'].denominator
            if any(values['financial_'+n].denominator!=pairs for n in FINANCIAL_STATUSES) or sum(values['financial_'+n].numerator for n in FINANCIAL_STATUSES)!=pairs:
                raise ValueError('financial statuses must partition observed pair results')
            if values['replay_consistent_slots'].numerator!=int(self.replay_first_sha256==self.replay_second_sha256):
                raise ValueError('replay count contradicts preserved digests')


@dataclass(frozen=True,kw_only=True)
class CohortAudit(Schema):
    role:str
    sample_sha256:str|None
    inventory_sha256:str|None
    source_plan_sha256:str|None
    original_implementation_sha256:str|None
    selected_count:int
    slots:tuple[SlotAudit,...]
    available:bool
    unchanged:bool
    profile:str
    limitations:tuple[str,...]
    auxiliary_measurements:tuple[Measurement,...]=()
    evidence:tuple[ReadinessEvidenceRef,...]=()
    auxiliary_causes:tuple[CauseOccurrence,...]=()

    def validate(self):
        if self.role not in ('frozen_pilot','holdout') or self.profile not in ('live','synthetic') or not 0<=self.selected_count<=30: raise ValueError('supported cohort role/profile/bounds required')
        for v in (self.sample_sha256,self.inventory_sha256,self.source_plan_sha256):
            if v is not None: _hash(v)
            elif self.available: raise ValueError('available cohort requires measured source hashes')
        if self.original_implementation_sha256 is not None: _hash(self.original_implementation_sha256)
        if self.slots!=tuple(sorted(self.slots,key=lambda s:s.slot)) or [s.slot for s in self.slots]!=list(range(self.selected_count)):
            raise ValueError('every selected slot must remain in the denominator')
        if not self.limitations: raise ValueError('cohort limitations required')
        if self.auxiliary_measurements!=ordered(self.auxiliary_measurements) or self.evidence!=ordered(self.evidence) or self.auxiliary_causes!=ordered(self.auxiliary_causes):
            raise ValueError('canonical cohort-level evidence required')
        if any(set(a.evidence_ids)-{r.evidence_id for r in self.evidence} for a in self.auxiliary_causes): raise ValueError('unregistered auxiliary cause evidence')


@dataclass(frozen=True,kw_only=True)
class GateResult(Schema):
    name:str
    result:Result
    numerator:int|None
    denominator:int|None
    unit:str
    rule:str
    rationale:str
    evidence_ids:tuple[str,...]
    limitations:tuple[str,...]

    def validate(self):
        if self.name not in DIMENSIONS+CONTROLS: raise ValueError('unknown dimension/control')
        Measurement(name=self.name,numerator=self.numerator,denominator=self.denominator,unit=self.unit,complete=self.numerator is not None)
        if not self.rule or not self.rationale or not self.limitations: raise ValueError('rule/rationale/limitations required')
        if self.result is Result.NOT_APPLICABLE and not self.rationale.startswith('mode_specific:'): raise ValueError('unknown is not not-applicable')


@dataclass(frozen=True,kw_only=True)
class ExpansionDecision(Schema):
    mode:str
    result:Decision
    required_dimensions:tuple[str,...]
    blockers:tuple[str,...]
    conditions:tuple[str,...]
    collection_permission:bool=False

    def validate(self):
        if self.mode not in MODES or self.collection_permission is not False: raise ValueError('mode assessment is never collection authorization')
        if set(self.required_dimensions)-set(DIMENSIONS): raise ValueError('unknown required dimension')
        if self.result is Decision.NO_GO and not self.blockers or self.result is Decision.CONDITIONAL_GO and not self.conditions: raise ValueError('explicit blockers/conditions required')


@dataclass(frozen=True,kw_only=True)
class ReadinessAssessment(Schema):
    protocol:ReadinessProtocol
    implementation_commit:str
    implementation_sha256:str
    cohorts:tuple[CohortAudit,...]
    dimensions:tuple[GateResult,...]
    hard_gates:tuple[GateResult,...]
    modes:tuple[ExpansionDecision,...]
    executed_at_utc:str|None=field(default=None,metadata={'execution':True})

    def validate(self):
        import re
        from .readiness_rules import conclusions
        _hash(self.implementation_sha256);_timestamp(self.executed_at_utc)
        if re.fullmatch('[0-9a-f]{40}',self.implementation_commit) is None: raise ValueError('exact implementation commit required')
        if [c.role for c in self.cohorts] not in (['frozen_pilot'],['frozen_pilot','holdout']): raise ValueError('distinct, canonical cohort roles required')
        if self.protocol.profile=='frozen-live-pilot':
            c=self.cohorts[0]
            if any(c.profile!='live' for c in self.cohorts): raise ValueError('synthetic evidence cannot certify a live readiness cohort')
            if c.profile!='live' or c.available and c.sample_sha256!=self.protocol.frozen_sample_sha256 or c.selected_count!=24:
                raise ValueError('frozen cohort identity cannot be replaced')
            if c.available and (c.inventory_sha256!=self.protocol.frozen_inventory_sha256 or c.source_plan_sha256!=self.protocol.frozen_pilot_plan_sha256):
                raise ValueError('frozen primary evidence inventory/plan changed')
        if any(c.role=='holdout' and c.selected_count>self.protocol.holdout_award_limit for c in self.cohorts):
            raise ValueError('readiness categories do not enlarge holdout limits')
        if (self.dimensions,self.hard_gates,self.modes)!=conclusions(self.cohorts): raise ValueError('readiness conclusions contradict deterministic gates')

    @property
    def substantive_sha256(self): return digest(self.to_dict(substantive=True))
