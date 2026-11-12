"""C17 read-only parent-modification evidence, never effective applicability.

Only original, scope-verified actions are admitted. A cross-source label match
is a candidate, even if there is exactly one parent observation.
"""
from .correction_reporting import report as c14_report, _parent_modification
from .authority_binding import c14_case
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .revision_lineage import LineageObservation, action_key
from .identity_matching import decode_usa_id


def assess(case, parent_records, *, modification, transaction):
    if any(type(v) is not str or not v or len(v) > 256 for v in (modification, transaction)):
        raise EvidenceError('literal_selected_action_components_required')
    if type(parent_records) not in (list, tuple) or len(parent_records)>32:
        raise EvidenceError('bounded_primary_parent_observations_required')
    for record in parent_records:
        decoded, issues=decode_usa_id(record['source_native_record_id'])
        if issues or {k:v.to_dict() for k,v in decoded.items()}!=record['native_action_components'] or decoded['modification'].value!=record['modification_number']:
            raise EvidenceError('parent_observation_native_components_conflict')
    old = c14_report([c14_case(case)])['cases'][0]
    nodes = []
    for raw in old['observation_graph']['nodes']:
        n = LineageObservation.from_dict({k: v for k, v in raw.items() if k != 'node_id'})
        c = strict_json(n.citation_json.encode())
        key = action_key(n, cross=True)
        if c['input_role'] == 'original_C10_primary' and key and key[-2:] == (modification, transaction):
            nodes.append(n)
    groups = {action_key(n, cross=True) for n in nodes}
    if len(groups) != 1 or {n.source for n in nodes} != {'usaspending', 'fpds'}:
        raise EvidenceError('one_exact_original_USA_FPDS_action_required')
    # Preserve repeated/competing source observations rather than choosing one.
    refs = [{'node_id': n.node_id, 'source': n.source, 'native_action_id': n.native_action_id,
        'native_components': strict_json(n.native_context_json.encode()),
        'action_date': n.action_date, 'citation': strict_json(n.citation_json.encode()),
        'referenced_parent_modification': _parent_modification(n, c14_case(case))} for n in nodes]
    asserted = sorted({r['referenced_parent_modification'] for r in refs if r['referenced_parent_modification'] is not None})
    pair = list(next(iter(groups))[2:4])
    candidates = []
    for record in parent_records:
        c = record['native_action_components']
        if [c['piid']['value'], c['agency']['value']] == pair and record['modification_number'] in asserted:
            candidates.append(record)
    variants = len(asserted) > 1 or any(len({n.content_sha256 for n in nodes if n.source == s}) > 1 for s in ('usaspending', 'fpds'))
    unique_parent_ids={r['source_native_record_id'] for r in candidates}
    reused = len({r['modification_number'] for r in candidates}) < len(unique_parent_ids)
    return {'schema_type': 'HistoricalParentModificationAssessment', 'schema_version': 1,
        'constructed_claim_id': 'parent-applicability-claim:v1:' + digest({'case': old['original_case_sha256'], 'action': list(next(iter(groups)))}),
        'original_case_sha256': old['original_case_sha256'], 'selected_native_action': dict(zip(('piid','agency','parent_piid','parent_agency','modification','transaction'), next(iter(groups)))),
        'original_child_evidence': refs, 'source_specific_parent_modification_assertions': asserted,
        'parent_modification_candidates': candidates,
        'conflicting_child_assertions_or_variants': variants, 'reused_parent_modification_label': reused,
        'distinct_parent_native_record_ids':sorted(unique_parent_ids),
        'duplicate_parent_observation_occurrences':len(candidates)-len(unique_parent_ids),
        'duplicates_are_independent_corroboration':False,
        'evidence_levels': {'child_references_parent_award': all(pair),
            'child_references_parent_modification': bool(asserted),
            'parent_modification_independently_observed': bool(candidates),
            'authoritative_historical_applicability_rule_established': False,
            'historical_applicability_independently_verified': False},
        'parent_action_cross_source_identity': 'UNVERIFIED',
        'historical_parent_applicability_intervals': [], 'authoritative_correction_relationships': [],
        'blockers': sorted(set(['no_admitted_authoritative_effective_or_revision_rule',
            'FPDS_reference_to_USA_parent_action_requires_authoritative_native_mapping',
            'current_summary_and_action_dates_do_not_establish_historical_applicability']
            + (['conflicting_child_observations'] if variants else [])
            + (['reused_parent_modification_requires_revision_disambiguation'] if reused else [])
            + (['original_child_parent_modification_reference_missing_or_unsupported'] if not asserted else [])
            + (['referenced_parent_modification_not_observed'] if asserted and not candidates else []))),
        'financial_comparison_authorized': False, 'readiness_changed': False}
