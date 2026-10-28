"""Deterministic, bounded history decisions. Amounts never establish revisions."""
from datetime import datetime
from .evidence_io import EvidenceError, digest
from .financial_models import USA_ACTION, FPDS_ACTION, AmountBasis, FinancialScope
from .financial_values import NumericState, exact_difference, has_cent_precision
from .history_models import Alignment, HistoricalStatus as S, RevisionAlignmentDecision, HistoricalFinancialComparison
from .matching_models import ordered
from .scope_models import FIELDS


def native_key(o):
    values=tuple(getattr(o.scope_assessment.observed,f).value for f in FIELDS)
    return values if all(v is not None for v in values) else None


def alignment(left,right):
    if not left.scope_assessment.supported or not right.scope_assessment.supported:
        return Alignment.UNSUPPORTED,'unsupported_source_identity_schema'
    if not left.eligible or not right.eligible or left.action_key is None or right.action_key is None:
        return Alignment.INSUFFICIENT,'verified_scope_and_complete_action_identity_required'
    if left.action_key!=right.action_key:
        return Alignment.DIFFERENT_ACTION,'exact_native_action_components_differ'
    if left.issues or right.issues:
        return Alignment.UNSUPPORTED,'unsupported_or_contradictory_temporal_financial_fields'
    if left.history_observation_id==right.history_observation_id and left!=right:
        return Alignment.UNSUPPORTED,'contradictory_same_occurrence_declarations'
    if left==right:
        return Alignment.SAME,'same_preserved_record_occurrence_only_not_cross_source_synchronization'
    a,b=left.revision.synthetic_control_revision,right.revision.synthetic_control_revision
    if a is not None and b is not None:
        return (Alignment.SAME,'fictional_history_control_v1_same_revision') if a==b else (Alignment.DIFFERENT_REVISION,'fictional_history_control_v1_different_revisions')
    if left.scope_assessment.evidence.reference.source==right.scope_assessment.evidence.reference.source:
        a={m.path:m for m in left.revision.update_markers if m.parsed is not None}
        b={m.path:m for m in right.revision.update_markers if m.parsed is not None}
        # Distinct declared update values do not identify a correction cause,
        # establish authoritative precedence, or certify equal monetary vintages.
        def distinct(x,y):
            if len(x.parsed)==10 or len(y.parsed)==10:
                return len(x.parsed)==len(y.parsed)==10 and x.parsed!=y.parsed
            x,y=datetime.fromisoformat(x.parsed),datetime.fromisoformat(y.parsed)
            if (x.utcoffset() is None)!=(y.utcoffset() is None): return False
            return x!=y
        if any(distinct(a[k],b[k]) for k in a.keys()&b.keys()):
            return Alignment.DIFFERENT_REVISION,'same_source_distinct_declared_update_markers_not_correction_causality'
    return Alignment.UNKNOWN,'no_positive_common_revision_evidence_retrieval_and_amounts_do_not_align'


def amount(o,field):
    return next((m.observation for m in o.money if m.observation.original_field==field),None)


def comparison_values(left,right,left_field,right_field,*,context_conflict=False):
    if not left.eligible or right is not None and not right.eligible:
        return S.SCOPE_UNCERTAIN,('verified_record_scope_required',),None
    if context_conflict:
        return S.HISTORY_INSUFFICIENT,('contradictory_same_source_action_revision_observations',),None
    if right is None:
        return S.HISTORY_INSUFFICIENT,('no_observed_eligible_action_counterpart_not_evidence_of_absence',),None
    state,_=alignment(left,right)
    if state is Alignment.UNSUPPORTED: return S.UNSUPPORTED,('unsupported_identity_or_temporal_semantics',),None
    if state in (Alignment.INSUFFICIENT,Alignment.DIFFERENT_ACTION): return S.HISTORY_INSUFFICIENT,('same_verified_action_required',),None
    a,b=amount(left,left_field),amount(right,right_field)
    if a is None or b is None: return S.UNSUPPORTED,('missing_supported_financial_observation',),None
    if not a.semantics.documented or not b.semantics.documented:
        return S.UNSUPPORTED,('unsupported_financial_field_semantics',),None
    if a.semantics!=b.semantics or a.semantics.basis is not AmountBasis.INCREMENTAL or a.semantics.scope is not FinancialScope.ACTION:
        return S.INCOMPATIBLE,('only_compatible_incremental_action_obligations_supported',),None
    if a.action_date is None or b.action_date is None or a.action_date!=b.action_date:
        return S.INCOMPATIBLE,('compatible_supported_signed_dates_required_no_effective_date_fallback',),None
    if a.currency is None or a.currency!=b.currency:
        return S.INCOMPATIBLE,('compatible_documented_currency_required',),None
    if not has_cent_precision(a.value) or not has_cent_precision(b.value):
        return S.UNSUPPORTED,('valid_cent_exact_values_required_no_rounding',),None
    if (state is Alignment.SAME and left.scope_assessment.evidence.reference.source==right.scope_assessment.evidence.reference.source
            and (left.scope_assessment.content_sha256!=right.scope_assessment.content_sha256 or a.value!=b.value)):
        return S.HISTORY_INSUFFICIENT,('contradictory_same_source_same_control_revision_values',),None
    if state is Alignment.DIFFERENT_REVISION: return S.REVISION_DIFFERENCE,('different_declared_reporting_states_not_an_amount_discrepancy',),None
    if state is not Alignment.SAME: return S.REVISION_UNKNOWN,('positive_revision_alignment_required_even_for_equal_amounts',),None
    delta=exact_difference(a.value.normalized,b.value.normalized)
    return (S.AGREEMENT if delta=='0' else S.UNEQUAL),('authorized_exact_observed_values_only_not_financial_correctness_or_misconduct',),delta


def compare(left,right,left_field=None,right_field=None,*,context_conflict=False):
    def field(o): return USA_ACTION if o.scope_assessment.evidence.reference.source=='usaspending' else FPDS_ACTION
    left_field=left_field or field(left);right_field=right_field or (field(right) if right else FPDS_ACTION)
    decision=None
    if right is not None:
        status,reason=alignment(left,right)
        decision=RevisionAlignmentDecision(left=left,right=right,status=status,reason=reason)
    status,reasons,delta=comparison_values(left,right,left_field,right_field,context_conflict=context_conflict)
    return HistoricalFinancialComparison(left=left,right=right,left_field=left_field,right_field=right_field,
        alignment=decision,status=status,reasons=reasons,difference_left_minus_right=delta,context_conflict=context_conflict)


def compare_observations(observations):
    if len(observations)>1000: raise EvidenceError('history_observation_limit')
    sizes={o.history_observation_id:len(o.to_json().encode()) for o in observations}
    if sum(sizes.values())>8*1024*1024: raise EvidenceError('history_observation_byte_limit')
    groups={};conflicts=set()
    for o in observations:
        key=native_key(o)
        if key is not None: groups.setdefault(key,[]).append(o)
    # A common synthetic revision cannot hide contradictory source versions.
    for values in groups.values():
        by_state={}
        for o in values:
            marker=o.revision.synthetic_control_revision
            if marker is not None:
                by_state.setdefault((o.scope_assessment.evidence.reference.source,marker),[]).append(o)
        for state in by_state.values():
            if len({digest({'content':o.scope_assessment.content_sha256,'money':[
                    {'field':m.observation.original_field,'value':m.observation.value.to_dict(),
                     'semantics':m.observation.semantics.to_dict(),'date':m.observation.action_date_raw,
                     'currency':m.observation.declared_currency_raw} for m in o.money]}) for o in state})>1:
                conflicts.update(o.history_observation_id for o in state)
    pairs=[];paired=set();work_bytes=0
    for values in groups.values():
        values=sorted(values,key=lambda o:(o.scope_assessment.evidence.reference.source!='usaspending',o.history_observation_id))
        for i,left in enumerate(values):
            for right in values[i+1:]:
                if len(pairs)>=10000: raise EvidenceError('history_comparison_work_limit')
                work_bytes+=3*(sizes[left.history_observation_id]+sizes[right.history_observation_id])+4096
                if work_bytes>16*1024*1024: raise EvidenceError('history_comparison_byte_limit')
                pairs.append((left,right));paired.update((left.history_observation_id,right.history_observation_id))
    pairs.extend((o,None) for o in observations if o.history_observation_id not in paired)
    if len(pairs)>10000: raise EvidenceError('history_comparison_work_limit')
    return ordered(compare(a,b,context_conflict=a.history_observation_id in conflicts or b is not None and b.history_observation_id in conflicts) for a,b in pairs)
