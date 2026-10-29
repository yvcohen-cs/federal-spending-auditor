"""Phase 4C3 deterministic projections of independently revalidated C2 journals."""
from html import escape
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .history_reporting import bounded_json
from .pilot_store import PilotStore
from .review_packet_io import outside
from .sam_validation_reporting import report as c2_report
from .sam_validation_models import SAMObservedRecord
from .sam_pagination_assessment import PaginationObservation, assess as assess_pagination
from .sam_historical_assessment import assess as assess_history

DOCS = Path(__file__).resolve().parents[1] / 'docs'
PROTOCOL_SHA = 'e0a0efc4d2c291e2209750fcc84fa297c4f3987334356306e6f127004c8ed0c7'
MATRIX_SHA = '5c34d128a5c49ed7b7d51923072cba5a17f0eeb36eecb47e77fbd5e88d417b2d'
ACCESS = ('not_checked_offline_no_credential_read', 'unavailable_no_configured_credential',
    'configured_material_present_not_authenticated')


def pinned(name, sha):
    value = strict_json((DOCS / name).read_bytes())
    if digest(value) != sha:
        raise EvidenceError('sam_semantics_versioned_document_changed')
    return value


def snapshot(path):
    with EvidenceRoot(path, max_bytes=2*1024*1024, max_total_bytes=32*1024*1024, max_files=60) as root:
        data = {n: root.read(n) for n in root.discover()}
        hashes = {n: s.byte_sha256 for n, s in data.items()}
        if {n: root.read(n, recheck=True).byte_sha256 for n in root.discover()} != hashes:
            raise EvidenceError('sam_semantics_source_changed')
    return data, hashes


def capture_report(path):
    before, hashes = snapshot(path)
    # No salvaged positive claims from unfinished or tampered journals. Preserve
    # their inventory and report unavailable counts instead of inventing zeros.
    try:
        value = c2_report(path, access='offline_capture_replay_no_credential_read')
    except (ValueError, TypeError, KeyError, IndexError):
        state = 'incomplete_or_interrupted_capture' if 'sam-research-commit.json' not in before else 'invalid_evidence_integrity_or_controls'
        _, after = snapshot(path)
        if hashes != after:
            raise EvidenceError('sam_semantics_source_changed')
        return {'state': state, 'inventory_sha256': digest(hashes), 'profile': 'untrusted_unknown',
            'metrics': None, 'pagination': [], 'records': [], 'requests': [],
            'blockers': ['primary_capture_not_revalidated_no_positive_claims_no_automatic_resume']}, ()
    profile = value['profile']; observations = {}; records = []
    requests = value['request_evidence']
    for attempt in requests:
        meta = attempt['metadata']; name = attempt['relative_path']; body_name = name[:-5]+'.body'
        raw = strict_json(before[body_name].data) if body_name in before else None
        counters = {k: raw[k] for k in ('offset', 'limit', 'totalRecords') if k in raw} if isinstance(raw, dict) else None
        # Only source row objects with validated SAM schemas enter identity/history.
        parsed = next((p['page'] for p in value['pages'] if p['subject_index']==meta['subject_index'] and p['page_index']==meta['page_index']), None)
        rows = [SAMObservedRecord.from_dict(r) for r in parsed['records']] if parsed else []
        records.extend(rows)
        obs = PaginationObservation(submitted_parameters_json=canonical(meta['request']['parameters']),
            response_counters_json=canonical(counters) if counters is not None else None,
            record_content_sha256=tuple(digest(r) for r in raw['awardSummary']) if isinstance(raw, dict) and isinstance(raw.get('awardSummary'), list) and len(raw['awardSummary'])<=10 else (),
            http_status=meta['status'], response_complete=meta['body_complete'],
            error=bool(meta['error_code'] or meta['capture_rejected'] or not isinstance(raw, dict) or not isinstance(raw.get('awardSummary'), list) or len(raw['awardSummary'])>10))
        observations.setdefault(meta['subject_index'], []).append(obs)
    _, after = snapshot(path)
    if hashes != after:
        raise EvidenceError('sam_semantics_source_changed')
    identity = []
    for row in records:
        identity.append({'claim_id': row.claim_id, 'requested': row.requested.to_dict(),
            'returned_native_award': row.award.to_dict(), 'returned_native_action': row.action.to_dict(),
            'scope': row.scope.value, 'parent': row.parent_status,
            'source_native_record_identifier': {'status': 'UNKNOWN', 'reason': 'no_separate_immutable_source_record_id_validated'},
            'content_hash_basis': 'canonical_parsed_record_content_not_entity_or_revision_identity',
            'source_field_observations': [f.to_dict() for f in row.fields], 'citation': row.citation.to_dict(),
            'knowledge_state': 'SYNTHETIC_ONLY' if profile=='synthetic' else 'AUTHENTICATED_OBSERVED',
            'semantic_limit': 'native_record_assertion_only_no_common_revision_or_verified_no_parent'})
    metrics = dict(value['metrics'])
    metrics.update(HTTP_request_reservations=value['capture_result']['attempts_reserved'],
        HTTP_responses_received=sum(a['metadata']['status'] is not None for a in requests),
        complete_response_bodies=sum(a['metadata']['body_complete'] for a in requests))
    return {'state': 'revalidated_bounded_capture', 'inventory_sha256': digest(hashes),
        'c2_inventory_sha256': value['capture_inventory_sha256'], 'profile': profile, 'metrics': metrics,
        'pagination': [{'subject_index': index, 'assessment': assess_pagination(obs, profile=profile, interrupted='unexpected_schema_or_pagination' in value['artifact_issues'])} for index, obs in sorted(observations.items())],
        'records': identity, 'requests': requests, 'blockers': value['artifact_issues']}, tuple(records)


def report(captures=(), *, access='not_checked_offline_no_credential_read'):
    if access not in ACCESS or len(captures)>3:
        raise ValueError('bounded_explicit_semantics_inputs_required')
    reports = []; occurrences = []; inventories = set()
    for index, path in enumerate(captures):
        value, records = capture_report(path)
        if value['inventory_sha256'] in inventories:
            raise EvidenceError('duplicate_capture_inventory_not_independent_retrieval')
        inventories.add(value['inventory_sha256'])
        reports.append(value); occurrences.extend((index, row) for row in records)
    profiles = {r['profile'] for r in reports}
    # Never pool fixture counts with live or untrusted captures.
    if len(profiles)>1:
        raise EvidenceError('mixed_synthetic_live_or_untrusted_cohorts_forbidden')
    for path, saved in zip(captures, reports):
        if digest(snapshot(path)[1]) != saved['inventory_sha256']:
            raise EvidenceError('sam_semantics_source_changed')
    profile = next(iter(profiles), 'offline_no_capture')
    metrics = None
    if reports and all(r['metrics'] is not None for r in reports):
        metrics = {key: sum(r['metrics'][key] for r in reports) for key in
            ('HTTP_request_reservations', 'HTTP_attempted', 'HTTP_responses_received', 'HTTP_successful',
             'complete_response_bodies', 'pages_parsed', 'native_record_occurrences')}
        metrics['unit'] = 'reservations_attempt_completions_responses_pages_and_occurrences_separate_not_wire_delivery_or_population_estimates'
    return {'schema_type': 'SAMSemanticsReport', 'schema_version': 1, 'version': 'sam-semantics-report-v1',
        'protocol': pinned('sam-semantics-protocol-v1.json', PROTOCOL_SHA),
        'documentation_matrix': pinned('sam-documentation-matrix-v1.json', MATRIX_SHA),
        'profile': profile, 'credential_availability': access,
        'authenticated_access_status': 'capture_profile_declared_live_not_independently_certified' if profile=='live' else
            'blocked_no_configured_credential' if access=='unavailable_no_configured_credential' else 'not_authenticated_by_this_report',
        'authenticated_metrics': metrics if profile=='live' else None,
        'synthetic_metrics': metrics if profile=='synthetic' else None,
        'captures': reports, 'historical_evidence': assess_history(occurrences),
        'migration_recommendation': 'A. Offline prototype only' if profile!='live' else 'B. Bounded research only; no migration approval',
        'live_continuation_authorized': False, 'production_migration_authorized': False,
        'financial_eligibility_changed': False, 'readiness_upgrade': False,
        'frozen_reference': {'kind': 'separate_historical_reference_never_pooled_or_reclassified',
            'occurrences': 381, 'scope': {'verified_in_scope': 154, 'verified_out_of_scope': 88, 'ambiguous_scope': 139}},
        'manual_next_actions': [f['next_action'] for f in pinned('sam-documentation-matrix-v1.json', MATRIX_SHA)['findings']],
        'limitations': ['No authenticated observations without an approved binding and frozen native selection.',
            'Live-profile journal provenance is recorded, not cryptographic proof of remote server origin or entitlement.',
            'Hash commits detect changes against preserved inventories; a complete coherent rewrite cannot be detected without an external trust anchor.',
            'Unknown no-parent, pagination, history, revision, deletion and freshness remain unknown.',
            'Financial arithmetic is withheld. A cross-source disagreement is not an allegation of misconduct.',
            'This is a read-only research projection; source captures and existing readiness decisions remain unchanged.']}


def text_report(value):
    # Fence-free JSON sections avoid active markup and preserve native strings.
    return 'Phase 4C3 SAM evidence assessment\n\n' + '\n\n'.join(
        key+'\n\n    '+canonical(value[key]) for key in sorted(value)) + '\n'


def html_report(value):
    return '<!doctype html><meta charset="utf-8"><title>SAM evidence assessment</title><h1>SAM evidence assessment</h1><pre>'+escape(text_report(value))+'</pre>'


def output_plan():
    return {'schema_type': 'SAMSemanticsOutputPlan', 'schema_version': 1, 'protocol_sha256': PROTOCOL_SHA,
        'documentation_sha256': MATRIX_SHA, 'config': {'max_run_bytes': 32*1024*1024}}


def write_report(path, value, *, captures=()):
    if value != report(captures, access=value['credential_availability']):
        raise EvidenceError('sam_semantics_primary_projection_conflict')
    target = outside(path, captures)
    raw = bounded_json({'report': value, 'substantive_sha256': digest(value)})
    text = text_report(value).encode(); html = html_report(value).encode()
    if sum(map(len, (raw, text, html))) > 32*1024*1024:
        raise EvidenceError('sam_semantics_output_size_limit')
    with PilotStore(target, output_plan()) as store:
        store.write_bytes('sam-semantics.json', raw); store.write_bytes('sam-semantics.md', text); store.write_bytes('sam-semantics.html', html)
        store.write('sam-semantics-commit.json', {'schema_type': 'SAMSemanticsOutputCommit', 'schema_version': 1, 'files': store.inventory()})
    return digest(value)


def read_report(path, *, captures=()):
    with EvidenceRoot(path, max_bytes=32*1024*1024, max_total_bytes=32*1024*1024, max_files=5) as root:
        data = {n: root.read(n) for n in root.discover()}
        if set(data) != {'pilot-plan.json', 'sam-semantics.json', 'sam-semantics.md', 'sam-semantics.html', 'sam-semantics-commit.json'}:
            raise EvidenceError('sam_semantics_report_inventory_conflict')
        expected = {'schema_type': 'SAMSemanticsOutputCommit', 'schema_version': 1,
            'files': {n: s.byte_sha256 for n, s in data.items() if n!='sam-semantics-commit.json'}}
        if strict_json(data['sam-semantics-commit.json'].data)!=expected or strict_json(data['pilot-plan.json'].data)!=output_plan():
            raise EvidenceError('sam_semantics_report_hash_or_plan_conflict')
        doc = strict_json(data['sam-semantics.json'].data); value = doc['report']
        if value!=report(captures, access=value['credential_availability']) or doc!={'report': value, 'substantive_sha256': digest(value)}:
            raise EvidenceError('sam_semantics_report_projection_conflict')
        if data['sam-semantics.md'].data!=text_report(value).encode() or data['sam-semantics.html'].data!=html_report(value).encode():
            raise EvidenceError('sam_semantics_readable_projection_conflict')
        if {n: root.read(n, recheck=True).byte_sha256 for n in root.discover()}!={n: s.byte_sha256 for n, s in data.items()}:
            raise EvidenceError('sam_semantics_output_changed')
    return value
