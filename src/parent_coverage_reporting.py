"""C15 reproducible package, parent pagination and financial preflight reports."""
import argparse
from html import escape
from pathlib import Path

from .award_validation import snapshot
from .correction_reporting import report as c14_report, _paths as c14_paths
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .evidence_package import verify_package
from .history_preflight import coverage, freshness, monetary_preflight, parent_assessments
from .parent_continuation import read as read_continuation, collect, plan, ContinuationLimits
from .pilot_store import PilotStore
from .review_packet_io import outside

RULE = 'parent-history-coverage-v1'


def _cases(cases):
    if type(cases) not in (tuple, list) or not 1 <= len(cases) <= 24 or any(type(c) is not dict for c in cases):
        raise EvidenceError('bounded_C15_cases_required')
    if sum(bool(c.get('continuation')) for c in cases) > 2:
        raise EvidenceError('at_most_two_targeted_continuation_cases')
    if any(c.get('continuation') and not (c.get('parent_history') and c.get('c12_capture')) for c in cases):
        raise EvidenceError('continuation_requires_original_parent_and_C12')
    return tuple(cases)


def _paths(case):
    return c14_paths(case) + ([case['continuation']] if case.get('continuation') else [])


def _package_evidence(path, base, cases):
    if path is None:
        return {'status': 'NOT_SUPPLIED', 'independent_primary_replay_claimed': False}
    verified = verify_package(path, expected_phase='C14')
    if verified['profile'] != base['profile']:
        raise EvidenceError('baseline_package_profile_conflict')
    selected = []
    for binding in verified['verified_case_bindings']:
        matches = [i for i, c in enumerate(base['cases']) if c['original_case_sha256'] == binding['original_case_sha256']
            and (None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256']) == binding['parent_inventory_sha256']]
        if len(matches) != 1:
            raise EvidenceError('baseline_package_not_bound_to_original_case')
        selected.append(cases[matches[0]])
    local = c14_report([{k: v for k, v in c.items() if k != 'continuation'} for c in selected])
    if digest(local) != verified['report_sha256']:
        raise EvidenceError('packaged_and_local_primary_replays_disagree')
    return {'status': 'VERIFIED_PRIMARY_REPLAY', 'independent_primary_replay_claimed': True, **verified}


def report(cases, *, baseline_package=None):
    cases = _cases(cases)
    before = [{p: {n: s.byte_sha256 for n, s in snapshot(p).items()} for p in _paths(c)} for c in cases]
    base = c14_report([{k: v for k, v in c.items() if k != 'continuation'} for c in cases])
    package = _package_evidence(baseline_package, base, cases)
    results, partials, inventories = [], [], set()
    prior_native_ids, acquired_native_ids = set(), set()
    for index, (case, old) in enumerate(zip(cases, base['cases'])):
        cont = read_continuation(case['continuation'], case['parent_history'], case['c12_capture']) if case.get('continuation') else None
        if cont is not None and (cont['profile'] != base['profile'] or cont['parent_inventory_sha256'] != old['parent_probe']['inventory_sha256']):
            raise EvidenceError('continuation_original_case_profile_or_parent_conflict')
        parent = old['parent_probe']
        prior = [] if parent is None else parent['record_reassessment']['records']
        added = [] if cont is None else cont['records']
        prior_ids = {r['row']['id'] for r in prior}
        selection = None if parent is None else parent['selection']['generated_id']
        prior_native_ids.update((selection, r['row']['id']) for r in prior)
        acquired_native_ids.update((selection, r['row']['id']) for r in added)
        new_ids = sorted({r['row']['id'] for r in added} - prior_ids)
        if cont is not None and cont['inventory_sha256'] not in inventories:
            inventories.add(cont['inventory_sha256'])
            partials.append({'case_index': index, 'acquisition_id': cont['acquisition_id'],
                'inventory_sha256': cont['inventory_sha256'], 'new_distinct_source_record_ids': new_ids,
                'record_citations': [r['citation'] for r in added],
                'bounded_query_chain_observed_terminal': cont['observed_terminal_query_chain'],
                'status': 'CONFLICTING_OR_PARTIAL' if cont['failures'] else 'FINITE_SOURCE_QUERY_SUBPROOF_ONLY',
                'original_requirement_fully_resolved': False,
                'remaining_dependencies': ['source_history_recall_and_deletion_archive',
                    'historical_parent_applicability', 'source_snapshot_asof_and_revision_authority']})
        results.append({'case_index': index, 'original_case_sha256': old['original_case_sha256'],
            'continuation': cont, 'parent_records_before': len(prior),
            'new_distinct_native_record_identifiers': new_ids,
            'historical_parent_assessments': parent_assessments(old, prior + added),
            'coverage': coverage(old, case, cont),
            'freshness': freshness([r['citation'] for r in prior + added]),
            'revision_lineage': old['directed_revision_graph'],
            'monetary_compatibility': monetary_preflight(old, case, cont),
            'financial_comparison_authorized': False})
    for c, expected in zip(cases, before):
        if {p: {n: s.byte_sha256 for n, s in snapshot(p).items()} for p in _paths(c)} != expected:
            raise EvidenceError('C15_primary_inputs_changed')
    prior_real = base['resolved_original_real_source_requirements']
    prior_synthetic = base['resolved_original_synthetic_requirements']
    all_ids = sorted(set(base['remaining_original_plan_ids'] + prior_real + prior_synthetic))
    value = {'schema_type': 'ParentCoverageReport', 'schema_version': 1, 'rule_version': RULE,
        'profile': base['profile'], 'baseline': base, 'baseline_original_plan_ids': all_ids,
        'baseline_report_sha256': digest(base), 'evidence_package_verification': package,
        'cases': results, 'newly_resolved_real_source_requirements': [],
        'previously_resolved_real_source_requirements': prior_real,
        'partial_real_source_subproofs': partials if base['profile'] == 'live' else [],
        'synthetic_only_subproofs': partials if base['profile'] == 'synthetic' else [],
        'new_distinct_parent_record_identifiers': [{'source': 'usaspending', 'source_native_parent_id': p,
            'source_native_record_id': r} for p, r in sorted(acquired_native_ids - prior_native_ids)],
        'repeated_identifiers_are_not_independent_corroboration': True,
        'previously_resolved_synthetic_requirements': prior_synthetic,
        'remaining_original_plan_ids': base['remaining_original_plan_ids'],
        'historical_parent_applicability_intervals_established': 0,
        'authoritative_real_source_correction_edges': 0,
        'complete_historical_financial_qualifications': 0,
        'financial_comparison_authorized': False, 'production_readiness_changed': False,
        'limitations': ['no_new_original_requirement_resolved_by_terminal_pages',
            'separate_capture_times_not_atomic_snapshot', 'parent_modification_match_not_effective_applicability',
            'unknown_native_transaction_number_not_zero', 'no_validated_live_correction_rule',
            'no_financial_arithmetic_or_eligibility_upgrade']}
    if len(canonical(value).encode()) > 16 * 1024 * 1024:
        raise EvidenceError('C15_report_size_limit')
    return value


def projections(value):
    lines = ['# Historical parent coverage and reproducible evidence v1', '',
        'Cohort: ' + value['profile'],
        'Package verification: ' + value['evidence_package_verification']['status'], '',
        '| Measure | Before | After |', '| --- | ---: | ---: |',
        '| Original requirements | ' + str(len(value['baseline_original_plan_ids'])) + ' | ' + str(len(value['baseline_original_plan_ids'])) + ' |',
        '| Previously resolved real requirements preserved | ' + str(len(value['previously_resolved_real_source_requirements'])) + ' | ' + str(len(value['previously_resolved_real_source_requirements'])) + ' |',
        '| Newly resolved real requirements | 0 | ' + str(len(value['newly_resolved_real_source_requirements'])) + ' |',
        '| Remaining requirements | ' + str(len(value['remaining_original_plan_ids'])) + ' | ' + str(len(value['remaining_original_plan_ids'])) + ' |',
        '| Historical applicability intervals | 0 | 0 |',
        '| Complete historical financial qualifications | 0 | 0 |', '',
        'Terminal observed pagination is not source recall, snapshot consistency or complete history. No financial authorization.', '']
    for case in value['cases']:
        lines += ['## Case ' + str(case['case_index']), '',
            'New distinct source-native record identifiers: ' + str(len(case['new_distinct_native_record_identifiers'])),
            'Parent query coverage: ' + case['coverage']['parent_query']['coverage_state'],
            'Monetary compatibility: BLOCKED; no sums, deltas or losses computed.', '']
    lines += ['## Primary evidence, source fields and unresolved dependencies', '', '```json',
        canonical(value).replace('`', '\\u0060'), '```', '']
    md = '\n'.join(lines)
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Historical parent coverage</title><pre>' + escape(md) + '</pre></html>\n'
    return {'coverage.json': (canonical(value) + '\n').encode(), 'coverage.md': md.encode(), 'coverage.html': html.encode()}


def _plan():
    return {'schema_type': 'ParentCoverageReportPlan', 'schema_version': 1,
        'rule_version': RULE, 'config': {'max_run_bytes': 128 * 1024 * 1024}}


def write_report(path, cases, *, baseline_package=None):
    outside(path, [p for c in _cases(cases) for p in _paths(c)] + ([baseline_package] if baseline_package else []))
    value = report(cases, baseline_package=baseline_package)
    rendered = projections(value)
    if any(len(v) > 32 * 1024 * 1024 for v in rendered.values()) or sum(map(len, rendered.values())) > 96 * 1024 * 1024:
        raise EvidenceError('C15_projection_size_limit')
    with PilotStore(path, _plan()) as store:
        for name, raw in rendered.items():
            store.write_bytes(name, raw)
        store.write('coverage-commit.json', {'schema_version': 1, 'files': store.inventory(), 'report_sha256': digest(value)})
    return digest(value)


def verify_report(path, cases, *, baseline_package=None):
    with EvidenceRoot(path, max_bytes=32 * 1024 * 1024, max_total_bytes=128 * 1024 * 1024, max_files=5) as root:
        values = {n: root.read(n) for n in root.discover()}
        if {n: root.read(n, recheck=True).byte_sha256 for n in root.discover()} != {n: s.byte_sha256 for n, s in values.items()}:
            raise EvidenceError('C15_report_changed')
    value = report(cases, baseline_package=baseline_package)
    rendered = projections(value)
    if set(values) != {*rendered, 'pilot-plan.json', 'coverage-commit.json'}:
        raise EvidenceError('C15_report_incomplete_or_extra_files')
    commit = {'schema_version': 1, 'files': {n: s.byte_sha256 for n, s in values.items() if n != 'coverage-commit.json'}, 'report_sha256': digest(value)}
    if (values['pilot-plan.json'].data != (canonical(_plan()) + '\n').encode()
        or values['coverage-commit.json'].data != (canonical(commit) + '\n').encode()
        or any(values[n].data != raw for n, raw in rendered.items())):
        raise EvidenceError('C15_report_primary_replay_conflict')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline C15 coverage/preflight; explicit bounded parent continuation only.')
    parser.add_argument('--cases', required=True)
    parser.add_argument('--baseline-package')
    parser.add_argument('--plan-continuation', action='store_true')
    parser.add_argument('--capture-continuation', action='store_true')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--max-requests', type=int, default=2)
    parser.add_argument('--max-records', type=int, default=10)
    parser.add_argument('--acquisition-label', default='bounded-parent-continuation')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--output')
    mode.add_argument('--verify-report')
    args = parser.parse_args(argv)
    try:
        if not args.plan_continuation and not (args.output or args.verify_report):
            raise EvidenceError('explicit_report_output_or_verification_required')
        source = Path(args.cases).absolute()
        with EvidenceRoot(source.parent, max_bytes=1048576) as root:
            cases = _cases(strict_json(root.read(source.name).data))
            root.read(source.name, recheck=True)
        limits = ContinuationLimits(max_requests=args.max_requests, max_records=args.max_records)
        if args.live != args.capture_continuation or args.plan_continuation and args.capture_continuation:
            raise EvidenceError('explicit_nonconflicting_continuation_flags_required')
        if args.plan_continuation or args.capture_continuation:
            if len(cases) != 1 or not cases[0].get('parent_history') or not cases[0].get('c12_capture') or args.verify_report:
                raise EvidenceError('one_anchored_parent_continuation_required')
            case = cases[0]
            report([{k: v for k, v in case.items() if k != 'continuation'}], baseline_package=args.baseline_package)
            value = plan(case['parent_history'], case['c12_capture'], limits=limits, label=args.acquisition_label)
            if args.plan_continuation:
                print(canonical(value))
                return 0
            if not case.get('continuation'):
                raise EvidenceError('new_separate_continuation_directory_required')
            outside(case['continuation'], [source] + c14_paths(case) + ([args.baseline_package] if args.baseline_package else []))
            outside(args.output, [source] + _paths(case))
            collect(case['continuation'], case['parent_history'], case['c12_capture'],
                live=True, limits=limits, label=args.acquisition_label)
        if args.verify_report:
            value = verify_report(args.verify_report, cases, baseline_package=args.baseline_package)
        else:
            write_report(args.output, cases, baseline_package=args.baseline_package)
            value = verify_report(args.output, cases, baseline_package=args.baseline_package)
        print(canonical({'report_sha256': digest(value), 'new_original_real_requirements_resolved': 0,
            'previous_real_requirements_preserved': len(value['previously_resolved_real_source_requirements']),
            'remaining_requirements': len(value['remaining_original_plan_ids']), 'financial_comparison_authorized': False}))
        return 1 if any(c['continuation'] and not c['continuation']['observed_terminal_query_chain'] for c in value['cases']) else 0
    except (ValueError, OSError, KeyError, IndexError, TypeError):
        print(canonical({'error_code': 'parent_coverage_failed_preserve_evidence', 'exit_code': 2}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
