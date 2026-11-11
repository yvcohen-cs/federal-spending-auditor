"""Separately journaled, bounded continuation of a preserved parent query.

A contiguous terminal page chain is an observation, not a historical archive.
"""
import hashlib
import time
from dataclasses import dataclass

from .award_validation import snapshot, pagination
from .collection import CollectionLimits
from .collection_sources import FixtureTransport, HTTPTransport
from .evidence import Schema, _text
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .historical_probe import manifest
from .parent_history_probe import read as read_parent, plan_for as parent_plan, parse, record, request
from .pilot_store import PilotStore
from .review_packet_io import outside
from .source_verification import _metadata

RULE = 'parent-continuation-v1'


@dataclass(frozen=True, kw_only=True)
class ContinuationLimits(Schema):
    max_requests: int = 2
    max_records: int = 10

    def validate(self):
        if not 1 <= self.max_requests <= 2 or not 5 <= self.max_records <= 10:
            raise ValueError('at_most_two_requests_ten_rows_fixed_five_row_pages')


def baseline(parent, c12):
    observed = read_parent(parent, c12)
    reassessed = observed['record_reassessment']
    if reassessed['failures'] or not reassessed['records']:
        raise EvidenceError('validated_nonempty_parent_records_required')
    values = snapshot(parent)
    spec = parent_plan(c12)
    pages = []
    rows = []
    for index in range(observed['request_attempts']):
        stem = f'parent-{index + 1:03d}'
        meta = strict_json(values[stem + '.json'].data)
        body = values.get(stem + '.body')
        if not _metadata(meta['response'], None if body is None else body.data):
            raise EvidenceError('unusable_parent_pagination_anchor')
        parsed = parse(body.data, request(spec, index + 1), spec)
        pages.append((index + 1, parsed['has_next'], tuple(parsed['fingerprints'])))
        rows.extend(parsed['rows'])
        if not parsed['has_next'] and index + 1 != observed['request_attempts']:
            raise EvidenceError('parent_anchor_after_terminal')
    if len({r['id'] for r in rows}) != len(rows) or [r['action_date'] for r in rows] != sorted(r['action_date'] for r in rows):
        raise EvidenceError('conflicting_parent_pagination_anchor')
    return observed, spec, pages


def plan(parent, c12, *, limits=None, label='bounded-parent-continuation'):
    limits = ContinuationLimits() if limits is None else limits
    if type(limits) is not ContinuationLimits:
        raise EvidenceError('typed_continuation_limits_required')
    if type(label) is not str:
        raise EvidenceError('literal_acquisition_label_required')
    _text(label, 'acquisition label')
    if len(label) > 80:
        raise EvidenceError('bounded_nonsecret_acquisition_label_required')
    old, spec, pages = baseline(parent, c12)
    if not pages[-1][1]:
        raise EvidenceError('no_observed_next_page_obligation')
    start = pages[-1][0] + 1
    value = {'schema_type': 'ParentContinuationPlan', 'schema_version': 1, 'rule_version': RULE,
        'label': label, 'profile': old['profile'], 'source_allowlist': ['usaspending'],
        'parent_inventory_sha256': old['inventory_sha256'],
        'C12_inventory_sha256': old['base_C12_inventory_sha256'],
        'selection': old['selection'], 'capture_contract_version': 1,
        'parent_capture_contract_version': old['capture_contract_version'],
        'record_contract_version': 2, 'start_page': start, 'page_size': 5,
        'limits': limits.to_dict(), 'retries': 0, 'redirects': False, 'pace_seconds': 1.0,
        'timeout_seconds': 10.0, 'max_response_bytes': 1048576,
        'planned_requests': [request(spec, p) for p in range(start, start + min(limits.max_requests, limits.max_records // 5))],
        'config': {'max_run_bytes': 8 * 1024 * 1024}}
    return {**value, 'acquisition_id': 'parent-continuation:v1:' + digest(value)}


def collect(path, parent, c12, *, live=False, synthetic=None, limits=None, label='bounded-parent-continuation'):
    value = plan(parent, c12, limits=limits, label=label)
    if type(live) is not bool:
        raise EvidenceError('explicit_continuation_mode_required')
    if live:
        if value['profile'] != 'live' or synthetic is not None:
            raise EvidenceError('live_continuation_requires_live_bound_anchor')
    elif value['profile'] != 'synthetic' or synthetic is None:
        raise EvidenceError('offline_default_no_continuation_access')
    if synthetic is not None:
        if type(synthetic) is not dict or type(synthetic.get('responses')) is not list or len(synthetic['responses']) > len(value['planned_requests']):
            raise EvidenceError('bounded_continuation_transcript_required')
        transport = FixtureTransport(synthetic)
    outside(path, (parent, c12))
    before = (manifest(parent), manifest(c12))
    spec = parent_plan(c12)
    with PilotStore(path, value) as store:
        if live:
            transport = HTTPTransport(CollectionLimits(retries=0, timeout_seconds=10.0,
                pace_seconds=1.0, max_response_bytes=1048576).to_dict())
        for index, req in enumerate(value['planned_requests']):
            stem = f'continuation-{index + 1:03d}'
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
                'representation': 'HTTP_entity_bytes_after_content_decoding' if live else 'synthetic_transcript_bytes'})
            if not _metadata(meta, raw):
                break
            try:
                page = parse(raw, req, spec)
            except (ValueError, KeyError, TypeError):
                break
            if not page['has_next']:
                break
        if (manifest(parent), manifest(c12)) != before:
            raise EvidenceError('continuation_anchor_changed')
        store.write('continuation-commit.json', {'schema_version': 1, 'files': store.inventory()})
    return read(path, parent, c12)


def read(path, parent, c12):
    values = snapshot(path)
    hashes = {n: s.byte_sha256 for n, s in values.items()}
    if 'continuation-commit.json' not in values:
        raise EvidenceError('interrupted_continuation_preserve_do_not_resume')
    saved = strict_json(values['pilot-plan.json'].data)
    expected = plan(parent, c12, limits=ContinuationLimits.from_dict(saved['limits']), label=saved['label'])
    commit = {'schema_version': 1, 'files': {n: h for n, h in hashes.items() if n != 'continuation-commit.json'}}
    if values['pilot-plan.json'].data != (canonical(expected) + '\n').encode() or values['continuation-commit.json'].data != (canonical(commit) + '\n').encode():
        raise EvidenceError('continuation_manifest_or_plan_conflict')
    old, spec, pages = baseline(parent, c12)
    names = {'pilot-plan.json', 'continuation-commit.json'}
    rows, failures = [], []
    following = True
    attempts = 0
    for index, req in enumerate(expected['planned_requests']):
        stem = f'continuation-{index + 1:03d}'
        if not following:
            if any(n.startswith(stem) for n in values):
                raise EvidenceError('continuation_after_terminal_or_failed_page')
            continue
        if stem + '.json' not in values or stem + '-reservation.json' not in values:
            raise EvidenceError('missing_continuation_request_history')
        names |= {stem + '.json', stem + '-reservation.json'}
        attempts += 1
        if values[stem + '-reservation.json'].data != (canonical({'sequence': index, 'request': req}) + '\n').encode():
            raise EvidenceError('continuation_reservation_scope_conflict')
        meta = strict_json(values[stem + '.json'].data)
        body = values.get(stem + '.body')
        if body is not None:
            names.add(stem + '.body')
        representation = 'HTTP_entity_bytes_after_content_decoding' if expected['profile'] == 'live' else 'synthetic_transcript_bytes'
        if (set(meta) != {'request', 'response', 'body_sha256', 'representation'}
            or canonical(meta['request']) != canonical(req) or meta['representation'] != representation
            or meta['body_sha256'] != (None if body is None else body.byte_sha256)):
            raise EvidenceError('continuation_response_provenance_conflict')
        cite = {'source': 'usaspending', 'request': req, 'metadata_file': stem + '.json',
            'metadata_sha256': values[stem + '.json'].byte_sha256,
            'body_file': None if body is None else stem + '.body', 'body_sha256': meta['body_sha256'],
            'retrieved_at_utc': meta['response']['retrieved_at_utc'], 'source_update_raw': meta['response']['source_update_raw'],
            'representation': representation, 'acquisition_id': expected['acquisition_id']}
        if not _metadata(meta['response'], None if body is None else body.data):
            failures.append({'reason': 'continuation_source_failed_or_incomplete', 'citation': cite})
            following = False
            continue
        try:
            parsed = parse(body.data, req, spec)
        except (ValueError, TypeError, KeyError):
            failures.append({'reason': 'continuation_native_or_page_contract_rejected', 'citation': cite})
            following = False
            continue
        pages.append((req['parameters']['page'], parsed['has_next'], tuple(parsed['fingerprints'])))
        rows.extend(record(row, {**cite, 'locator': '/results/' + str(i)}) for i, row in enumerate(parsed['rows']))
        following = parsed['has_next']
    if set(values) != names or manifest(path) != hashes:
        raise EvidenceError('continuation_inventory_changed_or_extra_files')
    combined = old['record_reassessment']['records'] + rows
    ids = [r['row']['id'] for r in combined]
    dates = [r['row']['action_date'] for r in combined]
    if len(ids) != len(set(ids)):
        failures.append({'reason': 'duplicate_or_competing_native_parent_records'})
    if dates != sorted(dates):
        failures.append({'reason': 'parent_order_changed_between_captures'})
    chain = pagination(pages)
    terminal = not failures and chain['bounded_observed_chain'] == 'consistent_terminal'
    return {'schema_type': 'ParentContinuation', 'schema_version': 1, 'rule_version': RULE,
        'profile': expected['profile'], 'acquisition_id': expected['acquisition_id'],
        'acquisition_evidence_id': 'parent-continuation-evidence:v1:' + digest(hashes),
        'capture_contract_version': expected['capture_contract_version'],
        'record_contract_version': expected['record_contract_version'],
        'inventory_sha256': digest(hashes), 'parent_inventory_sha256': old['inventory_sha256'],
        'selection': expected['selection'], 'request_attempts': attempts, 'records': rows,
        'combined_pagination': chain, 'failures': failures,
        'observed_terminal_query_chain': terminal,
        'request_cap_reached': following and attempts >= expected['limits']['max_requests'],
        'acquisition_budget_exhausted': following,
        'coverage_state': 'CONFLICTING_OR_PARTIAL' if failures else 'OBSERVED_TERMINAL_CHAIN_ONLY' if terminal else 'INCOMPLETE_ACQUISITION_BUDGET',
        'historical_interval_coverage': 'unknown', 'source_query_recall': 'unknown',
        'snapshot_consistency': 'unknown', 'correction_and_deletion_completeness': 'unknown',
        'entire_contract_history_complete': 'unknown', 'historical_parent_applicability_established': False,
        'financial_comparison_authorized': False, 'replay_creates_new_observation': False}
