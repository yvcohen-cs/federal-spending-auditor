"""One-request source-native child reference binding to a preserved parent.

No parent capture is rebound, recollected, relabeled or treated as temporal
authority. Only the unchanged missing-parent-primary identity claim is eligible.
"""
import hashlib
from pathlib import Path

from .award_validation import snapshot
from .collection import CollectionLimits, SelectedAward
from .collection_sources import HTTPTransport, FixtureTransport
from .correction_reporting import report as c14_report
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .evidence_package import verified_directory, _recipe
from .parent_history_probe import read as read_parent
from .parent_continuation import read as read_continuation
from .source_verification import inspect_experiment, _metadata
from .source_contracts import detail_request, award_detail
from .pilot_store import PilotStore
from .history_preflight import freshness
from .review_packet_io import outside

RULE = 'source-native-parent-primary-binding-v1'
REASON = ['parent_award_primary_record_not_observed']
PARENT_DOCUMENTATION = {
    'url': 'https://raw.githubusercontent.com/fedspendingtransparency/usaspending-api/c2b82690eb044e130afc80b546343a2af0b4af1a/usaspending_api/api_contracts/contracts/v2/awards/award_id.md',
    'body_sha256': '05ccfd684124aa0a0eac0ddbe00eaf1b4da4cf28ee1234e568e321eb24c59974',
    'section': 'ParentDetails',
    'fields': ['generated_unique_award_id', 'piid', 'sub_agency_id'],
    'claim_scope': 'current_source_local_identity_reference_not_historical_applicability'}


def c14_case(case):
    return {k: v for k, v in case.items() if k not in ('authority_binding', 'continuation')}


def parent_sources(root, verification):
    cases, _, _ = _recipe(root, 'C15')
    sources = []
    for case in cases:
        if not case.get('parent_history') or not case.get('c12_capture'):
            continue
        current = inspect_experiment(case['c12_capture'])
        parent = read_parent(case['parent_history'], case['c12_capture'])
        if current['current_source_parent_link'] != 'verified_source_local_summary_link' or parent['record_reassessment']['failures']:
            continue
        records = [(case['parent_history'], r) for r in parent['record_reassessment']['records']]
        cont = None
        if case.get('continuation'):
            cont = read_continuation(case['continuation'], case['parent_history'], case['c12_capture'])
            if cont['failures']:
                continue
            records += [(case['continuation'], r) for r in cont['records']]
        if not records:
            continue
        observations = []
        for path, r in records:
            cite = r['citation']
            observations.append({'source_native_record_id': r['row']['id'], 'native_action_components': r['native_action_components'],
                'modification_number': r['row']['modification_number'], 'action_date': r['row']['action_date'],
                'evidence': {**cite, 'archive_sha256': verification['archive_sha256'],
                    'package_body_member': (Path(path).relative_to(root) / cite['body_file']).as_posix(),
                    'package_metadata_member': (Path(path).relative_to(root) / cite['metadata_file']).as_posix()}})
        source_files = snapshot(case['c12_capture'])
        summary = current['parent']
        source = {'profile': parent['profile'], 'source': 'usaspending',
            'source_native_parent_id': summary['native_award_id'], 'parent_piid': summary['piid'],
            'parent_identity_agency': parent['selection']['agency_id'], 'parent_instrument': summary['instrument_type'],
            'package_archive_sha256': verification['archive_sha256'],
            'parent_capture_inventory_sha256': parent['inventory_sha256'],
            'parent_capture_contract_version': parent['capture_contract_version'],
            'parent_record_reassessment_version': parent['record_reassessment']['rule_version'],
            'original_parent_capture_failures': parent['failures'],
            'summary_evidence': {'source': 'usaspending',
                'package_body_member': (Path(case['c12_capture']).relative_to(root) / 'detail-001.body').as_posix(),
                'body_sha256': source_files['detail-001.body'].byte_sha256,
                'response_metadata': strict_json(source_files['detail-001.json'].data),
                'observed_parent_summary': summary},
            'record_observations': observations,
            'observed_query_chain': None if cont is None else cont['combined_pagination'],
            'historical_applicability': 'unknown', 'new_source_observations_on_replay': 0}
        sources.append(source)
    return sources


def candidate_plan(case, verification, sources):
    if len(case.get('collections', ())) != 1:
        raise EvidenceError('one_original_native_collection_required')
    root = case['collections'][0]
    values = snapshot(root)
    old_plan = strict_json(values['c3_plan.json'].data)
    if len(old_plan['awards']) != 1:
        raise EvidenceError('one_original_award_selection_required')
    selected = SelectedAward.from_dict(old_plan['awards'][0])
    if any(getattr(selected, k) is None for k in ('generated_id', 'piid', 'agency_id', 'parent_piid', 'parent_agency_id')):
        raise EvidenceError('complete_original_child_and_parent_selection_required')
    old = c14_report([c14_case(case)])
    target = old['cases'][0]
    eligible = [p for p in target['original_requirement_impacts'] if p['dimension'] == 'parent_identity'
        and p['native_context'].get('namespace') == 'usaspending'
        and p['original_requirement']['status'] == 'INSUFFICIENT_EVIDENCE'
        and p['original_requirement']['evidence_kind'] == 'missing_evidence'
        and p['original_requirement']['reasons'] == REASON and not p['original_requirement_resolved']
        and [p['native_context'].get(k) for k in ('piid', 'agency', 'parent_piid', 'parent_agency')] ==
            [selected.piid, selected.agency_id, selected.parent_piid, selected.parent_agency_id]]
    nodes = [n for n in target['observation_graph']['nodes'] if n['source'] == 'usaspending'
        and strict_json(n['citation_json'].encode())['input_role'] == 'original_C10_primary'
        and [strict_json(n['native_context_json'].encode()).get(k) for k in ('piid', 'agency', 'parent_piid', 'parent_agency')] ==
            [selected.piid, selected.agency_id, selected.parent_piid, selected.parent_agency_id]]
    if len(eligible) != 1 or not nodes or not all(n['identity_supported'] and n['existing_native_scope_verified'] and not n['outside_requested_context'] for n in nodes):
        raise EvidenceError('exact_original_unresolved_parent_primary_requirement_required')
    matches = [s for s in sources if (s['parent_piid'], s['parent_identity_agency'], s['profile']) ==
        (selected.parent_piid, selected.parent_agency_id, old['profile'])]
    if len(matches) != 1:
        raise EvidenceError('unique_verified_parent_source_context_required')
    source = matches[0]
    # Literal native components in the parent's own records, not agency aliases.
    if not source['record_observations'] or not all(
        [r['native_action_components']['piid']['value'], r['native_action_components']['agency']['value']] ==
        [selected.parent_piid, selected.parent_agency_id] for r in source['record_observations']):
        raise EvidenceError('parent_primary_native_pair_conflict')
    return {'schema_type': 'AuthorityBindingPlan', 'schema_version': 1, 'rule_version': RULE,
        'profile': old['profile'], 'selection': selected.to_dict(),
        'original_case_sha256': target['original_case_sha256'],
        'original_requirement_id': eligible[0]['original_plan_id'],
        'previous_requirement': eligible[0]['original_requirement'],
        'original_collection_inventory_sha256': digest({n: s.byte_sha256 for n, s in values.items()}),
        'original_child_node_ids': sorted(n['node_id'] for n in nodes),
        'parent_package_archive_sha256': verification['archive_sha256'],
        'source_native_parent_id': source['source_native_parent_id'],
        'parent_source_evidence_sha256': digest(source),
        'source_allowlist': ['usaspending'], 'source_contract_reference': PARENT_DOCUMENTATION,
        'request': detail_request(selected.generated_id),
        'maximum_requests': 1, 'maximum_summary_records': 1,
        'retries': 0, 'redirects': False, 'pace_seconds': 1.0,
        'timeout_seconds': 10.0, 'max_response_bytes': 1048576,
        'capture_contract_version': 1, 'config': {'max_run_bytes': 4 * 1024 * 1024}}


def plan(case, baseline_package):
    with verified_directory(baseline_package, expected_phase='C15') as (root, verified):
        return candidate_plan(case, verified, parent_sources(root, verified))


def collect(path, case, baseline_package, *, live=False, synthetic=None):
    value = plan(case, baseline_package)
    if type(live) is not bool:
        raise EvidenceError('explicit_binding_mode_required')
    if live:
        if value['profile'] != 'live' or synthetic is not None:
            raise EvidenceError('live_binding_requires_live_primary_context')
    elif value['profile'] != 'synthetic' or synthetic is None:
        raise EvidenceError('offline_default_no_binding_access')
    if synthetic is not None:
        if type(synthetic) is not dict or type(synthetic.get('responses')) is not list or len(synthetic['responses']) != 1:
            raise EvidenceError('one_response_synthetic_transcript_required')
        transport = FixtureTransport(synthetic)
    protected = list(case.get('collections', ())) + list(case.get('sam_captures', ())) + [baseline_package]
    protected += [case[k] for k in ('c12_capture', 'historical_probe', 'parent_history', 'continuation', 'report') if case.get(k)]
    outside(path, protected)
    with PilotStore(path, value) as store:
        if live:
            transport = HTTPTransport(CollectionLimits(retries=0, timeout_seconds=10.0,
                pace_seconds=1.0, max_response_bytes=1048576).to_dict())
        req = value['request']
        store.write('binding-001-reservation.json', {'sequence': 0, 'request': req})
        meta, raw = transport(req, 0)
        if raw is not None and len(raw) > 1048576:
            raw = raw[:1048576]
            meta = {**meta, 'body_complete': False, 'error_code': 'response_size_limit'}
        if raw is not None:
            store.write_bytes('binding-001.body', raw)
        store.write('binding-001.json', {'request': req, 'response': meta,
            'body_sha256': None if raw is None else hashlib.sha256(raw).hexdigest(),
            'representation': 'HTTP_entity_bytes_after_content_decoding' if live else 'synthetic_transcript_bytes'})
        _metadata(meta, raw)
        if plan(case, baseline_package) != value:
            raise EvidenceError('binding_primary_context_changed_during_acquisition')
        store.write('binding-commit.json', {'schema_version': 1, 'files': store.inventory()})
    return read(path, case, baseline_package)


def read(path, case, baseline_package, *, expected_plan=None):
    value = plan(case, baseline_package) if expected_plan is None else expected_plan
    files = snapshot(path)
    hashes = {n: s.byte_sha256 for n, s in files.items()}
    if 'binding-commit.json' not in files:
        raise EvidenceError('interrupted_binding_capture_preserve_no_repair')
    required = {'pilot-plan.json', 'binding-001-reservation.json', 'binding-001.json', 'binding-commit.json'}
    body = files.get('binding-001.body')
    if body is not None:
        required.add('binding-001.body')
    commit = {'schema_version': 1, 'files': {n: h for n, h in hashes.items() if n != 'binding-commit.json'}}
    if (set(files) != required or files['pilot-plan.json'].data != (canonical(value) + '\n').encode()
        or files['binding-commit.json'].data != (canonical(commit) + '\n').encode()
        or files['binding-001-reservation.json'].data != (canonical({'sequence': 0, 'request': value['request']}) + '\n').encode()):
        raise EvidenceError('binding_manifest_plan_or_request_conflict')
    meta = strict_json(files['binding-001.json'].data)
    representation = 'HTTP_entity_bytes_after_content_decoding' if value['profile'] == 'live' else 'synthetic_transcript_bytes'
    if (set(meta) != {'request', 'response', 'body_sha256', 'representation'} or meta['request'] != value['request']
        or meta['representation'] != representation or meta['body_sha256'] != (None if body is None else body.byte_sha256)):
        raise EvidenceError('binding_response_provenance_conflict')
    okay = _metadata(meta['response'], None if body is None else body.data) and meta['response']['status'] == 200
    observed, failures = None, []
    if okay:
        try:
            selected = SelectedAward.from_dict(value['selection'])
            observed = award_detail(body.data, selected.generated_id, selected.piid)
            parent = observed['parent']
            if (parent['state'] != 'observed_parent_reference' or
                [parent.get(k) for k in ('generated_unique_award_id', 'piid', 'sub_agency_id')] !=
                [value['source_native_parent_id'], selected.parent_piid, selected.parent_agency_id]):
                failures.append('source_child_parent_reference_conflict_or_missing')
        except (ValueError, TypeError, KeyError):
            failures.append('unsupported_child_summary_identity_or_instrument')
    else:
        failures.append('child_summary_source_failed_or_incomplete')
    update = freshness([{'retrieved_at_utc': meta['response']['retrieved_at_utc'],
        'source_update_raw': meta['response']['source_update_raw'], 'body_sha256': meta['body_sha256']}])
    if update['status'] == 'CONFLICTING_METADATA':
        failures.append('contradictory_source_update_metadata')
    if {n: s.byte_sha256 for n, s in snapshot(path).items()} != hashes:
        raise EvidenceError('binding_capture_changed_during_replay')
    return {'schema_type': 'AuthorityBindingObservation', 'schema_version': 1,
        'rule_version': RULE, 'profile': value['profile'], 'plan': value,
        'capture_inventory_sha256': digest(hashes), 'request_attempts': 1,
        'claim_status': 'VERIFIED_SOURCE_LOCAL_REFERENCE' if not failures else 'UNRESOLVED_SOURCE_BINDING',
        'observed_child_summary': observed, 'failures': failures, 'freshness': update,
        'citation': {'source': 'usaspending', 'request': value['request'],
            'body_file': None if body is None else 'binding-001.body', 'body_sha256': meta['body_sha256'],
            'metadata_file': 'binding-001.json', 'metadata_sha256': files['binding-001.json'].byte_sha256,
            'retrieved_at_utc': meta['response']['retrieved_at_utc'],
            'source_update_raw': meta['response']['source_update_raw'], 'representation': representation},
        'historical_parent_applicability_established': False,
        'financial_comparison_authorized': False, 'replay_creates_new_observation': False}
