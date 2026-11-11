"""C16 offline controls. All fixture identities and responses are synthetic."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from src.authority_binding import plan, collect, read, parent_sources, candidate_plan
from src.authority_reporting import report, write_report, verify_report, projections, main
from src.evidence_io import canonical, digest
from src.evidence_package import build_package, verify_package, verified_directory
from src.history_demo import fixture, collect_fixture
from src.scope_models import ScopeRequest
from tests.test_parent_coverage import captured, c14_staging, rewrite_zip
from tests.test_evidence_acquisition import inventory


@pytest.fixture(scope='module')
def context(tmp_path_factory):
    from src.parent_coverage_reporting import write_report as write_c15
    tmp = tmp_path_factory.mktemp('authority-synthetic')
    _, cases, c12, old, continuation, _, _ = captured(tmp / 'seed')
    stage = tmp / 'stage';stage.mkdir()
    for src, name in [(cases[0]['collections'][0], 'baseline'), (c12, 'c12'), (old, 'parent'), (continuation, 'continuation')]:
        shutil.copytree(src, stage / name)
    baseline_stage, _ = c14_staging(tmp / 'old')
    build_package(baseline_stage, stage / 'baseline-package.zip')
    relative = [{'collections': ['baseline'], 'c12_capture': 'c12', 'parent_history': 'parent',
        'continuation': 'continuation', 'scope': cases[0]['scope']}]
    absolute = [{**relative[0], 'collections': [str(stage / 'baseline')],
        **{k: str(stage / relative[0][k]) for k in ('c12_capture', 'parent_history', 'continuation')}}]
    (stage / 'cases.json').write_text(canonical({'schema_version': 1, 'cases': relative, 'baseline_package': 'baseline-package.zip'}))
    write_c15(stage / 'report', absolute, baseline_package=stage / 'baseline-package.zip')
    archive = tmp / 'c15.zip';build_package(stage, archive, phase='C15')
    # A separate original child, literal fixture native identifier, same parent.
    a, data = fixture('equal_control')
    old_piid = a.piid
    a = replace(a, piid='SYNTH-SECOND-00001', generated_id='SYNTHETIC-NATIVE-CHILD-SECOND')
    for row in data['responses'][0]['json']['results']:
        row['id'] = row['id'].replace(old_piid, a.piid)
    for response in data['responses']:
        if response['source'] == 'fpds':
            response['text'] = response['text'].replace(old_piid, a.piid)
    child_root = tmp / 'second';collect_fixture(child_root, a, data)
    scope = ScopeRequest(piid=a.piid, agency=a.agency_id, parent_piid=a.parent_piid, parent_agency=a.parent_agency_id)
    target = {'collections': [str(child_root)], 'scope': scope.to_dict()}
    transcript = {'schema_version': 1, 'responses': [{'source': 'usaspending', 'json': {
        'generated_unique_award_id': a.generated_id, 'piid': a.piid, 'category': 'contract', 'type': 'C',
        'parent_award': {'generated_unique_award_id': 'SOURCE-NATIVE-PARENT-001',
            'piid': a.parent_piid, 'sub_agency_id': a.parent_agency_id}}}]}
    return archive, absolute[0], target, transcript


def captured_binding(tmp_path, context, change=None):
    archive, prior, target, transcript = context
    transcript = deepcopy(transcript)
    if change:
        change(transcript)
    out = tmp_path / 'binding'
    value = collect(out, target, archive, synthetic=transcript)
    return out, [{**prior}, {**target, 'authority_binding': str(out)}], value


def resign(root, change):
    change(root)
    files = {n: h for n, h in inventory(root).items() if n != 'binding-commit.json'}
    (root / 'binding-commit.json').write_text(canonical({'schema_version': 1, 'files': files}) + '\n')


def test_exact_binding_resolves_only_original_identity_not_history(context, tmp_path):
    archive, prior, target, _ = context
    before = inventory(target['collections'][0])
    out, cases, value = captured_binding(tmp_path, context)
    assert value == read(out, target, archive)
    assert value['claim_status'] == 'VERIFIED_SOURCE_LOCAL_REFERENCE'
    r = report(cases, baseline_package=archive)
    assert len(r['newly_resolved_synthetic_requirements']) == 1
    assert not r['newly_resolved_real_source_requirements']
    assert len(r['previously_resolved_synthetic_requirements']) == 1
    assert set(r['newly_resolved_synthetic_requirements']) <= set(r['baseline']['remaining_original_plan_ids'])
    assert not r['historical_parent_applicability_intervals_established']
    assert not r['authoritative_real_source_correction_edges']
    assert not r['new_authoritative_cross_source_identities']
    assert not r['new_parent_action_observations']
    assert not r['financial_comparison_authorized'] and not r['production_readiness_changed']
    assert r['cases'][1]['closure']['dimension'] == 'parent_identity'
    assert r['cases'][1]['closure']['preserved_parent_evidence']['new_source_observations_on_replay'] == 0
    assert r['evidence_classes']['binding'] == 'SYNTHETIC_FIXTURE'
    assert inventory(target['collections'][0]) == before


@pytest.mark.parametrize('field,bad', [('piid', 'WRONG'), ('piid', 'SYNTH-SECOND-1'),
    ('generated_unique_award_id', 'RECONSTRUCTED'), ('generated_unique_award_id', '../escape'),
    ('category', 'idv'), ('type', 'IDV_B'), ('type', None), ('type', 1)])
def test_conflicting_or_unsupported_child_never_resolves(context, tmp_path, field, bad):
    _, cases, v = captured_binding(tmp_path, context, lambda t: t['responses'][0]['json'].__setitem__(field, bad))
    assert v['failures']
    assert not report(cases, baseline_package=context[0])['newly_resolved_synthetic_requirements']


@pytest.mark.parametrize('field', ['piid', 'sub_agency_id', 'generated_unique_award_id'])
@pytest.mark.parametrize('bad', [None, '', 'WRONG', 1, True, '../x', '0000'])
def test_exact_parent_native_triple_required(context, tmp_path, field, bad):
    _, cases, v = captured_binding(tmp_path, context, lambda t: t['responses'][0]['json']['parent_award'].__setitem__(field, bad))
    assert v['failures']
    assert not report(cases, baseline_package=context[0])['newly_resolved_synthetic_requirements']


@pytest.mark.parametrize('mode', ['missing', 'null', 'string'])
def test_missing_parent_is_unknown_not_absence(context, tmp_path, mode):
    def change(t):
        d = t['responses'][0]['json']
        if mode == 'missing':
            d.pop('parent_award')
        else:
            d['parent_award'] = None if mode == 'null' else 'SYNTH-PARENT'
    _, _, v = captured_binding(tmp_path, context, change)
    assert v['failures'] and not v['historical_parent_applicability_established']


@pytest.mark.parametrize('status', [301, 302, 401, 403, 404, 429, 500, 503])
def test_failed_api_preserves_observation_without_retry_or_resolution(context, tmp_path, status):
    out, cases, v = captured_binding(tmp_path, context, lambda t: t['responses'][0].__setitem__('status', status))
    assert v['request_attempts'] == 1 and v['failures']
    assert not (out / 'binding-002.json').exists()
    assert not report(cases, baseline_package=context[0])['newly_resolved_synthetic_requirements']


@pytest.mark.parametrize('file', ['pilot-plan.json', 'binding-001.json', 'binding-001.body', 'binding-001-reservation.json', 'binding-commit.json'])
def test_interrupted_capture_is_preserved_never_repaired(context, tmp_path, file):
    out, _, _ = captured_binding(tmp_path, context)
    (out / file).unlink()
    before = inventory(out)
    with pytest.raises(ValueError):
        read(out, context[2], context[0])
    assert inventory(out) == before


@pytest.mark.parametrize('field,value', [('representation', 'HTTP_entity_bytes_after_content_decoding'),
    ('body_sha256', '0'*64), ('request', {'source': 'fpds'})])
def test_manipulated_provenance_even_with_rehashed_manifest_rejected(context, tmp_path, field, value):
    out, _, _ = captured_binding(tmp_path, context)
    def change(p):
        meta = json.loads((p / 'binding-001.json').read_text());meta[field] = value
        (p / 'binding-001.json').write_text(canonical(meta) + '\n')
    resign(out, change)
    with pytest.raises(ValueError):
        read(out, context[2], context[0])


@pytest.mark.parametrize('field,bad', [('status', 201), ('body_complete', False), ('retrieved_at_utc', None), ('attempt', 2)])
def test_unsupported_response_metadata_rejected_or_unresolved(context, tmp_path, field, bad):
    out, _, _ = captured_binding(tmp_path, context)
    def change(p):
        meta = json.loads((p / 'binding-001.json').read_text());meta['response'][field] = bad
        (p / 'binding-001.json').write_text(canonical(meta) + '\n')
    resign(out, change)
    try:
        v = read(out, context[2], context[0])
    except ValueError:
        return
    assert v['failures']


def test_default_offline_and_synthetic_live_confusion_rejected(context, tmp_path, monkeypatch):
    import src.authority_binding as module
    monkeypatch.setattr(module, 'HTTPTransport', lambda *_: pytest.fail('network initialized'))
    archive, _, target, transcript = context
    for kw in ({}, {'live': True}, {'live': True, 'synthetic': transcript}, {'live': 1}):
        with pytest.raises(ValueError):
            collect(tmp_path / 'no', target, archive, **kw)
    assert not (tmp_path / 'no').exists()


def test_reports_recomputed_static_escaped_and_deterministic(context, tmp_path):
    _, cases, _ = captured_binding(tmp_path, context)
    a, b = tmp_path / 'a', tmp_path / 'b'
    assert write_report(a, cases, baseline_package=context[0]) == write_report(b, cases, baseline_package=context[0])
    assert inventory(a) == inventory(b)
    r = verify_report(a, cases, baseline_package=context[0])
    assert not r['cases'][1]['monetary_compatibility']['totals_or_deltas_computed']
    r['limitations'].append('<script>alert(1)</script>```')
    rendered = projections(r)
    assert b'<script>' not in rendered['authority.html'] and b'&lt;script&gt;' in rendered['authority.html']
    assert '\\u0060' in rendered['authority.md'].decode()


@pytest.mark.parametrize('file', ['authority.json', 'authority.md', 'authority.html', 'authority-commit.json', 'pilot-plan.json'])
def test_tampered_or_truncated_reports_rejected(context, tmp_path, file):
    _, cases, _ = captured_binding(tmp_path, context)
    out = tmp_path / 'report';write_report(out, cases, baseline_package=context[0])
    (out / file).write_bytes(b'{}')
    with pytest.raises(ValueError):
        verify_report(out, cases, baseline_package=context[0])


def test_duplicate_case_or_capture_cannot_double_credit(context, tmp_path):
    _, cases, _ = captured_binding(tmp_path, context)
    with pytest.raises(ValueError):
        report(cases + [cases[1]], baseline_package=context[0])
    with pytest.raises(ValueError):
        plan(context[1], context[0])  # already resolved, not eligible


def test_exact_original_scope_and_parent_package_required(context):
    archive, _, target, _ = context
    changed = deepcopy(target);changed['scope']['agency'] = '9999'
    with pytest.raises(ValueError):
        plan(changed, archive)


def test_C16_package_replays_raw_binding_and_nested_primary_chain(context, tmp_path):
    out, cases, _ = captured_binding(tmp_path, context)
    stage = tmp_path / 'export';stage.mkdir()
    relative, absolute = [], []
    for i, c in enumerate(cases):
        rel, abs_case = deepcopy(c), deepcopy(c)
        for k in ('collections', 'c12_capture', 'parent_history', 'continuation', 'authority_binding'):
            if k not in c:
                continue
            values = c[k] if k == 'collections' else [c[k]]
            names = [f'case-{i}-{k}-{j}' for j in range(len(values))]
            for value, name in zip(values, names):
                shutil.copytree(value, stage / name)
            rel[k] = names if k == 'collections' else names[0]
            paths = [str(stage / n) for n in names]
            abs_case[k] = paths if k == 'collections' else paths[0]
        relative.append(rel);absolute.append(abs_case)
    shutil.copyfile(context[0], stage / 'baseline-package.zip')
    (stage / 'cases.json').write_text(canonical({'schema_version': 1, 'cases': relative, 'baseline_package': 'baseline-package.zip'}))
    write_report(stage / 'report', absolute, baseline_package=stage / 'baseline-package.zip')
    archive = tmp_path / 'c16.zip';receipt = build_package(stage, archive, phase='C16')
    assert receipt == verify_package(archive, expected_phase='C16')
    assert not receipt['resolved_real_source_plan_ids']
    for phase in ('C14', 'C15'):
        with pytest.raises(ValueError):
            verify_package(archive, expected_phase=phase)
    bad = tmp_path / 'bad.zip'
    rewrite_zip(archive, bad, lambda files: files.__setitem__('report/authority.json', b'{}'), resign=True)
    with pytest.raises(ValueError):
        verify_package(bad)


def test_cli_plan_has_no_network_and_conflicting_flags_fail(context, tmp_path, capsys):
    archive, prior, target, _ = context
    recipe = tmp_path / 'cases.json'
    recipe.write_text(canonical([{**prior}, {**target, 'authority_binding': str(tmp_path / 'new')}]))
    args = ['--cases', str(recipe), '--baseline-package', str(archive)]
    assert main(args + ['--plan-binding']) == 0
    assert json.loads(capsys.readouterr().out)['maximum_requests'] == 1
    assert main(args + ['--plan-binding', '--live']) == 2
    assert main(args + ['--plan-binding', '--capture-binding', '--live']) == 2
    assert not (tmp_path / 'new').exists()


@pytest.fixture(scope='module')
def native_graph(context):
    from src.correction_reporting import report as c14_report
    return c14_report([context[2]])['cases'][0]['observation_graph']


def rehash_node(raw):
    from src.revision_lineage import LineageObservation
    raw['node_id'] = LineageObservation.from_dict({k: v for k, v in raw.items() if k != 'node_id'}).node_id


def test_existing_cross_source_identity_has_no_revision_or_money_authority(native_graph):
    from src.authority_identity import audit
    r = audit(native_graph)
    assert any(a['status'] == 'VERIFIED_CROSS_SOURCE_IDENTITY' for a in r['associations'])
    assert all(not a['common_revision_established'] and not a['financial_comparison_authorized'] for a in r['associations'])
    assert not r['new_authoritative_cross_source_mappings']


@pytest.mark.parametrize('field', ['piid', 'agency', 'parent_piid', 'parent_agency', 'modification', 'transaction'])
@pytest.mark.parametrize('bad', ['UNMATCHED', None])
def test_partial_or_conflicting_native_components_never_join(native_graph, field, bad):
    from src.authority_identity import audit
    graph = deepcopy(native_graph)
    for node in graph['nodes']:
        if node['source'] != 'fpds':
            continue
        c = json.loads(node['native_context_json']);c[field] = bad
        node['native_context_json'] = canonical(c)
        if bad is None and field in ('piid', 'agency', 'modification', 'transaction'):
            node['identity_supported'] = False
        rehash_node(node)
    r = audit(graph)
    assert all(a['status'] != 'VERIFIED_CROSS_SOURCE_IDENTITY' for a in r['associations'])


@pytest.mark.parametrize('field,bad', [('existing_native_scope_verified', False), ('outside_requested_context', True), ('identity_supported', False)])
def test_verified_scope_is_required_even_for_identical_strings(native_graph, field, bad):
    from src.authority_identity import audit
    graph = deepcopy(native_graph)
    for n in graph['nodes']:
        if n['source'] == 'fpds':
            n[field] = bad;rehash_node(n)
    r = audit(graph)
    assert r['unsupported_observations']
    assert all(a['status'] != 'VERIFIED_CROSS_SOURCE_IDENTITY' for a in r['associations'])


def test_competing_content_keeps_conflict_and_duplicate_is_not_corroboration(native_graph):
    from src.authority_identity import audit
    graph = deepcopy(native_graph)
    variant = deepcopy(graph['nodes'][0]);variant['original_occurrence_id'] += '-variant'
    variant['content_sha256'] = '0' * 64;rehash_node(variant)
    graph['nodes'].append(variant)
    r = audit(graph)
    assert any(a['status'] == 'CONFLICTING_OBSERVATIONS' for a in r['associations'])
    graph['nodes'].append(deepcopy(variant))
    with pytest.raises(ValueError):
        audit(graph)


def test_tampered_node_identifier_and_mixed_provenance_rejected(native_graph):
    from src.authority_identity import audit
    graph = deepcopy(native_graph);graph['nodes'][0]['node_id'] = 'forged'
    with pytest.raises(ValueError):
        audit(graph)
    graph = deepcopy(native_graph);graph['nodes'][0]['profile'] = 'live';rehash_node(graph['nodes'][0])
    with pytest.raises(ValueError):
        audit(graph)


@pytest.mark.parametrize('field', ['action_date', 'content_sha256'])
def test_date_or_hash_similarity_does_not_supply_missing_native_mapping(native_graph, field):
    from src.authority_identity import audit
    graph = deepcopy(native_graph)
    first = graph['nodes'][0]
    for n in graph['nodes']:
        n[field] = first[field]
        if n['source'] == 'fpds':
            c = json.loads(n['native_context_json']);c['piid'] = 'DIFFERENT'
            n['native_context_json'] = canonical(c)
        rehash_node(n)
    assert all(a['status'] != 'VERIFIED_CROSS_SOURCE_IDENTITY' for a in audit(graph)['associations'])


def test_source_matrix_is_documented_not_live_validation_or_approval():
    matrix = json.loads(Path('docs/historical-source-authority-v1.json').read_text())
    assert {r['status'] for r in matrix['capabilities']} <= {'DOCUMENTED', 'DIRECTLY OBSERVED', 'UNVERIFIED', 'UNSUPPORTED'}
    assert not matrix['new_real_correction_edges'] and not matrix['historical_parent_intervals']
    assert not matrix['financial_comparison_authorized']
    sam = [r for r in matrix['capabilities'] if r['source'] == 'samgov']
    assert not any(r['status'] == 'DIRECTLY OBSERVED' for r in sam)


def test_original_frozen_documents_are_byte_identical():
    p = json.loads(Path('docs/historical-authority-protocol-v1.json').read_text())
    assert len(p['frozen_files']) == 63
    for name, expected in p['frozen_files'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize('marker', [None, '1999-01-01T00:00:00Z', 'malformed', '2026-01-01T00:00:00Z'])
def test_freshness_separate_and_contradictory_update_cannot_resolve(context, tmp_path, marker):
    _, cases, v = captured_binding(tmp_path, context, lambda t: t['responses'][0].__setitem__('source_update_raw', marker))
    assert not v['freshness']['freshness_certified']
    assert not v['historical_parent_applicability_established']
    if marker == '2026-01-01T00:00:00Z':
        assert v['failures']
        assert not report(cases, baseline_package=context[0])['newly_resolved_synthetic_requirements']
    else:
        assert v['freshness']['status'] == 'UNKNOWN'
