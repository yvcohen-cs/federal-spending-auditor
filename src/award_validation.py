"""Offline claim diagnostics over preserved native evidence; never a money gate.

C9 v1 deliberately leaves source namespaces separate. Content equality is a
retrieval diagnostic, never an award identifier or a revision certificate.
"""
import argparse
from collections import defaultdict
from html import escape

from .collection_sources import parse_page
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .history_ingestion import reconstruct
from .history_rules import native_key
from .history_reporting import bounded_json
from .scope_models import FIELDS, ScopeRequest
from .sam_semantics_reporting import report as sam_report

VERSION = 'award-source-validation-v1'
BOUNDARY = {'financial_authorization_changed': False, 'production_readiness_changed': False,
            'live_collection_enabled': False, 'real_participant_operations_enabled': False}


def snapshot(path):
    with EvidenceRoot(path, max_total_bytes=64*1024*1024) as root:
        values = {n: root.read(n) for n in root.discover()}
        if {n: root.read(n, recheck=True).byte_sha256 for n in root.discover()} != {n: s.byte_sha256 for n, s in values.items()}:
            raise EvidenceError('award_validation_source_changed')
    return values


def pagination(pages):
    """Validate an observed one-origin chain, independently of query recall.

    Each input is (page index, has-next, canonical record content hashes).
    No rows, contiguous pages, or repeated content proves historical completeness.
    Variant successful responses to one page remain contradictory alternatives.
    """
    by_page = defaultdict(set); seen = set(); issues = set(); occurrences = 0
    for index, following, hashes in pages:
        if type(index) is not int or not 1 <= index <= 10000 or type(following) is not bool:
            raise EvidenceError('invalid_validation_page')
        if not isinstance(hashes, tuple) or len(hashes) > 1000:
            raise EvidenceError('invalid_validation_page_contents')
        for sha in hashes:
            if type(sha) is not str or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                raise EvidenceError('invalid_validation_content_hash')
        by_page[index].add((following, hashes)); occurrences += len(hashes)
        if following and not hashes:
            issues.add('empty_nonterminal_page')
    for index, variants in sorted(by_page.items()):
        if len(variants) > 1:
            issues.add('contradictory_successful_page_observations')
        for following, hashes in sorted(variants):
            if len(set(hashes)) != len(hashes) or seen.intersection(hashes):
                issues.add('duplicate_or_overlapping_record_content')
            seen.update(hashes)
            if index != max(by_page) and not following:
                issues.add('observations_after_terminal_page')
    if by_page and sorted(by_page) != list(range(1, max(by_page)+1)):
        issues.add('missing_observed_page')
    if by_page and any(f for f, _ in by_page[max(by_page)]):
        issues.add('nonterminal_observed_chain')
    if not occurrences:
        issues.add('empty_observation_query_support_and_scope_unverified')
    return {'observed_pages': sorted(by_page), 'record_occurrences': occurrences,
            'distinct_record_contents': len(seen), 'issues': sorted(issues),
            'bounded_observed_chain': 'consistent_terminal' if by_page and not issues else 'unresolved',
            'query_recall': 'unknown', 'transaction_history_complete': 'unknown', 'source_wide_complete': 'unknown'}


def collection_pagination(values):
    plan = strict_json(values['c3_plan.json'].data)
    results = []
    for source in plan['sources']:
        pages = []; refs = []; issues = set(); contexts = []
        for name, snap in sorted(values.items()):
            if not name.startswith('c3_attempt_') or not name.endswith('.json'):
                continue
            meta = strict_json(snap.data); req = meta['request']
            if req['source'] != source:
                continue
            body_name = name[:-5]+'.body'
            refs.append({'metadata_path': name, 'metadata_sha256': snap.byte_sha256,
                         'body_path': body_name if body_name in values else None,
                         'body_sha256': values[body_name].byte_sha256 if body_name in values else None})
            if meta['error_code'] or not meta['body_complete'] or meta['status'] is None or not 200 <= meta['status'] < 300 or body_name not in values:
                issues.add('failed_or_unavailable_attempt_preserved'); continue
            try:
                page = parse_page(source, values[body_name].data, req, plan['awards'][0])
                pages.append((req['page_index'], page['has_next'], tuple(page['fingerprints'])))
                contexts.extend({'body_path': body_name, 'body_sha256': values[body_name].byte_sha256,
                    'row_index': i, 'request_json': canonical(req['parameters']), 'context': c} for i, c in enumerate(page['contexts']))
            except (ValueError, KeyError, TypeError):
                issues.add('unsupported_page_or_continuation')
        result = pagination(pages)
        if issues:
            result['bounded_observed_chain'] = 'unresolved'
        result.update(source=source, issues=sorted(set(result['issues']) | issues), evidence=refs, record_contexts=contexts)
        results.append(result)
    return results


def validate(collections=(), requested=None, *, sam_captures=()):
    """Revalidate primary captures and bind diagnostics to their inventories.

    At most eight C3 roots and three C2 SAM roots; no network, credentials,
    inferred source identity, financial totals, or readiness upgrades.
    """
    collections = tuple(collections); sam_captures = tuple(sam_captures)
    if len(collections) > 8 or len(sam_captures) > 3 or not (collections or sam_captures):
        raise EvidenceError('bounded_nonempty_validation_inputs_required')
    if collections and not isinstance(requested, ScopeRequest):
        raise EvidenceError('explicit_native_scope_required')
    paths = collections + sam_captures
    snapshots = [snapshot(p) for p in paths]
    profiles = set()
    for values in snapshots[:len(collections)]:
        plan = strict_json(values['c3_plan.json'].data)
        profiles.add('synthetic' if plan['profile'].startswith('fixture:') else plan['profile'])
        for name, saved in values.items():
            if name.startswith('c3_attempt_') and name.endswith('.json'):
                meta = strict_json(saved.data); body = values.get(name[:-5]+'.body')
                if body is not None and meta['body_sha256'] != body.byte_sha256:
                    raise EvidenceError('award_validation_provenance_hash_conflict')
    manifests = [{n: s.byte_sha256 for n, s in v.items()} for v in snapshots]
    if len({digest(m) for m in manifests}) != len(manifests):
        raise EvidenceError('duplicate_validation_inventory')
    records = []; page_reports = []; comparisons = []; artifact_issues = []
    if collections:
        run = reconstruct(collections, requested)
        for index, values in enumerate(snapshots[:len(collections)]):
            page_reports.append({'input_index': index, 'sources': collection_pagination(values)})
        for source_run in run.inputs:
            artifact_issues.extend(source_run.artifact_issues)
        for o in run.observations:
            a = o.scope_assessment; gaps = set(o.issues) | set(a.missing_prerequisites)
            if not o.eligible:
                gaps.add('identity_or_parent_scope_unresolved')
            if native_key(o) is None:
                gaps.add('native_action_context_incomplete')
            if not o.money:
                gaps.add('no_supported_monetary_observation')
            gaps.update(('authoritative_revision_alignment_missing', 'freshness_semantics_unverified', 'complete_history_not_established'))
            source_contexts = [c['context'] for report in page_reports for page in report['sources']
                if page['source'] == a.evidence.reference.source for c in page['record_contexts']
                if c['body_sha256'] == a.evidence.artifact.sha256 and c['body_path'] == a.evidence.artifact.relative_path
                and c['request_json'] == a.evidence.artifact.request_json
                and c['row_index'] == int(a.evidence.reference.locator.split('/')[-1])
                ] if a.evidence.reference.source == 'usaspending' else []
            for context in source_contexts:
                if context != 'query_bound_candidate':
                    gaps.add('source_record_context_'+context)
            records.append({'source': a.evidence.reference.source, 'observation_id': o.history_observation_id,
                'native_context': {f: getattr(a.observed, f).to_dict() for f in FIELDS},
                'source_record_contexts': sorted(set(source_contexts)),
                'diagnostic_context_status': 'conflicting' if 'nonmatching_award_identifier' in source_contexts else 'insufficient' if any(c != 'query_bound_candidate' for c in source_contexts) else 'not_independently_certified',
                'scope_status': a.status.value, 'parent_status': a.parent_state,
                'content_sha256': a.content_sha256, 'citation': a.evidence.to_dict(),
                'action_key': list(native_key(o)) if native_key(o) is not None else None,
                'eligible_for_existing_comparison': o.eligible,
                'observed_money_fields': [m.observation.to_dict() for m in o.money], 'gaps': sorted(gaps)})
        comparisons = [{'claim_id': c.claim_id, 'status': c.status.value, 'reasons': list(c.reasons)} for c in run.comparisons]
    sam = sam_report(sam_captures) if sam_captures else None
    if sam:
        profiles.add(sam['profile'])
        for capture in sam['captures']:
            for r in capture['records']:
                records.append({'source': 'samgov', 'observation_id': r['claim_id'],
                    'native_award': r['returned_native_award'], 'native_action': r['returned_native_action'],
                    'scope_status': r['scope'], 'parent_status': r['parent'], 'citation': r['citation'],
                    'action_key': None, 'gaps': ['sam_cross_source_namespace_mapping_unverified',
                        'authoritative_revision_alignment_missing', 'complete_history_not_established',
                        'sam_financial_field_semantics_unverified'], 'observed_fields': r['source_field_observations']})
    if len(profiles) > 1:
        raise EvidenceError('mixed_source_evidence_profiles_forbidden')
    # Same-source variants and missing *observed* cross-source counterparts.
    groups = defaultdict(list)
    for r in records:
        if r['action_key'] is not None:
            groups[tuple(r['action_key'])].append(r)
    action_groups = []
    for key, rows in sorted(groups.items()):
        sources = {r['source'] for r in rows}; variants = {}
        for source in sorted(sources):
            variants[source] = sorted({r['content_sha256'] for r in rows if r['source'] == source})
            if len(variants[source]) > 1:
                for r in rows:
                    if r['source'] == source:
                        r['gaps'] = sorted(set(r['gaps']) | {'same_native_action_variant_content_unresolved'})
        missing = sorted({'usaspending', 'fpds'} - sources)
        if missing:
            for r in rows:
                r['gaps'] = sorted(set(r['gaps']) | {'counterpart_not_observed_not_proven_absent'})
        action_groups.append({'constructed_group_id': 'observed-native-action:v1:'+digest(key),
            'native_components': list(key), 'sources_observed': sorted(sources), 'missing_observed_sources': missing,
            'content_variants_by_source': variants, 'observation_ids': sorted(r['observation_id'] for r in rows),
            'revision_relationship': 'unknown', 'identity_claim': 'observed_native_components_not_verified_cross_source_match'})
    for path, manifest in zip(paths, manifests):
        if {n: s.byte_sha256 for n, s in snapshot(path).items()} != manifest:
            raise EvidenceError('award_validation_source_changed')
    return {'schema_type': 'AwardSourceValidation', 'schema_version': 1, 'rule_version': VERSION,
        'inputs': [{'input_index': i, 'inventory_sha256': digest(m), 'files': m} for i, m in enumerate(manifests)],
        'profile': next(iter(profiles), 'unknown'),
        'requested': requested.to_dict() if requested is not None else None,
        'records': sorted(records, key=lambda r: (r['source'], r['observation_id'])), 'action_groups': action_groups,
        'pagination': page_reports, 'existing_comparison_assessments': comparisons,
        'artifact_issues': sorted(set(artifact_issues)), 'sam_assessment': sam,
        'gap_counts': {g: sum(g in r['gaps'] for r in records) for g in sorted({g for r in records for g in r['gaps']})},
        'financial_arithmetic': 'withheld_by_this_diagnostic', 'restrictions': dict(BOUNDARY),
        'interpretation': 'Narrow observed evidence only. Missing counterparts are not proven absent; differences are not misconduct.'}


def markdown(value):
    # JSON strings escape control characters and keep identifiers visibly literal.
    lines = ['# Offline award source validation v1', '', 'No financial or readiness authorization.', '',
             '## Evidence gaps', '', '| Proof obligation | Observed records blocked |', '| --- | ---: |']
    for gap, count in sorted(value.get('gap_counts', {}).items()):
        lines.append('| '+canonical(gap).replace('|', '\\u007c').replace('`', '\\u0060')+' | '+str(count)+' |')
    lines.extend(('', '## Preserved evidence and deterministic diagnostics', '', '```json',
                  canonical(value).replace('`', '\\u0060'), '```', ''))
    return '\n'.join(lines)


def html(value):
    return '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Offline award validation</title><h1>Offline award source validation</h1><pre>'+escape(markdown(value))+'</pre>\n'


def write_report(path, value, *, protected=()):
    from .pilot_store import PilotStore
    from .review_packet_io import outside
    outside(path, protected)
    with PilotStore(path, {'schema_type': 'AwardValidationPlan', 'schema_version': 1,
                          'config': {'max_run_bytes': 128*1024*1024}, 'rule_version': VERSION}) as store:
        store.write_bytes('validation.json', bounded_json(value))
        store.write_bytes('validation.md', markdown(value).encode())
        store.write_bytes('validation.html', html(value).encode())
        store.write('validation-commit.json', {'schema_version': 1, 'files': store.inventory(), 'report_sha256': digest(value)})
    return digest(value)


def read_report(path):
    values = snapshot(path)
    if set(values) != {'pilot-plan.json', 'validation.json', 'validation.md', 'validation.html', 'validation-commit.json'}:
        raise EvidenceError('incomplete_validation_report')
    commit = strict_json(values['validation-commit.json'].data)
    actual = {n: s.byte_sha256 for n, s in values.items() if n != 'validation-commit.json'}
    value = strict_json(values['validation.json'].data)
    if (values['validation-commit.json'].data != (canonical(commit)+'\n').encode()
            or commit != {'schema_version': 1, 'files': actual, 'report_sha256': digest(value)}):
        raise EvidenceError('validation_report_integrity')
    if values['validation.md'].data != markdown(value).encode() or values['validation.html'].data != html(value).encode():
        raise EvidenceError('validation_projection_conflict')
    if (type(value) is not dict or value.get('schema_type') != 'AwardSourceValidation' or type(value.get('schema_version')) is not int
            or value['schema_version'] != 1 or value.get('rule_version') != VERSION
            or canonical(value.get('restrictions')) != canonical(BOUNDARY)):
        raise EvidenceError('unsupported_validation_report')
    return value


def verify_report(path, collections=(), requested=None, *, sam_captures=()):
    """Hashes detect corruption, not authenticity; replay primary inputs to trust claims."""
    saved = read_report(path)
    if canonical(saved) != canonical(validate(collections, requested, sam_captures=sam_captures)):
        raise EvidenceError('validation_primary_replay_conflict')
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline preserved award evidence diagnostics; no collection or financial authorization.')
    parser.add_argument('--collection', action='append', default=[])
    parser.add_argument('--sam-capture', action='append', default=[])
    parser.add_argument('--scope', help='JSON ScopeRequest; required for C3 collections')
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    try:
        from .review_packet_io import outside
        protected = tuple(args.collection + args.sam_capture + ([args.scope] if args.scope else []))
        outside(args.output, protected)
        scope = None
        if args.scope:
            from .collect_evidence import load_input
            scope = ScopeRequest.from_dict(load_input(args.scope))
        value = validate(args.collection, scope, sam_captures=args.sam_capture)
        sha = write_report(args.output, value, protected=protected)
        print(canonical({'report_sha256': sha, 'financial_arithmetic': 'withheld', 'output_complete': True}))
        return 0
    except (ValueError, TypeError, KeyError, IndexError, OSError):
        print(canonical({'error_code': 'offline_award_validation_blocked'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
