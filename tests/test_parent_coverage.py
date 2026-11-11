"""C15 offline synthetic regressions; no human or federal approval claims."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import io
import json
import os
import shutil
import stat
import warnings
import zipfile

import pytest

from src.evidence_io import EvidenceError, canonical, digest
from src.evidence_package import (EvidencePackageManifest, build_package, verify_package,
    main as package_main, MAX_FILE, MAX_TOTAL)
from src.parent_continuation import ContinuationLimits, plan, collect, read
from src.parent_coverage_reporting import report, write_report, verify_report, projections, main
from src.history_preflight import freshness, parent_assessments
from tests.test_correction_parent import setup as c14_setup
from tests.test_evidence_acquisition import inventory


def setup(tmp_path):
    import src.parent_history_probe as parent
    root, cases, c12, _, _, transcript = c14_setup(tmp_path / 'seed')
    old = tmp_path / 'original-parent'
    body = transcript['responses'][0]['json']
    body['results'][0]['id'] = body['results'][0]['id'][:-1] + '-NONE-'
    body['page_metadata'].update(hasNext=True, next=2)
    normal = parent.plan_for
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(parent, 'plan_for', lambda base, **kw: normal(base, contract_version=kw.get('contract_version', 1)))
        parent.collect(old, c12, synthetic=transcript)
    cases[0]['parent_history'] = str(old)
    row = deepcopy(body['results'][0])
    row.update(id=row['id'].replace('_0_-NONE-_-NONE-', '_1_-NONE-_-NONE-'), modification_number='1', action_date='2017-01-01')
    new_body = {'results': [row], 'page_metadata': {'page': 2, 'next': None, 'previous': 1, 'hasNext': False, 'hasPrevious': True}}
    new_transcript = {'schema_version': 1, 'responses': [{'source': 'usaspending', 'json': new_body}]}
    return root, cases, c12, old, new_transcript


def captured(tmp_path, change=None, limits=None):
    root, cases, c12, old, transcript = setup(tmp_path)
    if change:
        change(transcript)
    out = tmp_path / 'continuation'
    value = collect(out, old, c12, synthetic=transcript, limits=limits)
    cases[0]['continuation'] = str(out)
    return root, cases, c12, old, out, value, transcript


def c14_staging(tmp_path):
    _, cases, c12, old, _ = setup(tmp_path / 'source')
    root = tmp_path / 'stage'
    root.mkdir()
    shutil.copytree(cases[0]['collections'][0], root / 'baseline')
    shutil.copytree(c12, root / 'c12')
    shutil.copytree(old, root / 'parent')
    relative = [{'collections': ['baseline'], 'c12_capture': 'c12', 'parent_history': 'parent', 'scope': cases[0]['scope']}]
    absolute = [{**relative[0], 'collections': [str(root / 'baseline')], 'c12_capture': str(root / 'c12'), 'parent_history': str(root / 'parent')}]
    (root / 'cases.json').write_text(json.dumps(relative))
    from src.correction_reporting import write_report as c14_write
    c14_write(root / 'report', absolute)
    return root, absolute


def rewrite_zip(source, output, change, *, resign=False):
    with zipfile.ZipFile(source) as archive:
        files = {n: archive.read(n) for n in archive.namelist()}
    change(files)
    if resign:
        m = json.loads(files['package-manifest.json'])
        hashes = {n: hashlib.sha256(b).hexdigest() for n, b in files.items() if n != 'package-manifest.json'}
        if 'files_json' in m:
            m['files_json'] = canonical(hashes)
        else:
            m['files'] = hashes
        files['package-manifest.json'] = (canonical(m) + '\n').encode()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in files.items():
            archive.writestr(name, body)


def resign_capture(root, change):
    change(root)
    files = {n: h for n, h in inventory(root).items() if n != 'continuation-commit.json'}
    (root / 'continuation-commit.json').write_text(canonical({'schema_version': 1, 'files': files}) + '\n')


def test_offline_plan_is_bound_and_does_not_mutate_legacy_capture(tmp_path):
    _, _, c12, old, _ = setup(tmp_path)
    before = inventory(old)
    p = plan(old, c12)
    assert p['start_page'] == 2 and p['planned_requests'][0]['parameters']['page'] == 2
    assert p['planned_requests'][1]['parameters']['page'] == 3
    assert p['planned_requests'][0]['parameters']['award_id'] == p['selection']['generated_id']
    assert p['retries'] == 0 and not p['redirects'] and p['source_allowlist'] == ['usaspending']
    assert inventory(old) == before


def test_terminal_continuation_preserves_previous_resolution_without_history_promotion(tmp_path):
    _, cases, c12, old, out, value, _ = captured(tmp_path)
    before = inventory(old)
    assert value == read(out, old, c12)
    assert value['capture_contract_version'] == 1 and value['record_contract_version'] == 2
    assert value['acquisition_evidence_id'].endswith(value['inventory_sha256'])
    assert value['observed_terminal_query_chain'] and value['request_attempts'] == 1
    assert value['entire_contract_history_complete'] == 'unknown'
    r = report(cases)
    assert not r['newly_resolved_real_source_requirements']
    assert len(r['previously_resolved_synthetic_requirements']) == 1
    assert not r['authoritative_real_source_correction_edges'] and not r['financial_comparison_authorized']
    assert len(r['new_distinct_parent_record_identifiers']) == 1
    assert r['repeated_identifiers_are_not_independent_corroboration']
    assert r['cases'][0]['coverage']['parent_query']['entire_contract_history'] == 'unknown'
    assert not r['cases'][0]['monetary_compatibility']['totals_or_deltas_computed']
    assert inventory(old) == before


@pytest.mark.parametrize('limit', [ContinuationLimits(max_requests=1), ContinuationLimits(max_records=5), ContinuationLimits(max_records=6)])
def test_request_or_record_cap_keeps_coverage_incomplete(tmp_path, limit):
    def change(t):
        t['responses'][0]['json']['page_metadata'].update(hasNext=True, next=3)
    _, _, _, _, out, value, _ = captured(tmp_path, change, limit)
    assert value['request_attempts'] == 1 and value['acquisition_budget_exhausted']
    assert not value['observed_terminal_query_chain'] and value['coverage_state'] == 'INCOMPLETE_ACQUISITION_BUDGET'
    assert not (out / 'continuation-002-reservation.json').exists()


@pytest.mark.parametrize('kwargs', [{'max_requests': 0}, {'max_requests': 3}, {'max_requests': True}, {'max_records': 4}, {'max_records': 11}])
def test_unbounded_or_ambiguous_limits_rejected(kwargs):
    with pytest.raises(ValueError):
        ContinuationLimits(**kwargs)


@pytest.mark.parametrize('field,bad', [('page', 3), ('previous', None), ('previous', 0), ('next', 3), ('hasPrevious', False), ('hasNext', 'false')])
def test_missing_or_contradictory_page_metadata_cannot_prove_coverage(tmp_path, field, bad):
    _, _, _, _, _, value, _ = captured(tmp_path, lambda t: t['responses'][0]['json']['page_metadata'].__setitem__(field, bad))
    assert value['failures'] and not value['observed_terminal_query_chain']


@pytest.mark.parametrize('field,bad', [('id', 'CONT_TX_9999_-NONE-_WRONG_1_-NONE-_-NONE-'), ('modification_number', '2'), ('type', 'C'), ('action_date', 'unknown')])
def test_conflicting_native_identity_or_instrument_rejected(tmp_path, field, bad):
    _, _, _, _, _, value, _ = captured(tmp_path, lambda t: t['responses'][0]['json']['results'][0].__setitem__(field, bad))
    assert value['failures'] and not value['records']


@pytest.mark.parametrize('mode', ['duplicate', 'variant', 'reverse_dates'])
def test_duplicates_reused_modifications_and_refresh_order_conflicts_preserved(tmp_path, mode):
    def change(t):
        row = t['responses'][0]['json']['results'][0]
        if mode == 'reverse_dates':
            row['action_date'] = '2010-01-01'
        else:
            row.update(id=row['id'].replace('_1_-NONE-_-NONE-', '_0_-NONE-_-NONE-'), modification_number='0')
            if mode == 'variant':
                row['federal_action_obligation'] = -99
    _, cases, _, _, _, value, _ = captured(tmp_path, change)
    assert value['failures'] and not value['observed_terminal_query_chain']
    if mode != 'reverse_dates':
        assert not report(cases)['cases'][0]['new_distinct_native_record_identifiers']


@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 429, 500, 503])
def test_unavailable_APIs_do_not_retry_or_become_absence_proof(tmp_path, status):
    _, cases, _, _, out, value, _ = captured(tmp_path, lambda t: t['responses'][0].__setitem__('status', status))
    assert value['request_attempts'] == 1 and value['failures'] and not value['records']
    assert not (out / 'continuation-002.json').exists()
    assert not report(cases)['newly_resolved_real_source_requirements']


def test_offline_default_never_initializes_network(tmp_path, monkeypatch):
    import src.parent_continuation as module
    monkeypatch.setattr(module, 'HTTPTransport', lambda *_: pytest.fail('network initialized'))
    _, _, c12, old, transcript = setup(tmp_path)
    with pytest.raises(ValueError):
        collect(tmp_path / 'no', old, c12)
    with pytest.raises(ValueError):
        collect(tmp_path / 'no', old, c12, live=True)
    assert collect(tmp_path / 'fixture', old, c12, synthetic=transcript)['profile'] == 'synthetic'


@pytest.mark.parametrize('name', ['continuation-commit.json', 'continuation-001-reservation.json', 'continuation-001.json', 'continuation-001.body'])
def test_missing_or_interrupted_histories_are_not_repaired(tmp_path, name):
    _, _, c12, old, out, _, _ = captured(tmp_path)
    (out / name).unlink()
    before = inventory(out)
    with pytest.raises((ValueError, KeyError)):
        read(out, old, c12)
    assert inventory(out) == before


@pytest.mark.parametrize('mode', ['request', 'representation', 'extra', 'body', 'budget'])
def test_resigned_tampering_of_continuation_rejected(tmp_path, mode):
    _, _, c12, old, out, *_ = captured(tmp_path)
    def change(p):
        if mode == 'extra':
            (p / 'extra.json').write_text('{}')
        elif mode == 'body':
            (p / 'continuation-001.body').write_text('{}')
        else:
            filename = 'pilot-plan.json' if mode == 'budget' else 'continuation-001.json'
            v = json.loads((p / filename).read_text())
            if mode == 'budget':
                v['limits']['max_requests'] = 100
            elif mode == 'request':
                v['request']['parameters']['award_id'] = 'FOREIGN'
            else:
                v['representation'] = 'wire_exact_HTTP'
            (p / filename).write_text(canonical(v) + '\n')
    resign_capture(out, change)
    with pytest.raises((ValueError, KeyError)):
        read(out, old, c12)


def test_versioned_packages_reproduce_primary_and_stable_archives(tmp_path):
    root, _ = c14_staging(tmp_path)
    a, b = tmp_path / 'a.zip', tmp_path / 'b.zip'
    first, second = build_package(root, a), build_package(root, b)
    assert a.read_bytes() == b.read_bytes() and first == second
    verified = verify_package(a)
    assert verified['primary_replay'] == 'verified' and verified['profile'] == 'synthetic'
    assert not verified['resolved_real_source_plan_ids'] and len(verified['verified_case_bindings']) == 1


@pytest.mark.parametrize('mode', ['index', 'source', 'report', 'recipe', 'profile', 'version', 'missing', 'extra'])
def test_corrupted_or_resigned_packages_fail_closed(tmp_path, mode):
    root, _ = c14_staging(tmp_path)
    original, altered = tmp_path / 'a.zip', tmp_path / 'altered.zip'
    build_package(root, original)
    def change(files):
        if mode == 'index':
            d = json.loads(files['evidence-index.json']);d['report_sha256'] = '0' * 64;files['evidence-index.json'] = canonical(d).encode()
        elif mode == 'source':
            files['parent/parent-001.body'] = b'{}'
        elif mode == 'report':
            files['report/correction.json'] = b'{}'
        elif mode == 'recipe':
            d = json.loads(files['cases.json']);d[0]['collections'] = ['../outside'];files['cases.json'] = canonical(d).encode()
        elif mode == 'missing':
            files.pop('parent/parent-001.body')
        elif mode == 'extra':
            files['secret.txt'] = b'not permitted'
        else:
            d = json.loads(files['package-manifest.json']);d['profile' if mode == 'profile' else 'schema_version'] = 'live' if mode == 'profile' else 99;files['package-manifest.json'] = canonical(d).encode()
    rewrite_zip(original, altered, change, resign=True)
    with pytest.raises((ValueError, KeyError, TypeError)):
        verify_package(altered)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:/windows', 'a\\b', './file', 'a/../../b', 'a/%2e%2e/b', '.env', 'x.partial'])
def test_package_paths_are_rejected_before_extraction(tmp_path, name):
    source = tmp_path / 'bad.zip'
    with zipfile.ZipFile(source, 'w') as z:
        z.writestr(name, '{}')
        z.writestr('package-manifest.json', '{}')
    with pytest.raises(ValueError):
        verify_package(source)
    assert not (tmp_path / 'escape').exists()


@pytest.mark.parametrize('mode', [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFDIR])
def test_ZIP_links_and_special_files_rejected(tmp_path, mode):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        info = zipfile.ZipInfo('file');info.external_attr = (mode | 0o600) << 16;z.writestr(info, 'target')
        z.writestr('package-manifest.json', '{}')
    with pytest.raises(ValueError):
        verify_package(archive)


@pytest.mark.parametrize('names', [('same', 'same'), ('A.json', 'a.json'), ('file', 'file/child')])
def test_duplicate_or_colliding_ZIP_names_rejected(tmp_path, names):
    path = tmp_path / 'bad.zip'
    with zipfile.ZipFile(path, 'w') as z:
        for name in names:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                z.writestr(name, '{}')
        z.writestr('package-manifest.json', '{}')
    with pytest.raises(ValueError):
        verify_package(path)


def test_extreme_compression_and_malformed_archives_rejected(tmp_path):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('bomb.body', 'A' * 100000)
        z.writestr('package-manifest.json', '{}')
    with pytest.raises(ValueError):
        verify_package(archive)
    archive.write_bytes(b'not a ZIP')
    assert package_main(['--verify-package', str(archive)]) == 2


@pytest.mark.parametrize('raw', [None, 'old', 'Wed, 01 Jan 2020 00:00:00 GMT', '2099-01-01T00:00:00Z'])
def test_stale_future_or_missing_source_markers_never_certify_freshness(raw):
    value = freshness([{'source_update_raw': raw, 'retrieved_at_utc': '2026-01-01T00:00:00Z'}])
    assert not value['freshness_certified']
    assert value['status'] == ('CONFLICTING_METADATA' if raw and raw.startswith('2099') else 'UNKNOWN')


def test_cross_source_parent_modification_match_is_not_applicability():
    p = {'node_id': 'node', 'source': 'fpds', 'native_action_id': 'literal', 'parent_action_modification_asserted': '0',
        'native_parent_pair': ['PARENT', '0002'], 'states': ['HISTORICAL_ACTION_ASSERTS_PARENT'], 'child_citation': {'source': 'fpds'}}
    value = parent_assessments({'historical_parent_assessments': [p]}, [{'row': {'modification_number': '0'},
        'native_action_components': {'piid': {'value': 'PARENT'}, 'agency': {'value': '0002'}}, 'citation': {'source': 'usaspending'}}])[0]
    assert value['parent_modification_records_observed']
    assert not value['historical_parent_applicability_established'] and not value['cross_source_parent_action_identity_established']


@pytest.mark.parametrize('mode', ['foreign_parent', 'foreign_agency', 'missing_pair', 'out_of_scope'])
def test_parent_candidates_require_exact_full_pair_and_supported_scope(mode):
    p = {'node_id': 'node', 'source': 'fpds', 'native_action_id': 'literal', 'parent_action_modification_asserted': '0',
        'native_parent_pair': ['PARENT', '0002'], 'states': ['HISTORICAL_ACTION_ASSERTS_PARENT'], 'child_citation': {'source': 'fpds'}}
    if mode == 'foreign_parent':
        p['native_parent_pair'][0] = 'FOREIGN'
    elif mode == 'foreign_agency':
        p['native_parent_pair'][1] = '9999'
    elif mode == 'missing_pair':
        p['native_parent_pair'][0] = None
    else:
        p['states'] = []
    record = {'row': {'modification_number': '0'}, 'native_action_components': {'piid': {'value': 'PARENT'}, 'agency': {'value': '0002'}}}
    result = parent_assessments({'historical_parent_assessments': [p]}, [record])[0]
    assert not result['parent_modification_records_observed']
    assert not result['historical_parent_applicability_established']


def test_deterministic_reports_do_not_authorize_financial_arithmetic(tmp_path):
    _, cases, *_ = captured(tmp_path)
    a, b = tmp_path / 'a', tmp_path / 'b'
    assert write_report(a, cases) == write_report(b, cases)
    assert inventory(a) == inventory(b) and verify_report(a, cases) == report(cases)
    result = report(cases)
    assert result['evidence_package_verification']['status'] == 'NOT_SUPPLIED'
    money = result['cases'][0]['monetary_compatibility']
    assert money['status'] == 'BLOCKED' and money['amount_comparisons_performed'] == 0
    assert all(not f['eligible_for_arithmetic'] for f in money['observed_fields'])


def test_HTML_is_static_escaped_and_fence_safe(tmp_path):
    _, cases, *_ = captured(tmp_path)
    r = report(cases);r['untrusted'] = '<script>alert(1)</script>```'
    html = projections(r)['coverage.html'].decode()
    assert '<script>' not in html and '&lt;script&gt;' in html and "default-src 'none'" in html
    assert '\\u0060' in projections(r)['coverage.md'].decode()


def test_legacy_C14_package_is_explicitly_supported_without_trusting_conclusions(tmp_path):
    root, _ = c14_staging(tmp_path)
    files = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    files['package-manifest.json'] = canonical({'schema_version': 1, 'files': {n: hashlib.sha256(b).hexdigest() for n, b in files.items()}}).encode()
    out = tmp_path / 'legacy.zip'
    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    result = verify_package(out)
    assert result['format'] == 'explicit_legacy_C14_v1' and result['primary_replay'] == 'verified'
    assert result['qualification_scope'] == 'packaged_cases_only_not_unincluded_cohort'


def test_C15_package_replays_nested_baseline_and_continuation_from_separate_inputs(tmp_path):
    _, cases, c12, old, continuation, _, _ = captured(tmp_path / 'source')
    root = tmp_path / 'stage';root.mkdir()
    for src, name in [(cases[0]['collections'][0], 'baseline'), (c12, 'c12'), (old, 'parent'), (continuation, 'continuation')]:
        shutil.copytree(src, root / name)
    baseline_stage, _ = c14_staging(tmp_path / 'baseline-source')
    build_package(baseline_stage, root / 'baseline-package.zip')
    relative = [{'collections': ['baseline'], 'c12_capture': 'c12', 'parent_history': 'parent',
        'continuation': 'continuation', 'scope': cases[0]['scope']}]
    absolute = [{**relative[0], 'collections': [str(root / 'baseline')],
        **{k: str(root / relative[0][k]) for k in ('c12_capture', 'parent_history', 'continuation')}}]
    (root / 'cases.json').write_text(canonical({'schema_version': 1, 'cases': relative, 'baseline_package': 'baseline-package.zip'}))
    baseline = root / 'baseline-package.zip'
    write_report(root / 'report', absolute, baseline_package=baseline)
    archive = tmp_path / 'c15.zip'
    result = build_package(root, archive, phase='C15')
    assert result['phase'] == 'C15' and result['primary_replay'] == 'verified'
    assert not result['resolved_real_source_plan_ids']
    assert verify_package(archive) == result
    with pytest.raises(ValueError):
        verify_package(archive, expected_phase='C14')


@pytest.mark.parametrize('mode', ['symlink', 'hardlink'])
def test_archive_outer_links_are_not_followed(tmp_path, mode):
    root, _ = c14_staging(tmp_path)
    archive = tmp_path / 'source.zip';build_package(root, archive)
    linked = tmp_path / 'linked.zip'
    if mode == 'symlink':
        linked.symlink_to(archive)
    else:
        os.link(archive, linked)
    with pytest.raises(ValueError):
        verify_package(linked)


@pytest.mark.parametrize('mode', ['financial', 'resolved', 'applicability'])
def test_all_projections_and_hashes_cannot_resign_false_qualification(tmp_path, mode):
    from src.correction_reporting import projections as c14_projections
    root, _ = c14_staging(tmp_path)
    source, altered = tmp_path / 'source.zip', tmp_path / 'false.zip'
    build_package(root, source)
    def change(files):
        false = json.loads(files['report/correction.json'])
        if mode == 'financial':
            false['financial_comparison_authorized'] = True
        elif mode == 'resolved':
            false['resolved_original_real_source_requirements'] = ['forged-real-proof']
        else:
            false['cases'][0]['historical_parent_assessments'][0]['historical_parent_applicability_established'] = True
        for name, raw in c14_projections(false).items():
            files['report/' + name] = raw
        commit = json.loads(files['report/correction-commit.json'])
        commit['report_sha256'] = digest(false)
        commit['files'] = {n.removeprefix('report/'): hashlib.sha256(b).hexdigest() for n, b in files.items() if n.startswith('report/') and n != 'report/correction-commit.json'}
        files['report/correction-commit.json'] = (canonical(commit) + '\n').encode()
        index = json.loads(files['evidence-index.json']);index['report_sha256'] = digest(false);files['evidence-index.json'] = (canonical(index) + '\n').encode()
    rewrite_zip(source, altered, change, resign=True)
    with pytest.raises(ValueError):
        verify_package(altered)


@pytest.mark.parametrize('key', ['financial_comparison_authorized', 'historical_parent_applicability_intervals_established', 'newly_resolved_real_source_requirements'])
def test_resigned_C15_report_cannot_upgrade_eligibility_or_original_requirements(tmp_path, key):
    _, cases, *_ = captured(tmp_path)
    target = tmp_path / 'report';write_report(target, cases)
    false = report(cases)
    false[key] = ['forged'] if key.endswith('requirements') else True if key == 'financial_comparison_authorized' else 1
    for name, raw in projections(false).items():
        (target / name).write_bytes(raw)
    hashes = {n: h for n, h in inventory(target).items() if n != 'coverage-commit.json'}
    (target / 'coverage-commit.json').write_text(canonical({'schema_version': 1, 'files': hashes, 'report_sha256': digest(false)}) + '\n')
    with pytest.raises(ValueError):
        verify_report(target, cases)


@pytest.mark.parametrize('failure_index', [0, 1])
def test_interruption_preserves_all_completed_evidence_and_pending_reservation(tmp_path, monkeypatch, failure_index):
    import src.parent_continuation as module
    _, _, c12, old, transcript = setup(tmp_path)
    transcript['responses'][0]['json']['page_metadata'].update(hasNext=True, next=3)
    original = module.FixtureTransport
    def interrupted(t):
        transport = original(t)
        def call(req, index):
            if index == failure_index:
                raise KeyboardInterrupt()
            return transport(req, index)
        return call
    monkeypatch.setattr(module, 'FixtureTransport', interrupted)
    target = tmp_path / 'interrupted'
    with pytest.raises(KeyboardInterrupt):
        collect(target, old, c12, synthetic=transcript)
    before = inventory(target)
    assert (target / f'continuation-{failure_index + 1:03d}-reservation.json').exists()
    if failure_index:
        assert (target / 'continuation-001.body').exists()
    with pytest.raises(ValueError):
        read(target, old, c12)
    assert inventory(target) == before


@pytest.mark.parametrize('currency', [None, 'USD', 'EUR', 'unknown'])
def test_negative_obligations_and_incompatible_units_never_become_losses(tmp_path, currency):
    def change(t):
        t['responses'][0]['json']['results'][0].update(federal_action_obligation=-123.45, currency=currency)
    _, cases, *_ = captured(tmp_path, change)
    value = report(cases)['cases'][0]['monetary_compatibility']
    field = next(f for f in value['observed_fields'] if f.get('record_role') == 'parent_IDV_action_observation'
        and f.get('original_field') == 'federal_action_obligation' and f['value'].get('raw_text') == '-123.45')
    assert not field['eligible_for_arithmetic'] and value['totals_or_deltas_computed'] == 0
    if currency not in (None, 'USD'):
        assert field['currency_compatibility'] == 'CONFLICTING_OR_UNKNOWN'
    summaries = [f for f in value['observed_fields'] if f['record_role'] == 'parent_IDV_summary']
    assert summaries and all(not f['field_semantics']['documented'] for f in summaries)


def test_overflowing_update_marker_is_unknown_and_not_current_clock_dependent():
    value = freshness([{'source_update_raw': '9999-12-31T23:59:59-23:59', 'retrieved_at_utc': '2026-01-01T00:00:00Z'}])
    assert not value['freshness_certified'] and value['observations'][0]['parsed_update_utc'] is None


@pytest.mark.parametrize('label', [None, 1, True, '', 'unsafe\n', 'x' * 81])
def test_invalid_acquisition_labels_rejected(tmp_path, label):
    _, _, c12, old, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        plan(old, c12, label=label)


def test_no_next_page_no_implicit_new_acquisition(tmp_path):
    import src.parent_history_probe as parent
    _, _, c12, _, _, transcript = c14_setup(tmp_path)
    terminal = tmp_path / 'terminal'
    parent.collect(terminal, c12, synthetic=transcript)
    with pytest.raises(ValueError):
        plan(terminal, c12)


def test_frozen_C14_protocols_and_documents_remain_identical():
    protocol = json.loads(Path('docs/parent-coverage-protocol-v1.json').read_text())
    assert len(protocol['frozen_files']) == 61
    for name, sha in protocol['frozen_files'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == sha


def test_two_separate_new_pages_close_only_the_observed_page_obligation(tmp_path):
    def change(t):
        page = t['responses'][0]['json'];page['page_metadata'].update(hasNext=True, next=3)
        last = deepcopy(page)
        last['page_metadata'].update(page=3, previous=2, next=None, hasNext=False)
        last['results'][0].update(id=last['results'][0]['id'].replace('_1_-NONE-_-NONE-', '_2_-NONE-_-NONE-'), modification_number='2', action_date='2018-01-01')
        t['responses'].append({'source': 'usaspending', 'json': last})
    _, _, _, _, _, value, _ = captured(tmp_path, change)
    assert value['request_attempts'] == 2 and value['combined_pagination']['observed_pages'] == [1, 2, 3]
    assert value['observed_terminal_query_chain'] and value['source_query_recall'] == 'unknown'
    assert value['snapshot_consistency'] == 'unknown' and not value['historical_parent_applicability_established']


def test_later_response_after_terminal_cannot_be_resigned_into_history(tmp_path):
    _, _, c12, old, target, *_ = captured(tmp_path)
    def change(p):
        for suffix in ('.body', '.json', '-reservation.json'):
            shutil.copyfile(p / ('continuation-001' + suffix), p / ('continuation-002' + suffix))
    resign_capture(target, change)
    with pytest.raises(ValueError):
        read(target, old, c12)


def test_changed_original_anchor_rejects_continuation_and_preserves_acquisition(tmp_path):
    _, _, c12, old, target, *_ = captured(tmp_path)
    before = inventory(target)
    (old / 'parent-001.body').write_text('{}')
    with pytest.raises(ValueError):
        read(target, old, c12)
    assert inventory(target) == before


@pytest.mark.parametrize('metadata', [{'retrieved_at_utc': None}, {'source_update_raw': 'bad\n'}, {'body_complete': 1}])
def test_bad_provenance_retains_uncommitted_bounded_transport_evidence(tmp_path, metadata):
    _, _, c12, old, transcript = setup(tmp_path)
    transcript['responses'][0].update(metadata)
    target = tmp_path / 'bad-provenance'
    with pytest.raises(ValueError):
        collect(target, old, c12, synthetic=transcript)
    assert (target / 'continuation-001.body').exists() and not (target / 'continuation-commit.json').exists()
    with pytest.raises(ValueError):
        read(target, old, c12)


@pytest.mark.parametrize('filename', ['baseline/secret.json', 'baseline/evil.py', 'c12/token.txt'])
def test_even_resigned_extra_files_inside_declared_roots_are_not_exported(tmp_path, filename):
    root, _ = c14_staging(tmp_path)
    source, altered = tmp_path / 'original.zip', tmp_path / 'extra.zip'
    build_package(root, source)
    rewrite_zip(source, altered, lambda f: f.__setitem__(filename, b'not source evidence'), resign=True)
    with pytest.raises((ValueError, KeyError)):
        verify_package(altered)


def test_existing_archive_cannot_be_overwritten_or_created_under_primary_root(tmp_path):
    root, _ = c14_staging(tmp_path)
    target = tmp_path / 'out.zip';build_package(root, target)
    before = target.read_bytes()
    with pytest.raises((ValueError, FileExistsError)):
        build_package(root, target)
    assert target.read_bytes() == before
    with pytest.raises(ValueError):
        build_package(root, root / 'in-place.zip')


def test_valid_but_unrelated_package_cannot_be_claimed_as_baseline_reproduction(tmp_path):
    from src.correction_reporting import write_report as c14_write
    root, _ = c14_staging(tmp_path / 'packaged-source')
    other = tmp_path / 'other';other.mkdir()
    shutil.copytree(root / 'baseline', other / 'baseline')
    source_cases = json.loads((root / 'cases.json').read_text())
    relative = [{'collections': ['baseline'], 'scope': source_cases[0]['scope']}]
    (other / 'cases.json').write_text(canonical(relative))
    c14_write(other / 'report', [{'collections': [str(other / 'baseline')], 'scope': relative[0]['scope']}])
    archive = tmp_path / 'other.zip';build_package(other, archive)
    _, cases, *_ = captured(tmp_path / 'evaluated-source')
    with pytest.raises(ValueError):
        report(cases, baseline_package=archive)


def test_unavailable_original_package_is_not_reported_verified(tmp_path):
    _, cases, *_ = captured(tmp_path)
    value = report(cases)
    assert not value['evidence_package_verification']['independent_primary_replay_claimed']
    with pytest.raises((ValueError, OSError)):
        report(cases, baseline_package=tmp_path / 'unavailable.zip')


@pytest.mark.parametrize('flags', [['--live'], ['--capture-continuation'], ['--plan-continuation', '--capture-continuation'], ['--live', '--capture-continuation']])
def test_invalid_CLI_modes_cannot_initialize_source_collection(tmp_path, monkeypatch, flags):
    import src.parent_coverage_reporting as module
    monkeypatch.setattr(module, 'collect', lambda *_a, **_kw: pytest.fail('unexpected live collection'))
    recipe = tmp_path / 'cases.json';recipe.write_text('[{}]')
    assert main(['--cases', str(recipe), '--output', str(tmp_path / 'none'), *flags]) == 2


def test_original_v1_rejection_and_v2_reassessment_remain_separate_after_continuation(tmp_path):
    from src.parent_history_probe import read as read_parent
    _, _, c12, old, target, *_ = captured(tmp_path)
    value = read_parent(old, c12)
    assert value['capture_contract_version'] == 1 and value['failures'] and not value['records']
    assert value['record_reassessment']['records'] and not value['record_reassessment']['capture_repaired_or_resumed']
    assert read(target, old, c12)['parent_inventory_sha256'] == value['inventory_sha256']


def test_dictionary_limits_are_not_silently_defaulted(tmp_path):
    _, _, c12, old, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        plan(old, c12, limits={})


def test_planner_CLI_needs_no_report_directory_and_never_collects(tmp_path, monkeypatch, capsys):
    import src.parent_coverage_reporting as module
    _, cases, *_ = setup(tmp_path)
    recipe = tmp_path / 'recipe.json';recipe.write_text(canonical(cases))
    monkeypatch.setattr(module, 'collect', lambda *_a, **_kw: pytest.fail('unexpected collection'))
    assert main(['--cases', str(recipe), '--plan-continuation']) == 0
    assert json.loads(capsys.readouterr().out)['start_page'] == 2


@pytest.mark.parametrize('manifest', [None, [], 'text', 1, {'schema_version': 1, 'files': {'cases.json': None}}])
def test_malformed_manifest_types_are_validation_errors(tmp_path, manifest):
    archive = tmp_path / 'bad-types.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('package-manifest.json', canonical(manifest))
        z.writestr('cases.json', '[]')
    with pytest.raises(ValueError):
        verify_package(archive)


def test_corrupt_deflate_stream_is_a_validation_error_without_traceback(tmp_path, capsys):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('package-manifest.json', '{"schema_version":1,"files":{}}')
    damaged = bytearray(raw.getvalue())
    # Reserved DEFLATE block type, after the fixed local header and filename.
    damaged[30 + len('package-manifest.json')] = 7
    path = tmp_path / 'corrupt-stream.zip';path.write_bytes(damaged)
    with pytest.raises(ValueError):
        verify_package(path)
    assert package_main(['--verify-package', str(path)]) == 2
    assert json.loads(capsys.readouterr().out)['error_code'] == 'evidence_package_rejected'
