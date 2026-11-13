"""Source-specific proof obligations, not a new historical eligibility rule.

Only independently replayed primary packages may supply historical observations.
No reviewed source contract currently admits an applicability or correction rule.
"""
from enum import Enum
from html.parser import HTMLParser
from pathlib import Path

from .evidence import _hash, _timestamp
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .identity_matching import decode_usa_id
from .matching_models import MatchEvidenceReference
from .source_contracts import identifier


class ProofState(str, Enum):
    OBSERVED = 'OBSERVED'
    CONFLICTING = 'CONFLICTING'
    INSUFFICIENT = 'INSUFFICIENT'
    UNSUPPORTED = 'UNSUPPORTED'
    VERIFIED = 'VERIFIED'


REFERENCES = {
    'sam-guide': ('samgov', 'https://open.gsa.gov/api/contract-awards/',
                  '033a7007b702d25f1582f06feb8c0dd5d6dce3afee056cb57b61995e0e7443c7'),
    'fpds-correction-help': ('fpds', 'https://www.fpds.gov/help/Correct_a_Transaction.htm',
                            '51bc5a391f226224028422365d8b161397d3f1d6e391541d5d3b1f8f6d9ad73f'),
    'usa-transactions': ('usaspending', 'https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/c2b82690eb044e130afc80b546343a2af0b4af1a/usaspending_api/api_contracts/contracts/v2/transactions.md',
                         '76a50f3445670d8ee5488770d6583a7f6399a093a903dabfbab77344f1eba078'),
}
COMPONENTS = ('piid', 'agency', 'parent_piid', 'parent_agency', 'modification', 'transaction')


class VisibleText(HTMLParser):
    """Inspection projection only: never execute scripts or relax byte hashes."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.values = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, value):
        if not self.hidden and value.strip():
            self.values.append(' '.join(value.split()))


def documentation(path):
    """Bind reviewed semantics to exact public responses and retrieval metadata."""
    observations = []
    with EvidenceRoot(path, max_bytes=1048576) as root:
        for name, (source, url, reviewed) in REFERENCES.items():
            body = root.read(name + '.body')
            meta = strict_json(root.read(name + '.json').data)
            expected = {'request', 'status', 'retrieved_at_utc', 'body_complete',
                        'body_sha256', 'representation', 'location'}
            if (type(meta) is not dict or set(meta) != expected
                    or meta['request'] != {'method': 'GET', 'url': url, 'redirects': False}
                    or type(meta['status']) is not int or meta['status'] != 200
                    or meta['body_complete'] is not True or meta['location'] is not None
                    or type(meta['retrieved_at_utc']) is not str
                    or meta['body_sha256'] != body.byte_sha256
                    or meta['representation'] != 'HTTP_entity_bytes_after_content_decoding'):
                raise EvidenceError('historical_document_provenance_conflict')
            _timestamp(meta['retrieved_at_utc'])
            text = VisibleText()
            text.feed(body.data.decode('utf-8', errors='strict'))
            observations.append({'source': source, 'body_file': name + '.body',
                'metadata_file': name + '.json', 'retrieval': meta,
                'reviewed_document_version': body.byte_sha256 == reviewed,
                'visible_text_sha256': digest(text.values),
                'interpretation': 'REFERENCE_OR_WORKFLOW_NOT_APPLICABILITY_RULE'
                    if body.byte_sha256 == reviewed else 'UNREVIEWED_DOCUMENT_VERSION',
                'selected_primary_behavior_verified': False,
                'historical_rule_admitted': False})
            root.read(name + '.body', recheck=True)
            root.read(name + '.json', recheck=True)
    return observations


def assess(historical, *, profile, authority_claims=()):
    """Recompute the five distinct levels; reject caller-supplied authority.

    This is a secondary consistency check after package primary replay. Hashes
    alone do not authenticate publishers. A future positive rule needs a new
    reviewed rule version, primary source interpretation and revision binding.
    """
    if (profile not in ('live', 'synthetic') or type(historical) is not dict
            or historical.get('schema_type') != 'HistoricalParentModificationAssessment'
            or type(historical.get('schema_version')) is not int or historical['schema_version'] != 1
            or type(authority_claims) not in (tuple, list) or len(authority_claims) > 16):
        raise EvidenceError('versioned_replayed_historical_assessment_required')
    if authority_claims or historical.get('financial_comparison_authorized') is not False:
        raise EvidenceError('no_admitted_historical_authority_rule')
    if (historical.get('historical_parent_applicability_intervals') != []
            or historical.get('authoritative_correction_relationships') != []):
        raise EvidenceError('unsupported_historical_authority_promotion')
    selected = historical['selected_native_action']
    if (type(selected) is not dict or set(selected) != set(COMPONENTS)
            or any(type(v) is not str or not v or len(v) > 256 for v in selected.values())):
        raise EvidenceError('exact_native_historical_action_required')
    for value in selected.values():
        identifier(value)
    children = historical['original_child_evidence']
    parents = historical['parent_modification_candidates']
    if (type(children) is not list or not 1 <= len(children) <= 64
            or type(parents) is not list or len(parents) > 32):
        raise EvidenceError('bounded_primary_historical_observations_required')
    assertions, sources, by_source = set(), set(), {}
    for child in children:
        if child['native_components'] != selected or child['source'] not in ('fpds', 'usaspending'):
            raise EvidenceError('historical_child_native_context_conflict')
        cite = child['citation']
        ref = MatchEvidenceReference.from_dict(cite['original_reference'])
        if (cite['input_role'] != 'original_C10_primary'
                or ref.artifact.source != child['source']
                or ref.reference.native_id is None
                or (ref.reference.native_id.value != child['native_action_id']
                    if child['source'] == 'usaspending' else
                    ref.reference.native_id.namespace != 'PIID'
                    or ref.reference.native_id.value != selected['piid'])
                or ('synthetic_fixture_only' in ref.artifact.limitations) != (profile == 'synthetic')):
            raise EvidenceError('historical_child_primary_provenance_conflict')
        _hash(cite['input_inventory_sha256'])
        source = child['source']
        sources.add(source)
        by_source.setdefault(source, set()).add(child['node_id'])
        value = child['referenced_parent_modification']
        if value is not None:
            if source != 'fpds' or type(value) is not str or not value or len(value) > 256:
                raise EvidenceError('unsupported_native_parent_modification_reference')
            assertions.add(value)
    ids = []
    for parent in parents:
        native, issues = decode_usa_id(parent['source_native_record_id'])
        cite = parent['evidence']
        if (issues or {k: v.to_dict() for k, v in native.items()} != parent['native_action_components']
                or [native['piid'].value, native['agency'].value] != [selected['parent_piid'], selected['parent_agency']]
                or parent['modification_number'] != native['modification'].value
                or parent['modification_number'] not in assertions
                or cite['source'] != 'usaspending' or not cite['locator'].startswith('/results/')):
            raise EvidenceError('historical_parent_native_binding_conflict')
        for key in ('archive_sha256', 'body_sha256', 'metadata_sha256'):
            _hash(cite[key])
        if type(cite['retrieved_at_utc']) is not str:
            raise EvidenceError('historical_parent_retrieval_time_unknown')
        _timestamp(cite['retrieved_at_utc'])
        if cite['representation'] != ('synthetic_transcript_bytes' if profile == 'synthetic'
                                      else 'HTTP_entity_bytes_after_content_decoding'):
            raise EvidenceError('historical_parent_representation_conflict')
        ids.append(parent['source_native_record_id'])
    conflict = len(assertions) > 1 or any(len(v) > 1 for v in by_source.values())
    conflict = conflict or historical['conflicting_child_assertions_or_variants']
    observed = ProofState.CONFLICTING if conflict else ProofState.OBSERVED
    levels = [
        ('parent_identity_observed', observed if sources == {'fpds', 'usaspending'} else ProofState.INSUFFICIENT),
        ('referenced_parent_modification_observed', observed if assertions else ProofState.INSUFFICIENT),
        ('parent_modification_independently_retrieved', observed if ids else ProofState.INSUFFICIENT),
        ('historical_applicability_supported_by_authoritative_semantics', ProofState.UNSUPPORTED),
        ('historical_applicability_independently_verified', ProofState.INSUFFICIENT),
    ]
    return {'schema_type': 'HistoricalSourceAuthorityAssessment', 'schema_version': 1,
        'rule_version': 'historical-source-authority-v1', 'profile': profile,
        'claim_id': 'historical-authority:v1:' + digest(selected), 'selected_native_action': selected,
        'evidence_levels': [{'obligation': key, 'state': state.value} for key, state in levels],
        'primary_child_citations': children, 'primary_parent_citations': parents,
        'literal_parent_modification_references': sorted(assertions),
        'parent_native_record_ids': sorted(set(ids)), 'parent_observation_occurrences': len(ids),
        'conflicting_observations_preserved': bool(conflict),
        'reused_parent_modification_label': (bool(historical['reused_parent_modification_label'])
            or len({p['modification_number'] for p in parents}) < len(set(ids))),
        'namespace_mapping_verified': False, 'selected_revision_verified': False,
        'missing_proof_obligations': ['authoritative_source_rule_for_historical_applicability',
            'FPDS_to_USA_parent_action_namespace_mapping', 'selected_child_and_parent_revision_binding',
            'historical_publication_and_deletion_coverage', 'independent_application_of_admitted_rule']
            + ([] if parents else ['referenced_parent_primary_action']),
        'verified_historical_relationships': [], 'authoritative_correction_edges': [],
        'financial_comparison_authorized': False, 'readiness_changed': False,
        'repeated_observations_are_independent_corroboration': False}
