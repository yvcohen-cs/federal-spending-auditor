"""C16 exact missing-parent-primary closure; offline primary replay is the default.

A current source-local relationship resolves only that narrow identity/existence
claim. It cannot supply historical applicability, revision authority or money.
"""
import argparse
from html import escape
from pathlib import Path

from .authority_binding import (RULE, PARENT_DOCUMENTATION, candidate_plan, parent_sources, read, collect)
from .authority_identity import audit as audit_identity
from .award_validation import snapshot
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .evidence_package import verified_directory, _recipe
from .parent_coverage_reporting import report as c15_report, _paths as c15_paths
from .pilot_store import PilotStore
from .review_packet_io import outside
from .history_qualification import requirement, QualificationStatus


def _cases(cases):
    if type(cases) not in (list, tuple) or not 1 <= len(cases) <= 24 or any(type(c) is not dict for c in cases):
        raise EvidenceError('bounded_C16_cases_required')
    if sum(bool(c.get('authority_binding')) for c in cases) > 2:
        raise EvidenceError('at_most_two_exact_binding_targets')
    return tuple(cases)


def _paths(case):
    return c15_paths(case) + ([case['authority_binding']] if case.get('authority_binding') else [])


def report(cases, *, baseline_package):
    cases = _cases(cases)
    before = [{p: {n: s.byte_sha256 for n, s in snapshot(p).items()} for p in _paths(c)} for c in cases]
    clean = [{k: v for k, v in c.items() if k != 'authority_binding'} for c in cases]
    with verified_directory(baseline_package, expected_phase='C15') as (root, verified):
        _, prior_package, _ = _recipe(root, 'C15')
        base = c15_report(clean, baseline_package=prior_package)
        if verified['profile'] != base['profile']:
            raise EvidenceError('C16_baseline_profile_conflict')
        # Bind the preserved package to the same original cases and exact parent
        # captures; neither serialized report claims nor path names are authority.
        selected = []
        for binding in verified['verified_case_bindings']:
            matches = [i for i, c in enumerate(base['baseline']['cases'])
                if c['original_case_sha256'] == binding['original_case_sha256']
                and (None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256']) == binding['parent_inventory_sha256']]
            if len(matches) != 1:
                raise EvidenceError('C16_baseline_package_original_case_conflict')
            selected.append(clean[matches[0]])
        if digest(c15_report(selected, baseline_package=prior_package)) != verified['report_sha256']:
            raise EvidenceError('C16_packaged_and_local_primary_replays_disagree')
        sources = parent_sources(root, verified)
        results, resolved, table = [], set(), []
        for i, (case, old) in enumerate(zip(cases, base['baseline']['cases'])):
            binding, source, closure = None, None, None
            if case.get('authority_binding'):
                expected = candidate_plan(case, verified, sources)
                binding = read(case['authority_binding'], case, baseline_package, expected_plan=expected)
                source = next(s for s in sources if digest(s) == expected['parent_source_evidence_sha256'])
                if not binding['failures']:
                    claim = expected['original_requirement_id']
                    if claim not in base['remaining_original_plan_ids']:
                        raise EvidenceError('C16_requirement_not_original_unresolved')
                    resolved.add(claim)
                    binding_id = 'authority-binding-evidence:v1:' + binding['capture_inventory_sha256']
                    parent_id = 'preserved-parent-evidence:v1:' + digest(source)
                    qualified = requirement('parent_identity', QualificationStatus.QUALIFIED,
                        ['source_native_child_reference_and_independently_preserved_parent_primary'],
                        expected['previous_requirement']['citation_ids'] + [binding_id, parent_id])
                    closure = {'original_requirement_id': claim, 'previous_requirement': expected['previous_requirement'],
                        'new_requirement': qualified.to_dict(), 'new_child_evidence_id': binding_id,
                        'preserved_parent_evidence_id': parent_id,
                        'qualification_status': qualified.status.value, 'dimension': 'parent_identity',
                        'claim': 'source-local child reference and independently preserved parent primary existence',
                        'rule_version': RULE, 'original_child_node_ids': expected['original_child_node_ids'],
                        'new_child_summary_evidence': binding['citation'],
                        'preserved_parent_evidence': source,
                        'source_documentation': [PARENT_DOCUMENTATION],
                        'historical_applicability_established': False,
                        'remaining_dependencies': ['historical_child_parent_effective_rule', 'applicable_parent_revision',
                            'historical_source_recall_and_snapshot', 'authoritative_correction_edges', 'financial_semantics_and_existing_gates'],
                        'financial_comparison_authorized': False}
            for p in old['original_requirement_impacts']:
                if p['original_plan_id'] not in base['remaining_original_plan_ids']:
                    continue
                parent_available = any((s['parent_piid'], s['parent_identity_agency']) == (p['native_context'].get('parent_piid'), p['native_context'].get('parent_agency')) for s in sources)
                primary = p['dimension'] == 'parent_identity' and p['original_requirement']['reasons'] == ['parent_award_primary_record_not_observed']
                table.append({'original_requirement_id': p['original_plan_id'], 'case_index': i,
                    'dimension': p['dimension'], 'native_context': p['native_context'],
                    'missing_evidence': p['original_requirement']['reasons'],
                    'required_source': p['native_context'].get('namespace'),
                    'selected': bool(binding and p['original_plan_id'] == binding['plan']['original_requirement_id']),
                    'preserved_parent_primary_available': parent_available,
                    'supporting_observation_ids': p['original_requirement']['citation_ids'],
                    'priority': 1 if primary and parent_available and p['native_context'].get('namespace') == 'usaspending' else 2,
                    'acquisition_decision': ('EXACT_PUBLIC_CHILD_SUMMARY_AND_PRESERVED_PARENT' if parent_available else 'REQUIRES_CHILD_REFERENCE_AND_INDEPENDENT_PARENT_CAPTURE') if primary and p['native_context'].get('namespace') == 'usaspending' else 'BLOCKED_PENDING_AUTHORITATIVE_SOURCE_OR_SEMANTICS',
                    'result': 'NARROW_IDENTITY_CLAIM_RESOLVED' if p['original_plan_id'] in resolved else 'UNRESOLVED',
                    'no_names_amounts_dates_or_alias_join': True})
            results.append({'case_index': i, 'original_case_sha256': old['original_case_sha256'],
                'binding': binding, 'closure': closure,
                'cross_source_identity': {'new_authoritative_counterpart_status': 'MISSING_NEW_AUTHORITATIVE_COUNTERPART',
                    'new_verified_mappings': 0, 'preserved_native_counterpart_audit': audit_identity(old['observation_graph']) if case.get('authority_binding') or old['original_case_sha256'] in {b['original_case_sha256'] for b in verified['verified_case_bindings']} else None,
                    'limitations': ['existing_exact_native_mapping_is_preserved_not_new_corroboration',
                        'current_USA_parent_reference_does_not_map_parent_actions_to_FPDS_or_SAM']},
                'monetary_compatibility': {**{k: v for k, v in base['cases'][i]['monetary_compatibility'].items() if k != 'observed_fields'},
                    'observed_fields_json_pointer': '/baseline/cases/' + str(i) + '/monetary_compatibility/observed_fields'},
                'historical_parent_applicability_established': False, 'financial_comparison_authorized': False})
    for c, expected in zip(cases, before):
        if {p: {n: s.byte_sha256 for n, s in snapshot(p).items()} for p in _paths(c)} != expected:
            raise EvidenceError('C16_primary_inputs_changed')
    real = sorted(resolved) if base['profile'] == 'live' else []
    synthetic = sorted(resolved) if base['profile'] == 'synthetic' else []
    value = {'schema_type': 'HistoricalAuthorityReport', 'schema_version': 1, 'rule_version': RULE,
        'profile': base['profile'], 'baseline': base, 'baseline_original_plan_ids': base['baseline_original_plan_ids'],
        'baseline_report_sha256': digest(base), 'evidence_package_verification': verified,
        'cases': results, 'acquisition_decision_table': table,
        'previously_resolved_real_source_requirements': base['previously_resolved_real_source_requirements'],
        'previously_resolved_synthetic_requirements': base['previously_resolved_synthetic_requirements'],
        'newly_resolved_real_source_requirements': real, 'newly_resolved_synthetic_requirements': synthetic,
        'remaining_original_plan_ids': sorted(set(base['remaining_original_plan_ids']) - resolved),
        'new_authoritative_cross_source_identities': 0, 'new_parent_action_observations': 0,
        'historical_parent_applicability_intervals_established': 0, 'authoritative_real_source_correction_edges': 0,
        'complete_historical_financial_qualifications': 0, 'financial_comparison_authorized': False,
        'production_readiness_changed': False,
        'evidence_classes': {'binding': 'REAL_SOURCE' if base['profile'] == 'live' else 'SYNTHETIC_FIXTURE',
            'prior_parent_and_counterparts': 'PRESERVED_REPLAY', 'historical_applicability': 'UNVERIFIED_ASSUMPTION'},
        'limitations': ['current_relationship_is_not_historical_applicability', 'replay_is_not_independent_corroboration',
            'terminal_query_is_not_source_wide_or_transaction_history_completeness',
            'digests_are_integrity_not_upstream_authentication', 'no_real_correction_precedence_rule',
            'no_new_financial_eligibility_or_production_authorization']}
    if len(canonical(value).encode()) > 16 * 1024 * 1024:
        raise EvidenceError('C16_report_size_limit')
    return value


def projections(value):
    lines = ['# Cross-source historical authority v1', '',
        'Profile: ' + value['profile'],
        'Previously resolved real requirements preserved: ' + str(len(value['previously_resolved_real_source_requirements'])),
        'Newly resolved original real requirements: ' + str(len(value['newly_resolved_real_source_requirements'])),
        'Remaining original requirements: ' + str(len(value['remaining_original_plan_ids'])),
        'Historical applicability intervals: 0; real correction edges: 0; financial authorization: DISABLED.',
        'Original primary evidence, exact native identities, acquisition decisions and unresolved dependencies follow.', '',
        '```json', canonical(value).replace('`', '\\u0060'), '```', '']
    md = '\n'.join(lines)
    html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'"><title>Historical authority</title><pre>' + escape(md) + '</pre></html>\n'
    return {'authority.json': (canonical(value) + '\n').encode(), 'authority.md': md.encode(), 'authority.html': html.encode()}


def _plan():
    return {'schema_type': 'HistoricalAuthorityReportPlan', 'schema_version': 1, 'rule_version': RULE,
        'config': {'max_run_bytes': 128 * 1024 * 1024}}


def write_report(path, cases, *, baseline_package):
    outside(path, [p for c in _cases(cases) for p in _paths(c)] + [baseline_package])
    value = report(cases, baseline_package=baseline_package)
    rendered = projections(value)
    if any(len(v) > 32 * 1024 * 1024 for v in rendered.values()) or sum(map(len, rendered.values())) > 96 * 1024 * 1024:
        raise EvidenceError('C16_projection_size_limit')
    with PilotStore(path, _plan()) as store:
        for name, raw in rendered.items():
            store.write_bytes(name, raw)
        store.write('authority-commit.json', {'schema_version': 1, 'files': store.inventory(), 'report_sha256': digest(value)})
    return digest(value)


def verify_report(path, cases, *, baseline_package):
    with EvidenceRoot(path, max_bytes=32 * 1024 * 1024, max_total_bytes=128 * 1024 * 1024, max_files=5) as root:
        values = {n: root.read(n) for n in root.discover()}
        if {n: root.read(n, recheck=True).byte_sha256 for n in root.discover()} != {n: s.byte_sha256 for n, s in values.items()}:
            raise EvidenceError('C16_report_changed')
    value = report(cases, baseline_package=baseline_package)
    rendered = projections(value)
    commit = {'schema_version': 1, 'files': {n: s.byte_sha256 for n, s in values.items() if n != 'authority-commit.json'}, 'report_sha256': digest(value)}
    if (set(values) != {*rendered, 'pilot-plan.json', 'authority-commit.json'}
        or values['pilot-plan.json'].data != (canonical(_plan()) + '\n').encode()
        or values['authority-commit.json'].data != (canonical(commit) + '\n').encode()
        or any(values[n].data != raw for n, raw in rendered.items())):
        raise EvidenceError('C16_report_primary_replay_conflict')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description='C16 offline exact authority replay; optional one-request public child binding.')
    parser.add_argument('--cases', required=True)
    parser.add_argument('--baseline-package', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--plan-binding', action='store_true')
    mode.add_argument('--output')
    mode.add_argument('--verify-report')
    parser.add_argument('--capture-binding', action='store_true')
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args(argv)
    try:
        source = Path(args.cases).absolute()
        with EvidenceRoot(source.parent, max_bytes=1048576) as root:
            cases = _cases(strict_json(root.read(source.name).data))
            root.read(source.name, recheck=True)
        if args.live != args.capture_binding or (args.plan_binding or args.verify_report) and args.capture_binding:
            raise EvidenceError('explicit_nonconflicting_binding_flags_required')
        if args.plan_binding or args.capture_binding:
            targets = [c for c in cases if c.get('authority_binding')]
            if len(targets) != 1:
                raise EvidenceError('one_explicit_binding_target_required')
            target = targets[0]
            from .authority_binding import plan
            value = plan(target, args.baseline_package)
            if args.plan_binding:
                print(canonical(value))
                return 0
            # Validate all pre-existing primary evidence before the only request.
            report([{k: v for k, v in c.items() if k != 'authority_binding'} for c in cases], baseline_package=args.baseline_package)
            outside(target['authority_binding'], [source] + [p for c in cases for p in c15_paths(c)] + [args.baseline_package])
            outside(args.output, [source] + [p for c in cases for p in _paths(c)] + [args.baseline_package])
            collect(target['authority_binding'], target, args.baseline_package, live=True)
        if args.verify_report:
            value = verify_report(args.verify_report, cases, baseline_package=args.baseline_package)
        else:
            outside(args.output, [source])
            write_report(args.output, cases, baseline_package=args.baseline_package)
            value = verify_report(args.output, cases, baseline_package=args.baseline_package)
        print(canonical({'report_sha256': digest(value), 'new_real_requirements': len(value['newly_resolved_real_source_requirements']),
            'remaining': len(value['remaining_original_plan_ids']), 'financial_comparison_authorized': False}))
        return 0
    except (ValueError, OSError, KeyError, IndexError, TypeError):
        print(canonical({'error_code': 'historical_authority_failed_preserve_evidence', 'exit_code': 2}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
