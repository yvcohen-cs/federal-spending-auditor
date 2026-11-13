"""C19 compact, primary-replayed historical obligations and bounded gap closure.

Reports reference the verified C18 receipt instead of recursively embedding prior
reports. Original qualification and acquisition rules remain unchanged.
"""
import argparse
from html import escape
from pathlib import Path

from .action_authority_reporting import paths as c18_paths, clean as c18_clean
from .parent_authority_reporting import clean as c17_clean
from .authority_binding import c14_case
from .correction_reporting import report as c14_report
from .parent_authority_acquisition import plan, usable
from .source_verification import inspect_experiment
from .parent_history_probe import read as read_parent
from .historical_source_authority import assess, documentation
from .evidence_package import verified_directory, _recipe
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .award_validation import snapshot
from .history_preflight import monetary_preflight
from .pilot_store import PilotStore
from .review_packet_io import outside

EXTRA = ('c19_parent_capture', 'c19_parent_history')
ORIGINAL_IDS = '4bdc74df2b5002a557a0f9ac793aca5e2610526490c9890746ecd8f0acccd439'
LIVE_TARGETS = {
    'evidence-resolution:v1:1f8e8f63303ebad6981e77c7e60133733e67c6504efce8229ad8a84d5a5249f5':
        ('81ab54630942ca891c724becc19b39b133cb073d9889de5194d0d9ce5c14f927', '121aad115e8721063299e088feff26370b7ddfd2da719dde31f382189e84fe36'),
    'evidence-resolution:v1:0b94bb645635e1c8414acb90d661d51178cd3ffbb0c0304abc07a55fc2949b3f':
        ('7bc7fa0c0f181ba53d7f1d997cf88271eab334e41e3afac8c31910555d824b8c', '1aa1a23388d935c5e69fe3b98f7af4dee2a3eaa1880eac0306c143102233ddd9'),
}


def clean(case):
    return {k: v for k, v in case.items() if k not in EXTRA}


def original(case):
    return c14_case(c17_clean(c18_clean(clean(case))))


def fallback(case):
    if any(case.get(k) for k in ('new_parent_capture', 'new_parent_history',
                                 'action_parent_capture', 'action_parent_history')):
        raise EvidenceError('C19_cannot_rebind_prior_acquisition')
    return {**original(case), 'new_parent_capture': case.get(EXTRA[0]),
            'new_parent_history': case.get(EXTRA[1])}


def paths(case):
    return c18_paths(clean(case)) + [case[k] for k in EXTRA if case.get(k) and Path(case[k]).exists()]


def bounded(cases):
    if (type(cases) not in (tuple, list) or not 1 <= len(cases) <= 24
            or any(type(c) is not dict for c in cases)
            or sum(bool(c.get(EXTRA[0])) for c in cases) > 2):
        raise EvidenceError('bounded_C19_original_cases_required')
    return cases


def report(cases, *, baseline_package, source_documents):
    cases = bounded(cases)
    protected = {p: {n: s.byte_sha256 for n, s in snapshot(p).items()}
                 for c in cases for p in paths(c)}
    docs = documentation(source_documents)
    old = c14_report([original(c) for c in cases])
    originals = old['cases']
    case_ids = [c['original_case_sha256'] for c in originals]
    if len(set(case_ids)) != len(case_ids):
        raise EvidenceError('duplicate_original_case_not_new_corroboration')
    ids = sorted({p['original_plan_id'] for c in originals for p in c['original_requirement_impacts']})
    with verified_directory(baseline_package, expected_phase='C18') as (root, verified):
        with EvidenceRoot(Path(root) / 'report', max_bytes=32*1024*1024) as reader:
            base = strict_json(reader.read('action-authority.json').data)
        if verified['profile'] != old['profile']:
            raise EvidenceError('C19_baseline_profile_conflict')
        packaged, _, _ = _recipe(root, 'C18')
        if len(packaged) != len(verified['verified_case_bindings']):
            raise EvidenceError('C19_baseline_binding_count_conflict')
        roles = ('collections', 'sam_captures', 'c12_capture', 'historical_probe', 'parent_history',
                 'continuation', 'authority_binding', 'new_parent_capture', 'new_parent_history',
                 'action_parent_capture', 'action_parent_history')
        for saved, binding in zip(packaged, verified['verified_case_bindings']):
            matches = [i for i, c in enumerate(originals) if c['original_case_sha256'] == binding['original_case_sha256']
                and (None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256']) == binding['parent_inventory_sha256']]
            if len(matches) != 1:
                raise EvidenceError('C19_preserved_original_case_binding_missing')
            current = cases[matches[0]]
            for role in roles:
                expected, supplied = saved.get(role), current.get(role)
                many = role in ('collections', 'sam_captures')
                expected = (expected or []) if many else [] if expected is None else [expected]
                supplied = (supplied or []) if many else [] if supplied is None else [supplied]
                if type(supplied) is not list or len(expected) != len(supplied):
                    raise EvidenceError('C19_preserved_evidence_role_changed')
                for a, b in zip(expected, supplied):
                    if ({n: s.byte_sha256 for n, s in snapshot(a).items()}
                            != {n: s.byte_sha256 for n, s in snapshot(b).items()}):
                        raise EvidenceError('C19_preserved_evidence_inventory_changed')
        prior_real = sorted(base['previously_resolved_real_source_requirements'] + base['newly_resolved_real_source_requirements'])
        prior_synthetic = sorted(base['previously_resolved_synthetic_requirements'] + base['newly_resolved_synthetic_requirements'])
        prior = set(prior_real + prior_synthetic)
        if (not prior <= set(ids) or len(prior) != len(prior_real + prior_synthetic)
                or not set(base['baseline_original_plan_ids']) <= set(ids)):
            raise EvidenceError('C19_original_requirement_set_not_preserved')
        full = old['profile'] == 'live' and len(cases) == 24
        if old['profile'] == 'live':
            if full:
                if len(ids) != 1570 or digest(ids) != ORIGINAL_IDS:
                    raise EvidenceError('C19_live_original_1570_ID_set_changed')
            else:
                allowed = {b['original_case_sha256'] for b in verified['verified_case_bindings']}
                allowed.update(v[0] for v in LIVE_TARGETS.values())
                if not set(case_ids) <= allowed:
                    raise EvidenceError('C19_unregistered_live_case')
        historical = assess(base['baseline']['historical_parent_assessment'], profile=old['profile'])
    results, new = [], set()
    for index, (case, previous) in enumerate(zip(cases, originals)):
        source = parent = None
        impacts = []
        money = None
        if case.get(EXTRA[1]) and not case.get(EXTRA[0]):
            raise EvidenceError('C19_parent_requires_original_child_anchor')
        if case.get(EXTRA[0]):
            target = fallback(case)
            planned = plan(target, live=old['profile'] == 'live')
            key = planned['original_requirement_id']
            if key not in set(ids) - prior:
                raise EvidenceError('C19_target_not_original_unresolved')
            if old['profile'] == 'live' and LIVE_TARGETS.get(key) != (planned['original_case_sha256'], digest(planned)):
                raise EvidenceError('C19_target_not_preregistered_plan')
            source = inspect_experiment(case[EXTRA[0]])
            if source['experiment'] != planned['experiment']:
                raise EvidenceError('C19_source_not_bound_to_original_plan')
            if usable(source) and case.get(EXTRA[1]) and Path(case[EXTRA[1]]).exists():
                parent = read_parent(case[EXTRA[1]], case[EXTRA[0]])
                if parent['capture_contract_version'] != 2:
                    raise EvidenceError('C19_parent_contract_v2_required')
                augmented = {**original(case), 'c12_capture': case[EXTRA[0]], 'parent_history': case[EXTRA[1]]}
                enhanced = c14_report([augmented])['cases'][0]
                if enhanced['original_case_sha256'] != previous['original_case_sha256']:
                    raise EvidenceError('C19_original_case_identity_changed')
                for p in enhanced['original_requirement_impacts']:
                    if p['original_requirement_resolved']:
                        if (p['original_plan_id'] != key or p['dimension'] != 'parent_identity'
                                or p['native_context']['namespace'] != 'usaspending'
                                or p['original_requirement'] != planned['original_requirement']):
                            raise EvidenceError('C19_unsupported_qualification_expansion')
                        new.add(key)
                        impacts.append(p)
                money = monetary_preflight(enhanced, augmented, None)
        results.append({'case_index': index, 'original_case_sha256': previous['original_case_sha256'],
            'child_parent_capture': source, 'parent_probe': parent, 'resolved_original_impacts': impacts,
            'financial_preflight': money, 'financial_comparison_authorized': False})
    for p, expected in protected.items():
        if {n: s.byte_sha256 for n, s in snapshot(p).items()} != expected:
            raise EvidenceError('C19_primary_inputs_changed')
    if documentation(source_documents) != docs:
        raise EvidenceError('C19_source_documents_changed')
    return {'schema_type': 'HistoricalAuthorityReport', 'schema_version': 1, 'profile': old['profile'],
        'qualification_scope': 'original_24_case_cohort' if full else 'included_cases_only',
        'baseline_report_sha256': verified['report_sha256'], 'baseline_package_verification': verified,
        'baseline_original_plan_ids': ids, 'original_case_bindings': [
            {'original_case_sha256': c['original_case_sha256'], 'parent_inventory_sha256':
             None if c['parent_probe'] is None else c['parent_probe']['inventory_sha256']} for c in originals],
        'source_documentation': docs,
        'source_documentation_evidence_class': 'REAL_PUBLIC_DOCUMENT_CAPTURE' if old['profile'] == 'live' else 'SYNTHETIC_DOCUMENT_FIXTURE',
        'historical_authority_assessment': historical, 'cases': results,
        'previously_resolved_real_source_requirements': prior_real,
        'previously_resolved_synthetic_requirements': prior_synthetic,
        'newly_resolved_real_source_requirements': sorted(new) if old['profile'] == 'live' else [],
        'newly_resolved_synthetic_requirements': sorted(new) if old['profile'] == 'synthetic' else [],
        'remaining_original_plan_ids': sorted(set(ids) - prior - new),
        'real_source_partial_subproofs': [historical] if old['profile'] == 'live' else [],
        'synthetic_only_subproofs': [historical] if old['profile'] == 'synthetic' else [],
        'source_observations': {'capture_request_attempts': sum(
            (c['child_parent_capture']['request_attempts'] if c['child_parent_capture'] else 0)
            + (c['parent_probe']['request_attempts'] if c['parent_probe'] else 0) for c in results),
            'parent_native_record_ids': sorted({r['row']['id'] for c in results if c['parent_probe']
                and not c['parent_probe']['record_reassessment']['failures']
                for r in c['parent_probe']['record_reassessment']['records']}),
            'replay_makes_new_requests': False, 'repeated_records_are_independent_corroboration': False},
        'historical_parent_applicability_intervals_established': 0,
        'authoritative_real_source_correction_edges': 0, 'financial_comparison_authorized': False,
        'financial_eligibility_changed': False, 'production_readiness_changed': False}


def projections(value):
    md = ('# Historical source authority v1\n\nScope: ' + value['qualification_scope']
          + '\nPrior real: ' + str(len(value['previously_resolved_real_source_requirements']))
          + '\nNew real: ' + str(len(value['newly_resolved_real_source_requirements']))
          + '\nRemaining: ' + str(len(value['remaining_original_plan_ids']))
          + '\nNo historical or financial authorization.\n\n```json\n'
          + canonical(value).replace('`', '\\u0060') + '\n```\n')
    html = ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; base-uri \'none\'">'
            '<title>Historical source authority</title><pre>' + escape(md) + '</pre></html>\n')
    return {'historical-authority.json': (canonical(value)+'\n').encode(),
            'historical-authority.md': md.encode(), 'historical-authority.html': html.encode()}


def write_report(path, cases, *, baseline_package, source_documents):
    outside(path, [p for c in bounded(cases) for p in paths(c)] + [baseline_package, source_documents])
    value = report(cases, baseline_package=baseline_package, source_documents=source_documents)
    raw = projections(value)
    if any(len(b) > 16*1024*1024 for b in raw.values()):
        raise EvidenceError('C19_projection_limit')
    with PilotStore(path, {'schema_type': 'HistoricalAuthorityReportPlan', 'schema_version': 1,
                          'config': {'max_run_bytes': 64*1024*1024}}) as store:
        for n, b in raw.items():
            store.write_bytes(n, b)
        store.write('historical-authority-commit.json', {'schema_version': 1,
            'files': store.inventory(), 'report_sha256': digest(value)})
    return digest(value)


def verify_report(path, cases, *, baseline_package, source_documents):
    with EvidenceRoot(path, max_bytes=16*1024*1024, max_total_bytes=64*1024*1024, max_files=5) as root:
        saved = {n: root.read(n) for n in root.discover()}
        if any(root.read(n, recheck=True).byte_sha256 != s.byte_sha256 for n, s in saved.items()):
            raise EvidenceError('C19_report_changed')
    value = report(cases, baseline_package=baseline_package, source_documents=source_documents)
    raw = projections(value)
    plan_value = {'schema_type': 'HistoricalAuthorityReportPlan', 'schema_version': 1,
                  'config': {'max_run_bytes': 64*1024*1024}}
    commit = {'schema_version': 1, 'files': {n: s.byte_sha256 for n, s in saved.items()
              if n != 'historical-authority-commit.json'}, 'report_sha256': digest(value)}
    if (set(saved) != {*raw, 'pilot-plan.json', 'historical-authority-commit.json'}
            or saved['pilot-plan.json'].data != (canonical(plan_value)+'\n').encode()
            or saved['historical-authority-commit.json'].data != (canonical(commit)+'\n').encode()
            or any(saved[n].data != b for n, b in raw.items())):
        raise EvidenceError('C19_report_primary_replay_conflict')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline historical authority; no network or credential reads.')
    parser.add_argument('--cases', required=True)
    parser.add_argument('--baseline-package', required=True)
    parser.add_argument('--source-documents', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output')
    mode.add_argument('--verify-report')
    mode.add_argument('--plan-fallback', action='store_true')
    args = parser.parse_args(argv)
    try:
        file = Path(args.cases).absolute()
        with EvidenceRoot(file.parent) as reader:
            cases = bounded(strict_json(reader.read(file.name).data))
        if args.plan_fallback:
            print(canonical([plan(fallback(c)) for c in cases if c.get(EXTRA[0])]))
            return 0
        kwargs = {'baseline_package': args.baseline_package, 'source_documents': args.source_documents}
        if args.verify_report:
            value = verify_report(args.verify_report, cases, **kwargs)
        else:
            outside(args.output, [args.cases])
            write_report(args.output, cases, **kwargs)
            value = verify_report(args.output, cases, **kwargs)
        print(canonical({'report_sha256': digest(value), 'new_real': len(value['newly_resolved_real_source_requirements']),
                         'remaining': len(value['remaining_original_plan_ids']), 'financial_authorized': False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, IndexError, AttributeError):
        print(canonical({'error_code': 'historical_authority_failed_preserve_evidence'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
