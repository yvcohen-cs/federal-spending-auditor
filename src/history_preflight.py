"""Source-local coverage and monetary compatibility only; no financial math."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .award_validation import snapshot
from .evidence_io import canonical, strict_json
from .financial_ingestion import _usa_fields
from .financial_models import field_semantics
from .financial_values import NumberToken, RawKind, exact_json, monetary_value
from .history_qualification import HistoricalInterval


def freshness(markers):
    observations = []
    for citation in markers:
        raw = citation.get('source_update_raw')
        retrieved = citation.get('retrieved_at_utc')
        parsed = None
        if raw is not None:
            try:
                parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
            except ValueError:
                try:
                    parsed = parsedate_to_datetime(raw)
                except (ValueError, TypeError, OverflowError):
                    pass
        if parsed is not None and parsed.tzinfo is None:
            parsed = None
        if parsed is not None:
            try:
                parsed = parsed.astimezone(timezone.utc)
            except (OverflowError, ValueError):
                parsed = None
        future = bool(parsed is not None and retrieved is not None and
            parsed > datetime.fromisoformat(retrieved.replace('Z', '+00:00')))
        observations.append({'citation': citation, 'source_update_raw': raw,
            'parsed_update_utc': None if parsed is None else parsed.isoformat(),
            'status': 'CONFLICTING_UPDATE_AFTER_RETRIEVAL' if future else 'UNKNOWN_FRESHNESS',
            'revision_precedence_established': False})
    return {'status': 'CONFLICTING_METADATA' if any(o['status'].startswith('CONFLICTING') for o in observations) else 'UNKNOWN',
        'observations': observations, 'freshness_certified': False,
        'blocker': 'authoritative_publication_delay_snapshot_and_asof_rules_missing'}


def parent_assessments(old, all_records):
    output = []
    for p in old['historical_parent_assessments']:
        mod = p['parent_action_modification_asserted']
        pair = p['native_parent_pair']
        asserted = 'HISTORICAL_ACTION_ASSERTS_PARENT' in p['states']
        # Even one candidate cannot supply a missing transaction/revision key.
        candidates = []
        if asserted and mod is not None and all(v is not None for v in pair):
            for r in all_records:
                components = r['native_action_components']
                if ([components['piid']['value'], components['agency']['value']] == pair
                    and r['row']['modification_number'] == mod):
                    candidates.append(r)
        output.append({'node_id': p['node_id'], 'source': p['source'],
            'native_action_id': p['native_action_id'], 'native_parent_pair': pair,
            'parent_identifier_observed': asserted,
            'parent_record_independently_located': 'HISTORICAL_PARENT_RECORD_INDEPENDENTLY_LOCATED' in p['states'],
            'parent_modification_asserted': mod,
            'parent_modification_records_observed': candidates,
            'historical_child_action_references_parent': 'HISTORICAL_ACTION_ASSERTS_PARENT' in p['states'],
            'historical_parent_applicability_established': False,
            'cross_source_parent_action_identity_established': False,
            'original_child_citation': p['child_citation'],
            'remaining_dependencies': ['authoritative_effective_applicability_rule_missing',
                'source_native_parent_revision_binding_missing', 'dates_and_modification_labels_not_applicability_certificates']})
    return output


def coverage(case, recipe, continuation):
    nodes = case['observation_graph']['nodes']
    interval = recipe.get('comparison_interval', recipe.get('interval'))
    interval = HistoricalInterval() if interval is None else HistoricalInterval.from_dict(interval) if type(interval) is dict else interval
    if type(interval) is not HistoricalInterval:
        raise ValueError('typed_requested_historical_interval_required')
    sources = []
    for source in ('usaspending', 'fpds', 'samgov'):
        selected = [n for n in nodes if n['source'] == source]
        contexts = [strict_json(n['native_context_json'].encode()) for n in selected]
        sources.append({'source': source, 'original_observations': len(selected),
            'base_modification_label_observed': any(c['modification'] == '0' for c in contexts),
            'original_as_submitted_record': 'unknown',
            'verified_native_scope_observations': sum(n['existing_native_scope_verified'] for n in selected),
            'observed_modifications': sorted({c['modification'] for c in contexts if c['modification'] is not None}),
            'expected_modification_sequence': None, 'missing_modifications_inferred': [],
            'signed_dates': sorted({n['action_date'] for n in selected if n['action_date'] is not None}),
            'effective_date_observations': [{'node_id': n['node_id'], 'field': m,
                'citation': strict_json(n['citation_json'].encode())} for n in selected
                for m in strict_json(n['update_metadata_json'].encode()) if m.get('meaning') == 'effective'],
            'requested_interval': interval.to_dict(), 'historical_interval_coverage': 'unknown',
            'correction_deletion_lineage': 'unknown', 'source_freshness': 'unknown',
            'monetary_revision_compatibility': 'unknown', 'financial_comparison_authorized': False})
    return {'source_assessments': sources,
        'parent_query': {'selection': None if continuation is None else continuation['selection'],
            'combined_pagination': None if continuation is None else continuation['combined_pagination'],
            'coverage_state': 'NOT_CONTINUED' if continuation is None else continuation['coverage_state'],
            'defined_scope': 'observed_USA_parent_IDV_table_pages_same_literal_selection_and_page_size',
            'snapshot_consistency': 'unknown', 'query_recall': 'unknown', 'entire_contract_history': 'unknown',
            'historical_interval_complete': False},
        'financial_comparison_authorized': False}


def monetary_preflight(case, recipe, continuation):
    fields = []
    for n in case['observation_graph']['nodes']:
        for value in strict_json(n['monetary_fields_json'].encode()):
            fields.append({'record_role': 'child_contract_observation', 'source': n['source'],
                'node_id': n['node_id'], 'field_observation': value,
                'citation': strict_json(n['citation_json'].encode()), 'eligible_for_arithmetic': False})
    parent = case['parent_probe']
    for path, records in ([ (recipe['parent_history'], parent['record_reassessment']['records']) ] if parent else []) + (
        [(recipe['continuation'], continuation['records'])] if continuation else []):
        values = snapshot(path)
        for r in records:
            citation = r['citation']
            raw = exact_json(values[citation['body_file']].data)['results'][int(citation['locator'].split('/')[-1])]
            _, observed = _usa_fields(raw)
            for name, kind, text, currency in observed:
                fields.append({'record_role': 'parent_IDV_action_observation', 'source': 'usaspending',
                    'native_record_id': r['row']['id'], 'original_field': name,
                    'value': monetary_value(kind, text).to_dict(),
                    'field_semantics': field_semantics('usaspending', name).to_dict(),
                    'declared_currency_raw': currency, 'citation': citation,
                    'currency_compatibility': 'CONFLICTING_OR_UNKNOWN' if currency not in (None, 'USD') else 'FIELD_DEFINED_UNIT_NOT_REVISION_COMPATIBILITY',
                    'eligible_for_arithmetic': False,
                    'scope_limitation': 'parent_IDV_action_is_not_child_contract_obligation_or_IDV_ceiling'})
    if recipe.get('c12_capture'):
        values = snapshot(recipe['c12_capture'])
        for name in ('detail-000.body', 'detail-001.body'):
            if name not in values:
                continue
            raw = exact_json(values[name].data)
            for field in ('total_obligation', 'base_exercised_options', 'base_and_all_options'):
                value = raw.get(field)
                kind = RawKind.JSON_NUMBER if isinstance(value, NumberToken) else RawKind.JSON_STRING if type(value) is str else RawKind.MISSING if value is None else RawKind.UNSUPPORTED
                fields.append({'record_role': 'parent_IDV_summary' if name == 'detail-001.body' else 'child_award_summary',
                    'source': 'usaspending', 'source_native_award_id': raw.get('generated_unique_award_id'),
                    'original_field': field, 'value': monetary_value(kind, None if value is None else str(value) if isinstance(value, NumberToken) or type(value) is str else canonical(value)).to_dict(),
                    'field_semantics': field_semantics('usaspending', field).to_dict(),
                    'citation': {'body_file': name, 'body_sha256': values[name].byte_sha256, 'locator': '/' + field,
                        'request': strict_json(values[name[:-5] + '.json'].data)['request']},
                    'eligible_for_arithmetic': False,
                    'scope_limitation': 'reported_summary_value_not_incremental_action_amount; IDV_value_or_ceiling_must_not_be_obligation'})
    return {'schema_version': 1, 'assessment_only': True, 'observed_fields': fields,
        'required_distinctions': ['transaction_obligation', 'deobligation_not_loss', 'modification_level_amount',
            'award_reported_total', 'cumulative_value', 'IDV_ceiling_not_obligation', 'historical_asof_value'],
        'required_before_comparison': ['exact_native_award_action_and_parent_scope', 'supported_same_field_measure_basis_and_unit',
            'complete_authoritative_history_and_deletion_visibility', 'historical_parent_applicability',
            'common_source_native_revision_and_asof', 'explicit_compatible_currency_and_precision',
            'existing_financial_eligibility_and_reconciliation_checks'],
        'status': 'BLOCKED', 'amount_comparisons_performed': 0, 'totals_or_deltas_computed': 0,
        'financial_comparison_authorized': False}
