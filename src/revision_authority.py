"""Directed claims require explicit source semantics, not observation ordering.

No reviewed live source currently has an admitted correction-edge adapter.
The explicit synthetic protocol exercises admission, ambiguity and cycle safety
without pretending that fixture statements are federal source guarantees.
"""
from dataclasses import dataclass
from enum import Enum

from .evidence import Schema, _hash, _text, _timestamp
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .revision_lineage import LineageObservation, native

RULE = 'directed-revision-admission-v1'
SYNTHETIC_RULE = 'synthetic-explicit-revision-v1'
LIVE_RULES = ()  # Adding an adapter requires documented native relationship semantics.


class RelationStatus(str, Enum):
    SUPPORTED = 'EXPLICIT_SYNTHETIC_RELATION'
    CONFLICTING = 'CONFLICTING_RELATION_EVIDENCE'
    UNRESOLVED = 'UNRESOLVED_RELATION'
    UNSUPPORTED = 'UNSUPPORTED_RELATION'


@dataclass(frozen=True, kw_only=True)
class RevisionStatement(Schema):
    profile: str
    source: str
    successor_node_id: str
    predecessor_native_id: str
    predecessor_content_sha256: str
    relation: str
    applicable_at_utc: str
    rule_version: str
    citation_json: str

    def validate(self):
        if self.profile not in ('live', 'synthetic') or self.source not in ('usaspending', 'fpds', 'samgov'):
            raise ValueError('explicit_source_profile_required')
        for value in (self.successor_node_id, self.predecessor_native_id, self.rule_version):
            _text(value, 'native relation reference')
            if len(value) > 256:
                raise ValueError('bounded_relation_identifier_required')
        if not self.successor_node_id.startswith('revision-node:v1:'):
            raise ValueError('constructed_observation_reference_required')
        _hash(self.predecessor_content_sha256)
        _timestamp(self.applicable_at_utc)
        if self.relation not in ('corrects', 'replaces', 'deletes', 'reinstates'):
            raise ValueError('explicit_narrow_relation_required')
        citation = strict_json(self.citation_json.encode())
        if (type(citation) is not dict or not citation or canonical(citation) != self.citation_json
            or len(self.citation_json) > 131072):
            raise ValueError('canonical_primary_relation_citation_required')


@dataclass(frozen=True, kw_only=True)
class DirectedRevision(Schema):
    predecessor: str
    successor: str
    source: str
    profile: str
    relation: str
    status: RelationStatus
    rule_version: str
    statement_sha256: str
    citation_json: str
    applicable_at_utc: str
    correction_winner_selected: bool = False
    historical_completeness_certified: bool = False
    financial_comparison_authorized: bool = False

    def validate(self):
        if self.predecessor == self.successor or any(not n.startswith('revision-node:v1:') for n in (self.predecessor, self.successor)):
            raise ValueError('distinct_bound_observation_nodes_required')
        for node in (self.predecessor, self.successor):
            _hash(node.removeprefix('revision-node:v1:'))
        if (self.profile != 'synthetic' or self.rule_version != SYNTHETIC_RULE
            or self.source != 'usaspending' or self.relation not in ('corrects', 'replaces', 'deletes', 'reinstates')
            or self.status not in (RelationStatus.SUPPORTED, RelationStatus.CONFLICTING)):
            raise ValueError('no_live_directed_rule_has_been_validated')
        if any(v is not False for v in (self.correction_winner_selected, self.historical_completeness_certified, self.financial_comparison_authorized)):
            raise ValueError('directed_relation_cannot_authorize_winner_completeness_or_money')
        _hash(self.statement_sha256)
        _timestamp(self.applicable_at_utc)
        citation = strict_json(self.citation_json.encode())
        if type(citation) is not dict or not citation or canonical(citation) != self.citation_json or len(self.citation_json) > 131072:
            raise ValueError('primary_directed_relation_citation_required')


def statement_from_row(node, row):
    """Only the controlled fixture path is supported. Live controls fail closed.

    Caller must replay the node's original body and locator before invoking this
    extractor. The report tool does so; direct model construction is no proof.
    """
    control = row.get('_c14_revision')
    if control is None:
        return None
    if node.profile != 'synthetic' or node.source != 'usaspending':
        raise EvidenceError('synthetic_revision_control_in_live_evidence')
    keys = {'profile', 'predecessor_native_id', 'predecessor_content_sha256', 'relation', 'applicable_at_utc'}
    if type(control) is not dict or set(control) != keys or control['profile'] != SYNTHETIC_RULE:
        raise EvidenceError('unsupported_explicit_revision_control')
    return RevisionStatement(profile=node.profile, source=node.source,
        successor_node_id=node.node_id, predecessor_native_id=control['predecessor_native_id'],
        predecessor_content_sha256=control['predecessor_content_sha256'], relation=control['relation'],
        applicable_at_utc=control['applicable_at_utc'], rule_version=SYNTHETIC_RULE,
        citation_json=canonical({'original_observation': strict_json(node.citation_json.encode()),
            'field': '/_c14_revision', 'original_statement': control}))


def directed_graph(nodes, statements):
    nodes, statements = tuple(nodes), tuple(statements)
    if (len(nodes) > 1000 or len(statements) > 1000
        or any(type(n) is not LineageObservation for n in nodes)
        or any(type(s) is not RevisionStatement for s in statements)):
        raise EvidenceError('bounded_typed_revision_inputs_required')
    byid = {n.node_id: n for n in nodes}
    if len(byid) != len(nodes) or len({n.profile for n in nodes}) > 1:
        raise EvidenceError('duplicate_or_mixed_profile_revision_nodes')
    edges, unresolved = [], []
    seen = set()
    for statement in sorted(statements, key=lambda s: s.to_json()):
        fingerprint = digest(statement.to_dict())
        if fingerprint in seen:
            raise EvidenceError('duplicate_relation_statement_not_independent_evidence')
        seen.add(fingerprint)
        successor = byid.get(statement.successor_node_id)
        reason = None
        if successor is None or successor.profile != statement.profile or successor.source != statement.source:
            reason = 'successor_source_profile_or_reference_conflict'
        elif statement.profile != 'synthetic' or statement.rule_version != SYNTHETIC_RULE or statement.source != 'usaspending':
            reason = 'no_validated_live_directed_semantics'
        predecessors = [n for n in nodes if n.source == statement.source and n.profile == statement.profile
            and n.native_action_id == statement.predecessor_native_id
            and n.content_sha256 == statement.predecessor_content_sha256]
        if reason is None and len(predecessors) != 1:
            reason = 'missing_or_ambiguous_exact_predecessor_occurrence'
        if reason is None:
            predecessor = predecessors[0]
            if (predecessor.node_id == successor.node_id or not predecessor.identity_supported
                or not successor.identity_supported or predecessor.outside_requested_context
                or successor.outside_requested_context
                or native(predecessor) != native(successor)):
                reason = 'revision_requires_same_complete_source_native_action_context'
            elif any(v is None for v in native(predecessor).values()):
                reason = 'incomplete_native_relation_context'
        if reason is not None:
            unresolved.append({'statement_sha256': fingerprint, 'statement': statement.to_dict(),
                'status': RelationStatus.UNRESOLVED.value, 'reason': reason})
            continue
        edges.append(DirectedRevision(predecessor=predecessor.node_id, successor=successor.node_id,
            source=statement.source, profile=statement.profile, relation=statement.relation,
            status=RelationStatus.SUPPORTED, rule_version=SYNTHETIC_RULE,
            statement_sha256=fingerprint, citation_json=statement.citation_json,
            applicable_at_utc=statement.applicable_at_utc).to_dict())
    # Preserve every conflicting assertion. No topological winner is chosen.
    outgoing = {}
    for edge in edges:
        outgoing.setdefault(edge['predecessor'], set()).add(edge['successor'])
    def reaches(start, target):
        pending, visited = [start], set()
        while pending:
            node = pending.pop()
            if node == target:
                return True
            if node not in visited:
                visited.add(node)
                pending.extend(outgoing.get(node, ()))
        return False
    conflicts = []
    for edge in edges:
        same_pair = [e for e in edges if (e['predecessor'], e['successor']) == (edge['predecessor'], edge['successor'])]
        reasons = []
        if reaches(edge['successor'], edge['predecessor']):
            reasons.append('directed_cycle')
        if len(outgoing[edge['predecessor']]) > 1:
            reasons.append('competing_successors')
        if len({e['relation'] for e in same_pair}) > 1:
            reasons.append('contradictory_relationship_types')
        if reasons:
            edge['status'] = RelationStatus.CONFLICTING.value
            conflicts.append({'statement_sha256': edge['statement_sha256'], 'reasons': reasons})
    return {'schema_type': 'DirectedRevisionGraph', 'schema_version': 1, 'rule_version': RULE,
        'edges': sorted(edges, key=canonical), 'unresolved': unresolved,
        'conflicts': sorted(conflicts, key=canonical), 'validated_live_rules': list(LIVE_RULES),
        'established_real_source_revision_relationships': 0,
        'explicit_synthetic_relationships': sum(e['status'] == RelationStatus.SUPPORTED.value for e in edges),
        'correction_winners': [], 'financial_comparison_authorized': False,
        'historical_completeness_certified': False}
