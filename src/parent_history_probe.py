"""C14 bounded USA parent action lookup, anchored in preserved C12 evidence.

Offline by default. A located record is not an effective-interval certificate.
"""
import hashlib
import time
from enum import Enum

from .award_validation import snapshot, pagination
from .collection import CollectionLimits, SelectedAward
from .collection_sources import HTTPTransport, FixtureTransport, request_for
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .historical_probe import anchor, manifest
from .identity_matching import decode_usa_id, agency_component
from .pilot_store import PilotStore
from .review_packet_io import outside
from .source_contracts import identifier, usa_transaction_contract
from .source_verification import _metadata

RULE = 'historical-parent-action-v1'


class ParentEvidenceState(str, Enum):
    CURRENT = 'CURRENT_PARENT_RELATIONSHIP_VERIFIED'
    ASSERTED = 'HISTORICAL_ACTION_ASSERTS_PARENT'
    LOCATED = 'HISTORICAL_PARENT_RECORD_INDEPENDENTLY_LOCATED'
    APPLICABLE = 'HISTORICAL_PARENT_APPLICABILITY_ESTABLISHED'
    UNRESOLVED = 'HISTORICAL_PARENT_APPLICABILITY_UNRESOLVED'


def plan_for(base, *, contract_version=2):
    if type(contract_version) is not int or contract_version not in (1, 2):
        raise EvidenceError('supported_parent_contract_version_required')
    observed, child = anchor(base)
    if observed['current_source_parent_link'] != 'verified_source_local_summary_link':
        raise EvidenceError('independently_replayed_current_parent_required')
    parent = observed['parent']
    # The opaque parent ID is returned by the source, never constructed.
    selected = SelectedAward(generated_id=identifier(parent['native_award_id']),
        piid=child.parent_piid, agency_id=child.parent_agency_id)
    return {'schema_type': 'ParentHistoryProbePlan', 'schema_version': 1,
        **({'parent_contract_version': 2} if contract_version == 2 else {}),
        'rule_version': RULE, 'base_C12_inventory_sha256': observed['inventory_sha256'],
        'selection': selected.to_dict(), 'child_selection': child.to_dict(),
        'profile': 'synthetic' if observed['knowledge_basis'] == 'SYNTHETIC_ONLY' else 'live',
        'source_allowlist': ['usaspending'], 'maximum_requests': 2,
        'page_size': 5, 'maximum_rows': 10, 'retries': 0, 'redirects': False,
        'pace_seconds': 1.0, 'max_response_bytes': 1048576,
        'config': {'max_run_bytes': 8 * 1024 * 1024}}


def request(plan, page):
    return request_for('usaspending', plan['selection'], page, plan['page_size'])


def parse(raw, req, plan):
    selected = plan['selection']
    parsed = usa_transaction_contract(raw, req, selected)
    for row in parsed['rows']:
        context, issues = decode_usa_id(row['id'])
        if (issues or context['piid'].value != selected['piid']
            or agency_component(context['agency']).value != selected['agency_id']
            or context['modification'].value is None
            or (plan.get('parent_contract_version', 1) == 1 and context['transaction'].value is None)
            or (context['transaction'].value is None and context['transaction'].original_json != canonical('-NONE-'))
            or context['modification'].value != row['modification_number']):
            raise EvidenceError('parent_action_native_context_conflict')
        # Reject a loan/assistance/ordinary contract row returned for an IDV.
        if row.get('type') not in ('IDV_A', 'IDV_B', 'IDV_B_A', 'IDV_B_B', 'IDV_B_C', 'IDV_C', 'IDV_D', 'IDV_E'):
            raise EvidenceError('parent_action_instrument_not_IDV')
    return parsed


def record(row, citation):
    components, _ = decode_usa_id(row['id'])
    return {'row': row, 'citation': citation,
        'row_representation': 'parsed_JSON_observation_original_entity_bytes_cited',
        'native_action_components': {name: value.to_dict() for name, value in components.items()}}


def collect(path, base, *, live=False, synthetic=None):
    plan = plan_for(base)
    if type(live) is not bool:
        raise EvidenceError('explicit_parent_probe_mode_required')
    if live:
        if plan['profile'] != 'live' or synthetic is not None:
            raise EvidenceError('live_parent_probe_requires_live_anchor')
    elif plan['profile'] != 'synthetic' or synthetic is None:
        raise EvidenceError('offline_default_no_network')
    if synthetic is not None:
        if (type(synthetic) is not dict or set(synthetic) != {'schema_version', 'responses'}
            or synthetic['schema_version'] != 1 or type(synthetic['responses']) is not list
            or not 1 <= len(synthetic['responses']) <= 2):
            raise EvidenceError('bounded_parent_transcript_required')
        transport = FixtureTransport(synthetic)
    outside(path, (base,))
    before = manifest(base)
    with PilotStore(path, plan) as store:
        if live:
            transport = HTTPTransport(CollectionLimits(retries=0, timeout_seconds=10.0,
                pace_seconds=1.0, max_response_bytes=1048576).to_dict())
        for index in range(2):
            req = request(plan, index + 1)
            stem = f'parent-{index + 1:03d}'
            store.write(stem + '-reservation.json', {'sequence': index, 'request': req})
            if live and index:
                time.sleep(1.0)
            meta, raw = transport(req, index)
            if raw is not None and len(raw) > 1048576:
                raw = raw[:1048576]
                meta = {**meta, 'body_complete': False, 'error_code': 'response_size_limit'}
            if raw is not None:
                store.write_bytes(stem + '.body', raw)
            store.write(stem + '.json', {'request': req, 'response': meta,
                'body_sha256': None if raw is None else hashlib.sha256(raw).hexdigest(),
                'representation': 'synthetic_transcript_bytes' if plan['profile'] == 'synthetic'
                    else 'HTTP_entity_bytes_after_content_decoding'})
            # Preserve bounded transport evidence before semantic admission.
            # Invalid metadata leaves an uncommitted forensic capture.
            okay = _metadata(meta, raw)
            if not okay:
                break
            try:
                parsed = parse(raw, req, plan)
            except (ValueError, KeyError, TypeError):
                break
            if not parsed['has_next']:
                break
        if manifest(base) != before:
            raise EvidenceError('parent_anchor_changed_during_collection')
        store.write('parent-commit.json', {'schema_version': 1, 'files': store.inventory()})
    return read(path, base)


def read(path, base):
    values = snapshot(path)
    files = {name: s.byte_sha256 for name, s in values.items()}
    saved_plan = strict_json(values['pilot-plan.json'].data)
    version = saved_plan.get('parent_contract_version', 1)
    plan = plan_for(base, contract_version=version)
    commit = values.get('parent-commit.json')
    if commit is None:
        raise EvidenceError('interrupted_parent_capture_preserve_evidence')
    expected = {'schema_version': 1, 'files': {n: h for n, h in files.items() if n != 'parent-commit.json'}}
    if (commit.data != (canonical(expected) + '\n').encode()
        or values['pilot-plan.json'].data != (canonical(plan) + '\n').encode()):
        raise EvidenceError('parent_probe_manifest_or_anchor_conflict')
    names = {'pilot-plan.json', 'parent-commit.json'}
    records, pages, failures = [], [], []
    continuing = True
    attempts = 0
    for index in range(2):
        stem = f'parent-{index + 1:03d}'
        if not continuing:
            if any(n.startswith(stem) for n in values):
                raise EvidenceError('parent_request_after_terminal_or_failure')
            continue
        req = request(plan, index + 1)
        if stem + '.json' not in values or stem + '-reservation.json' not in values:
            raise EvidenceError('missing_parent_request_history')
        names |= {stem + '.json', stem + '-reservation.json'}
        attempts += 1
        if values[stem + '-reservation.json'].data != (canonical({'sequence': index, 'request': req}) + '\n').encode():
            raise EvidenceError('parent_request_reservation_conflict')
        meta = strict_json(values[stem + '.json'].data)
        body = values.get(stem + '.body')
        if body is not None:
            names.add(stem + '.body')
        representation = 'synthetic_transcript_bytes' if plan['profile'] == 'synthetic' else 'HTTP_entity_bytes_after_content_decoding'
        if (set(meta) != {'request', 'response', 'body_sha256', 'representation'}
            or canonical(meta['request']) != canonical(req)
            or meta['representation'] != representation
            or meta['body_sha256'] != (None if body is None else body.byte_sha256)):
            raise EvidenceError('parent_response_provenance_conflict')
        citation = {'source': 'usaspending', 'request': req,
            'metadata_file': stem + '.json', 'metadata_sha256': values[stem + '.json'].byte_sha256,
            'body_file': None if body is None else stem + '.body', 'body_sha256': meta['body_sha256'],
            'retrieved_at_utc': meta['response']['retrieved_at_utc'],
            'source_update_raw': meta['response']['source_update_raw'], 'representation': representation}
        if not _metadata(meta['response'], None if body is None else body.data):
            failures.append({'citation': citation, 'reason': 'parent_source_failed_or_incomplete'})
            continuing = False
            continue
        try:
            parsed = parse(body.data, req, plan)
        except (ValueError, KeyError, TypeError):
            failures.append({'citation': citation, 'reason': 'unsupported_parent_action_or_pagination'})
            continuing = False
            continue
        pages.append((index + 1, parsed['has_next'], tuple(parsed['fingerprints'])))
        for i, row in enumerate(parsed['rows']):
            records.append(record(row, {**citation, 'locator': '/results/' + str(i)}))
        continuing = parsed['has_next']
    if set(values) != names or manifest(path) != files:
        raise EvidenceError('parent_inventory_changed_or_extra_files')
    dates = [r['row']['action_date'] for r in records]
    ids = [r['row']['id'] for r in records]
    if dates != sorted(dates):
        failures.append({'reason': 'parent_action_date_order_conflict'})
    if len(ids) != len(set(ids)):
        failures.append({'reason': 'duplicate_or_competing_parent_action_id'})
    result = {'schema_type': 'ParentHistoryProbe', 'schema_version': 1, 'rule_version': RULE,
        'capture_contract_version': version,
        'profile': plan['profile'], 'inventory_sha256': digest(files),
        'base_C12_inventory_sha256': plan['base_C12_inventory_sha256'],
        'selection': plan['selection'], 'request_attempts': attempts, 'records': records,
        'pagination': pagination(pages), 'failures': failures,
        'historical_parent_applicability': 'unknown', 'history_completeness': 'unknown',
        'replay_creates_new_observation': False, 'financial_comparison_authorized': False}
    # Preserve the v1 rejection exactly. A new rule may reassess the retained
    # response as record evidence; it does not repair/continue the old capture.
    reassessed = []
    reassessment_failures = []
    if version == 1:
        modern_plan = plan_for(base, contract_version=2)
        for index in range(attempts):
            stem = f'parent-{index + 1:03d}'
            metadata = strict_json(values[stem + '.json'].data)
            body = values.get(stem + '.body')
            if not _metadata(metadata['response'], None if body is None else body.data):
                reassessment_failures.append('original_source_attempt_unusable')
                continue
            try:
                parsed = parse(body.data, request(modern_plan, index + 1), modern_plan)
            except (ValueError, KeyError, TypeError):
                reassessment_failures.append('parent_contract_v2_record_rejected')
                continue
            for row_index, row in enumerate(parsed['rows']):
                cite = {'source': 'usaspending', 'request': metadata['request'],
                    'metadata_file': stem + '.json', 'metadata_sha256': values[stem + '.json'].byte_sha256,
                    'body_file': stem + '.body', 'body_sha256': body.byte_sha256,
                    'retrieved_at_utc': metadata['response']['retrieved_at_utc'],
                    'source_update_raw': metadata['response']['source_update_raw'],
                    'representation': metadata['representation'], 'locator': '/results/' + str(row_index)}
                reassessed.append(record(row, cite))
        dates = [r['row']['action_date'] for r in reassessed]
        ids = [r['row']['id'] for r in reassessed]
        if dates != sorted(dates) or len(ids) != len(set(ids)):
            reassessment_failures.append('competing_or_unordered_parent_records')
    result['record_reassessment'] = {'rule_version': 'parent-record-contract-v2',
        'records': reassessed if version == 1 else records,
        'failures': reassessment_failures if version == 1 else failures,
        'transaction_number_sentinel_means': 'unknown_not_zero',
        'original_capture_unchanged': True, 'new_HTTP_requests': 0,
        'capture_repaired_or_resumed': False, 'historical_applicability_established': False,
        'historical_completeness_certified': False}
    if manifest(path) != files:
        raise EvidenceError('parent_evidence_changed_during_reassessment')
    return result
