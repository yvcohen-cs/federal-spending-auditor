"""Audit preserved native action counterparts; never construct new mappings.

Only the existing USA/FPDS six-component namespace contract is admitted. This
is a finite identity assertion, not common revision, correction or money proof.
"""
from collections import defaultdict
from .evidence_io import EvidenceError, digest, strict_json
from .revision_lineage import LineageObservation, NATIVE, action_key


def audit(graph):
    if type(graph) is not dict or type(graph.get('nodes')) is not list or len(graph['nodes']) > 1000:
        raise EvidenceError('bounded_replayed_native_observations_required')
    nodes = []
    for raw in graph['nodes']:
        if type(raw) is not dict:
            raise EvidenceError('native_observation_required')
        n = LineageObservation.from_dict({k: v for k, v in raw.items() if k != 'node_id'})
        if n.node_id != raw.get('node_id'):
            raise EvidenceError('native_observation_identifier_conflict')
        nodes.append(n)
    if len({n.node_id for n in nodes}) != len(nodes) or len({n.profile for n in nodes}) > 1:
        raise EvidenceError('duplicate_or_mixed_profile_native_observations')
    groups, unsupported = defaultdict(list), []
    for n in nodes:
        key = action_key(n, cross=True)
        if key is None:
            unsupported.append({'node_id': n.node_id, 'source': n.source,
                'status': 'UNSUPPORTED_MAPPING', 'citation': strict_json(n.citation_json.encode()),
                'reason': 'exact_existing_namespace_or_native_scope_not_established'})
        else:
            groups[key].append(n)
    results = []
    for key, group in sorted(groups.items()):
        sources = {n.source for n in group}
        signatures = defaultdict(set)
        for n in group:
            # Multiple copies cannot become additional independent sources.
            signatures[n.source].add((n.content_sha256, n.monetary_fields_json))
        conflict = any(len(values) > 1 for values in signatures.values())
        status = ('CONFLICTING_OBSERVATIONS' if conflict else
            'VERIFIED_CROSS_SOURCE_IDENTITY' if sources == {'usaspending', 'fpds'} else 'MISSING_AUTHORITATIVE_COUNTERPART')
        results.append({'association_id': 'native-counterpart:v1:' + digest(list(key)),
            'native_components': dict(zip(NATIVE, key)), 'status': status,
            'mapping_rule': 'existing_usa-fpds-v1' if sources == {'usaspending', 'fpds'} else None,
            'evidence_class': 'PRESERVED_REPLAY', 'nodes': [
                {'node_id': n.node_id, 'source': n.source, 'native_action_id': n.native_action_id,
                    'citation': strict_json(n.citation_json.encode())} for n in sorted(group, key=lambda n: n.node_id)],
            'independent_source_namespaces': sorted(sources),
            'new_authoritative_mapping': False, 'common_revision_established': False,
            'financial_comparison_authorized': False,
            'limitations': ['finite_exact_native_identity_only', 'source_hash_is_not_identity',
                'current_parent_summary_does_not_supply_parent_action_counterpart']})
    return {'schema_type': 'NativeCounterpartAudit', 'schema_version': 1,
        'associations': results, 'unsupported_observations': sorted(unsupported, key=lambda r: r['node_id']),
        'new_authoritative_cross_source_mappings': 0, 'financial_comparison_authorized': False}
