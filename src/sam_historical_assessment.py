"""Conservative occurrence history, not action revision reconstruction or money."""
from collections import defaultdict

from .evidence_io import digest

# These are proof obligations, not boolean inputs capable of enabling arithmetic.
PROOF_OBLIGATIONS = (
    ('native_identity', 'Authoritatively bound namespaces, exact award/IDV, PIID, identity agency, parent and native action context for each source.'),
    ('revision_lineage', 'Immutable source revision identifiers and authoritative correction/replacement links, including direction and supersession.'),
    ('as_of_alignment', 'Independently evidenced common as-of revision and visibility; equal timestamps/schema versions do not suffice.'),
    ('deletion_lifecycle', 'Award-level deletion/reinstatement evidence, visibility entitlement and retained prior versions, not extract/job state.'),
    ('monetary_definition', 'Compatible action versus aggregate basis, currency, units, sign conventions, precision and treatment of adjustments.'),
    ('history_coverage', 'Explicit action-history bounds, opening balances and excluded/missing actions; bounded query pagination is insufficient.'),
    ('freshness', 'Source update/publication/reveal semantics, timezone, reporting lag and snapshot consistency supported separately.'),
    ('provenance_review', 'Preserved primary evidence and independently revalidated citations, unresolved contradictions reviewed under existing workflow.'),
)


def native_key(record):
    values = (record.award.award_class, record.award.instrument_type, record.award.piid,
        record.award.identity_subtier, record.award.parent_piid, record.award.parent_subtier,
        record.action.modification, record.action.transaction)
    return values if record.supported_schema and all(v is not None for v in values) else None


def assess(occurrences):
    """Occurrence dictionaries come only from revalidated C2 reports.

    Equal content means equal canonical parsed record JSON, never entity identity.
    Different contents for one full native key remain alternatives; no winner,
    direction, revision number or correction relationship is inferred.
    """
    by_content = defaultdict(list); by_key = defaultdict(list)
    for index, (capture_index, record) in enumerate(occurrences):
        ref = {'occurrence_index': index, 'capture_index': capture_index,
            'claim_id': record.claim_id, 'citation': record.citation.to_dict()}
        by_content[record.content_sha256].append(ref)
        key = native_key(record)
        if key is not None:
            by_key[key].append((record.content_sha256, ref))
    groups = []
    for key, items in sorted(by_key.items()):
        variants = sorted({sha for sha, _ in items})
        groups.append({'native_key_components': list(key), 'constructed_group_id': 'sam-native-context:v1:'+digest(key),
            'content_variants': variants, 'occurrences': [ref for _, ref in items],
            'relationship': 'contradictory_or_variant_content_unresolved' if len(variants)>1 else 'same_native_context_not_revision_certificate'})
    return {'schema_type': 'SAMHistoricalAssessment', 'schema_version': 1,
        'record_occurrences': len(occurrences), 'distinct_canonical_record_contents': len(by_content),
        'same_content_groups': [{'canonical_content_sha256': sha, 'occurrences': refs,
            'retrieval_relation': 'multiple_capture_occurrences_same_content' if len({r['capture_index'] for r in refs})>1
                else 'same_capture_content_occurrences', 'identity_inferred_from_hash': False}
            for sha, refs in sorted(by_content.items()) if len(refs)>1],
        'native_action_context_groups': groups,
        'distinct_complete_native_action_contexts': len(groups),
        'occurrences_without_complete_native_context': sum(native_key(r) is None for _, r in occurrences),
        'variant_native_context_groups': sum(len(g['content_variants'])>1 for g in groups),
        'certified_revision_relationships': 0, 'certified_corrections': 0, 'certified_deletions': 0,
        'publication_reveal_timestamp_semantics': 'unknown_no_validated_record_path',
        'transaction_history_complete': 'unknown', 'source_wide_complete': 'unknown', 'freshness': 'unknown',
        'financial_arithmetic': 'withheld', 'financial_eligibility_changed': False,
        'future_comparison_proof_obligations': [{'id': key, 'requirement': text, 'status': 'UNKNOWN'} for key, text in PROOF_OBLIGATIONS],
        'limitations': ['Multiple native contexts are not proof of a complete transaction history.',
            'Schema/document versions, same timestamps, prior IDs, matching money and repeated retrievals are not common revision certificates.',
            'No winner, replacement direction or deletion inferred from contradictory source content.',
            'Six-month deleted-only visibility cannot establish complete deletion history; job flags are not award deletions.']}
