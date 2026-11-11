"""Offline C14 adversarial controls. No real federal correction certificates."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import os

import pytest

from src.correction_reporting import report, write_report, verify_report, projections, main
from src.evidence_io import EvidenceError, canonical, digest
from src.parent_history_probe import collect, read, plan_for, parse, request
from src.revision_authority import (RevisionStatement, DirectedRevision, RelationStatus,
    SYNTHETIC_RULE, directed_graph, statement_from_row)
from src.revision_lineage import LineageObservation
from tests.test_historical_lineage import node, variant
from tests.test_source_verification import capture
from tests.test_evidence_acquisition import inventory


def setup(tmp_path, change=None):
    root, cases, _, c12, _ = capture(tmp_path / 'seed')
    plan = plan_for(c12)
    a = plan['selection']
    row = {'id': f"CONT_TX_{a['agency_id']}_-NONE-_{a['piid']}_0_-NONE-_0",
        'type': 'IDV_B', 'action_date': '2016-01-01', 'modification_number': '0',
        'federal_action_obligation': 0, 'description': 'Synthetic parent record'}
    body = {'results': [row], 'page_metadata': {'page': 1, 'next': None,
        'previous': None, 'hasNext': False, 'hasPrevious': False}}
    transcript = {'schema_version': 1, 'responses': [{'source': 'usaspending', 'json': body}]}
    if change:
        change(transcript)
    out = tmp_path / 'parent'
    value = collect(out, c12, synthetic=transcript)
    cases = [{**cases[0], 'c12_capture': str(c12), 'parent_history': str(out)}]
    return root, cases, c12, out, value, transcript


def statement(before, after, **kwargs):
    return RevisionStatement(profile=after.profile, source=after.source,
        successor_node_id=after.node_id, predecessor_native_id=before.native_action_id,
        predecessor_content_sha256=before.content_sha256, relation='corrects',
        applicable_at_utc='2026-01-01T00:00:00Z', rule_version=SYNTHETIC_RULE,
        citation_json=canonical({'synthetic_primary': 'explicit_fixture_statement'}), **kwargs)


def resign(path, commit, change):
    change(path)
    old = json.loads((path / commit).read_text())
    old['files'] = {n: h for n, h in inventory(path).items() if n != commit}
    (path / commit).write_text(canonical(old) + '\n')


def test_independent_parent_record_is_not_historical_applicability(tmp_path):
    root, cases, c12, out, value, _ = setup(tmp_path)
    before = inventory(root)
    assert value == read(out, c12)
    assert value['request_attempts'] == 1 and len(value['records']) == 1
    result = report(cases)
    assert result['new_synthetic_parent_action_records'] == 1
    assert result['new_real_source_parent_action_records'] == 0
    assert result['parent_record_supported_plan_ids'] and not result['real_source_partial_plan_ids']
    assert not result['resolved_original_real_source_requirements']
    assert len(result['resolved_original_synthetic_requirements']) == 1
    parents = result['cases'][0]['historical_parent_assessments']
    assert any('HISTORICAL_PARENT_RECORD_INDEPENDENTLY_LOCATED' in p['states'] for p in parents)
    assert all(not p['historical_parent_applicability_established'] for p in parents)
    assert all(not p['cross_source_parent_action_identity_established'] for p in parents)
    assert inventory(root) == before
    assert not result['financial_comparison_authorized'] and not result['production_readiness_changed']


def test_FPDS_reference_modification_retained_without_cross_source_promotion(tmp_path):
    from tests.test_evidence_acquisition import base
    _, cases = base(tmp_path / 'full', case='equal_control')
    fpds = [p for p in report(cases)['cases'][0]['historical_parent_assessments'] if p['source'] == 'fpds']
    assert fpds
    assert all(not p['new_parent_record_citations'] for p in fpds)
    assert all(not p['cross_source_parent_action_identity_established'] for p in fpds)


@pytest.mark.parametrize('field,bad', [('id', 'CONT_TX_9999_-NONE-_WRONG_0_-NONE-_0'),
    ('id', 'CONT_TX_0002_-NONE-_SYNTH-PARENT_P1_-NONE-_0'),
    ('id', 'unsupported'), ('modification_number', 'P2'), ('modification_number', None),
    ('type', 'C'), ('type', '04'), ('type', None), ('action_date', '2026-99-99')])
def test_malformed_parent_rows_cannot_become_located_records(tmp_path, field, bad):
    _, cases, _, _, value, _ = setup(tmp_path, lambda t: t['responses'][0]['json']['results'][0].__setitem__(field, bad))
    assert value['failures'] and not value['records']
    assert not report(cases)['synthetic_partial_plan_ids']


@pytest.mark.parametrize('key,bad', [('page', 2), ('next', 2), ('previous', 0),
    ('hasPrevious', True), ('hasNext', 'false'), ('next', False)])
def test_parent_pagination_contract_failures(tmp_path, key, bad):
    _, cases, _, _, value, _ = setup(tmp_path, lambda t: t['responses'][0]['json']['page_metadata'].__setitem__(key, bad))
    assert value['failures'] and not value['records']
    assert not report(cases)['synthetic_partial_plan_ids']


@pytest.mark.parametrize('code', [301, 302, 401, 403, 404, 429, 500, 503])
def test_parent_source_failures_are_preserved_without_retry(tmp_path, code):
    def change(t):
        t['responses'][0].update(status=code)
    _, cases, _, out, value, _ = setup(tmp_path, change)
    assert value['request_attempts'] == 1 and value['failures'] and not value['records']
    assert not (out / 'parent-002-reservation.json').exists()
    assert not report(cases)['synthetic_partial_plan_ids']


def test_empty_parent_page_does_not_prove_absence(tmp_path):
    _, cases, _, _, value, _ = setup(tmp_path, lambda t: t['responses'][0]['json'].__setitem__('results', []))
    assert not value['records'] and value['history_completeness'] == 'unknown'
    assert not report(cases)['synthetic_partial_plan_ids']


def test_incomplete_two_page_window_does_not_certify_history(tmp_path):
    def change(t):
        body = t['responses'][0]['json']
        body['page_metadata'].update(next=2, hasNext=True)
        second = deepcopy(body)
        second['results'][0].update(id=body['results'][0]['id'].replace('_0_-NONE-_0', '_P1_-NONE-_0'), modification_number='P1', action_date='2017-01-01')
        second['page_metadata'].update(page=2, previous=1, hasPrevious=True, next=3)
        t['responses'].append({'source': 'usaspending', 'json': second})
    _, cases, _, out, value, _ = setup(tmp_path, change)
    assert value['request_attempts'] == 2 and len(value['records']) == 2
    assert value['history_completeness'] == 'unknown'
    assert not (out / 'parent-003.json').exists()
    assert len(report(cases)['resolved_original_synthetic_requirements']) == 1
    assert all(not p['original_requirement_resolved'] for p in report(cases)['cases'][0]['original_requirement_impacts'] if p['dimension'] != 'parent_identity')


@pytest.mark.parametrize('mode', ['duplicate', 'variant', 'reverse_dates'])
def test_parent_record_conflicts_block_partial_credit(tmp_path, mode):
    def change(t):
        row = t['responses'][0]['json']['results'][0]
        other = deepcopy(row)
        if mode == 'variant':
            other['federal_action_obligation'] = -99
        elif mode == 'reverse_dates':
            other.update(id=other['id'].replace('_0_-NONE-_0', '_P1_-NONE-_0'), modification_number='P1', action_date='2015-01-01')
        t['responses'][0]['json']['results'].append(other)
    _, cases, _, _, value, _ = setup(tmp_path, change)
    assert value['failures'] and not report(cases)['synthetic_partial_plan_ids']


@pytest.mark.parametrize('name', ['parent-001-reservation.json', 'parent-001.json', 'parent-001.body', 'parent-commit.json'])
def test_interrupted_parent_history_is_never_repaired(tmp_path, name):
    _, _, c12, out, *_ = setup(tmp_path)
    (out / name).unlink()
    before = inventory(out)
    with pytest.raises((ValueError, KeyError)):
        read(out, c12)
    assert inventory(out) == before


@pytest.mark.parametrize('mode', ['request', 'representation', 'reservation', 'body', 'extra', 'plan', 'anchor'])
def test_even_resigned_parent_capture_rejects_semantic_tampering(tmp_path, mode):
    _, _, c12, out, *_ = setup(tmp_path)
    def change(path):
        if mode == 'extra':
            (path / 'extra.json').write_text('{}')
        elif mode == 'body':
            (path / 'parent-001.body').write_text('{}')
        elif mode == 'anchor':
            (c12 / 'detail-001.body').write_text('{}')
        else:
            name = 'parent-001-reservation.json' if mode == 'reservation' else 'pilot-plan.json' if mode == 'plan' else 'parent-001.json'
            data = json.loads((path / name).read_text())
            if mode == 'representation':
                data['representation'] = 'HTTP_wire_bytes'
            elif mode == 'plan':
                data['maximum_requests'] = 100
            else:
                data['request']['endpoint'] = 'https://unapproved.invalid/'
            (path / name).write_text(canonical(data) + '\n')
    resign(out, 'parent-commit.json', change)
    with pytest.raises((ValueError, KeyError)):
        read(out, c12)


@pytest.mark.parametrize('mode', ['symlink', 'hardlink'])
def test_parent_capture_rejects_link_substitution(tmp_path, mode):
    _, _, c12, out, *_ = setup(tmp_path)
    target = tmp_path / 'copied-body'
    target.write_bytes((out / 'parent-001.body').read_bytes())
    (out / 'parent-001.body').unlink()
    if mode == 'symlink':
        (out / 'parent-001.body').symlink_to(target)
    else:
        os.link(target, out / 'parent-001.body')
    with pytest.raises(ValueError):
        read(out, c12)


def test_offline_probe_never_initializes_HTTP_or_reads_credentials(tmp_path, monkeypatch):
    import src.parent_history_probe as module
    monkeypatch.setattr(module, 'HTTPTransport', lambda *_: pytest.fail('network initialized'))
    _, _, c12, out, _, transcript = setup(tmp_path)
    with pytest.raises(ValueError):
        collect(tmp_path / 'second', c12)
    with pytest.raises(ValueError):
        collect(tmp_path / 'second', c12, live=True)
    with pytest.raises(ValueError):
        collect(tmp_path / 'second', c12, live=True, synthetic=transcript)
    with pytest.raises((ValueError, FileExistsError)):
        collect(out, c12, synthetic=transcript)


def test_synthetic_explicit_directed_relation_preserves_both_observations(tmp_path):
    before = node(tmp_path)
    after = variant(before, 'after')
    result = directed_graph((before, after), (statement(before, after),))
    assert len(result['edges']) == result['explicit_synthetic_relationships'] == 1
    edge = result['edges'][0]
    assert edge['predecessor'] == before.node_id and edge['successor'] == after.node_id
    assert not edge['correction_winner_selected'] and not edge['financial_comparison_authorized']
    assert not result['established_real_source_revision_relationships']
    assert not result['correction_winners']
    assert DirectedRevision.from_dict(edge).to_dict() == edge


@pytest.mark.parametrize('field,value', [('profile', 'live'), ('source', 'samgov'),
    ('rule_version', 'later_timestamp'), ('predecessor_native_id', 'missing'),
    ('predecessor_content_sha256', '0' * 64), ('successor_node_id', 'revision-node:v1:' + '0' * 64)])
def test_unsupported_or_unbound_revision_claims_do_not_create_edges(tmp_path, field, value):
    before = node(tmp_path)
    after = variant(before, 'after')
    s = replace(statement(before, after), **{field: value})
    result = directed_graph((before, after), (s,))
    assert not result['edges'] and result['unresolved']


@pytest.mark.parametrize('field,value', [('predecessor_native_id', ''), ('predecessor_native_id', 'x\n'),
    ('predecessor_content_sha256', 'short'), ('relation', 'later'), ('applicable_at_utc', '2026-01-01'),
    ('citation_json', '{}'), ('citation_json', '[]'), ('schema_version', 2)])
def test_invalid_revision_statement_schema_rejected(tmp_path, field, value):
    before = node(tmp_path)
    after = variant(before, 'after')
    with pytest.raises(ValueError):
        replace(statement(before, after), **{field: value})


@pytest.mark.parametrize('kind', ['context', 'missing_component', 'outside_scope', 'unsupported_identity'])
def test_reused_modifications_or_partial_context_cannot_support_revision(tmp_path, kind):
    before = node(tmp_path)
    after = variant(before, 'after')
    if kind in ('context', 'missing_component'):
        context = json.loads(after.native_context_json)
        context['parent_piid'] = 'DIFFERENT' if kind == 'context' else None
        after = replace(after, native_context_json=canonical(context))
    else:
        after = replace(after, **({'outside_requested_context': True} if kind == 'outside_scope' else {'identity_supported': False}))
    r = directed_graph((before, after), (statement(before, after),))
    assert not r['edges'] and r['unresolved']


@pytest.mark.parametrize('mode', ['cycle', 'fork', 'contradictory_relation'])
def test_conflicting_directed_assertions_preserved_without_winner(tmp_path, mode):
    a = node(tmp_path)
    b, c = variant(a, 'B'), variant(a, 'C')
    first = statement(a, b)
    second = statement(b, a) if mode == 'cycle' else statement(a, c) if mode == 'fork' else replace(first, relation='reinstates')
    result = directed_graph((a, b, c), (first, second))
    assert len(result['edges']) == 2 and result['conflicts']
    assert all(e['status'] == RelationStatus.CONFLICTING.value for e in result['edges'])
    assert not result['correction_winners'] and not result['explicit_synthetic_relationships']


def test_duplicate_statements_and_ambiguous_predecessors_rejected(tmp_path):
    a = node(tmp_path)
    b = variant(a, 'B')
    s = statement(a, b)
    with pytest.raises(ValueError):
        directed_graph((a, b), (s, s))
    repeated = replace(a, original_occurrence_id='another-preserved-occurrence')
    result = directed_graph((a, b, repeated), (s,))
    assert not result['edges'] and result['unresolved'][0]['reason'] == 'missing_or_ambiguous_exact_predecessor_occurrence'


@pytest.mark.parametrize('field', ['correction_winner_selected', 'historical_completeness_certified', 'financial_comparison_authorized'])
def test_directed_edge_cannot_authorize_winner_completeness_or_arithmetic(tmp_path, field):
    a = node(tmp_path)
    b = variant(a, 'B')
    edge = directed_graph((a, b), (statement(a, b),))['edges'][0]
    edge[field] = True
    with pytest.raises(ValueError):
        DirectedRevision.from_dict(edge)


def test_higher_labels_updates_disappearance_reappearance_do_not_create_edges(tmp_path):
    a = node(tmp_path)
    b = variant(a, 'later', update_metadata_json=canonical([{'status': 'DELETED', 'updated': '2026-01-01'}]))
    c = variant(a, 'returned', update_metadata_json=canonical([{'status': 'ACTIVE', 'updated': '2026-02-01'}]))
    result = directed_graph((a, b, c), ())
    assert not result['edges'] and not result['historical_completeness_certified']


def test_live_synthetic_control_rejected_and_explicit_fixture_statement_bound(tmp_path):
    a = node(tmp_path)
    control = {'profile': SYNTHETIC_RULE, 'predecessor_native_id': a.native_action_id,
        'predecessor_content_sha256': a.content_sha256, 'relation': 'corrects',
        'applicable_at_utc': '2026-01-01T00:00:00Z'}
    s = statement_from_row(a, {'_c14_revision': control})
    assert s.citation_json and s.successor_node_id == a.node_id
    with pytest.raises(ValueError):
        statement_from_row(replace(a, profile='live'), {'_c14_revision': control})
    assert statement_from_row(a, {'lastModified': '2026-01-01', 'oldContractId': ['x']}) is None


def test_deterministic_reports_replay_primary_and_preserve_original_rules(tmp_path):
    root, cases, c12, out, *_ = setup(tmp_path)
    before = {str(p): inventory(p) for p in (root, c12, out)}
    first, second = tmp_path / 'report-A', tmp_path / 'report-B'
    assert write_report(first, cases) == write_report(second, cases)
    assert verify_report(first, cases) == report(cases)
    assert inventory(first) == inventory(second)
    assert {str(p): inventory(p) for p in (root, c12, out)} == before
    assert main(['--cases', str(tmp_path / 'missing'), '--output', str(tmp_path / 'none')]) == 2


@pytest.mark.parametrize('filename', ['correction.json', 'correction.md', 'correction.html', 'pilot-plan.json'])
def test_tampered_or_truncated_even_resigned_summaries_fail_primary_replay(tmp_path, filename):
    _, cases, *_ = setup(tmp_path)
    out = tmp_path / 'report'
    write_report(out, cases)
    resign(out, 'correction-commit.json', lambda p: (p / filename).write_text('tampered'))
    with pytest.raises(ValueError):
        verify_report(out, cases)


def test_HTML_static_escaped_and_markdown_fence_injection_blocked(tmp_path):
    _, cases, *_ = setup(tmp_path)
    r = report(cases)
    r['untrusted'] = '<script>alert(1)</script>```\n<img src=x onerror=alert(2)>'
    outputs = projections(r)
    html = outputs['correction.html'].decode()
    assert '<script>' not in html and '<img' not in html and '&lt;script&gt;' in html
    assert "default-src &#x27;none&#x27;" not in html  # CSP is fixed markup, never untrusted.
    assert "default-src 'none'" in html
    assert '\\u0060' in outputs['correction.md'].decode()


@pytest.mark.parametrize('flags', [[], ['--live'], ['--capture-parent'], ['--live', '--capture-parent']])
def test_CLI_requires_explicit_live_and_original_anchor_before_access(tmp_path, monkeypatch, flags):
    import src.correction_reporting as module
    monkeypatch.setattr(module, 'collect_parent', lambda *_args, **_kwargs: pytest.fail('unexpected collection'))
    recipe = tmp_path / 'cases.json'
    recipe.write_text('[{}]')
    assert main(['--cases', str(recipe), '--output', str(tmp_path / 'report'), *flags]) == 2


def test_C14_freezes_all_prior_C13_documents():
    protocol = json.loads(Path('docs/correction-parent-protocol-v1.json').read_text())
    for name, expected in protocol['frozen_files'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == expected, name


def test_IDV_unknown_transaction_is_preserved_without_zero_substitution(tmp_path):
    def change(t):
        row = t['responses'][0]['json']['results'][0]
        row['id'] = row['id'][:-1] + '-NONE-'
    _, cases, _, _, value, _ = setup(tmp_path, change)
    assert not value['failures'] and value['records'][0]['row']['id'].endswith('_-NONE-')
    component = value['records'][0]['native_action_components']['transaction']
    assert component['value'] is None and component['original_json'] == '"-NONE-"'
    assert value['record_reassessment']['transaction_number_sentinel_means'] == 'unknown_not_zero'
    assert report(cases)['parent_record_supported_plan_ids']
    assert len(report(cases)['resolved_original_synthetic_requirements']) == 1


def test_old_rejected_capture_is_preserved_and_reassessed_without_resume(tmp_path, monkeypatch):
    import src.parent_history_probe as module
    _, _, c12, original, _, transcript = setup(tmp_path)
    transcript['responses'][0]['json']['results'][0]['id'] = transcript['responses'][0]['json']['results'][0]['id'][:-1] + '-NONE-'
    transcript['responses'][0]['json']['page_metadata'].update(hasNext=True, next=2)
    normal = module.plan_for
    monkeypatch.setattr(module, 'plan_for', lambda base, **kwargs: normal(base, contract_version=kwargs.get('contract_version', 1)))
    legacy = tmp_path / 'v1-capture'
    value = collect(legacy, c12, synthetic=transcript)
    before = inventory(legacy)
    assert value['capture_contract_version'] == 1 and value['failures'] and not value['records']
    assert len(value['record_reassessment']['records']) == 1
    assert not value['record_reassessment']['capture_repaired_or_resumed']
    assert not (legacy / 'parent-002-reservation.json').exists()
    assert value == read(legacy, c12) and inventory(legacy) == before


def test_interrupted_transport_preserves_reservation_and_rejects_implicit_resume(tmp_path, monkeypatch):
    import src.parent_history_probe as module
    _, _, c12, _, _, transcript = setup(tmp_path)
    def interrupted(_scenario):
        def call(_request, _index):
            raise KeyboardInterrupt()
        return call
    monkeypatch.setattr(module, 'FixtureTransport', interrupted)
    out = tmp_path / 'interrupted'
    with pytest.raises(KeyboardInterrupt):
        collect(out, c12, synthetic=transcript)
    assert (out / 'parent-001-reservation.json').exists()
    before = inventory(out)
    with pytest.raises(ValueError):
        read(out, c12)
    with pytest.raises((ValueError, FileExistsError)):
        collect(out, c12, synthetic=transcript)
    assert inventory(out) == before


@pytest.mark.parametrize('version', [0, 3, True, '2'])
def test_unsupported_parent_contract_versions_rejected(tmp_path, version):
    _, _, c12, *_ = setup(tmp_path)
    with pytest.raises(ValueError):
        plan_for(c12, contract_version=version)


@pytest.mark.parametrize('bad', ['NONE', '', 'garbage', '-1'])
def test_missing_transaction_component_only_admits_observed_sentinel(tmp_path, bad):
    def change(t):
        row = t['responses'][0]['json']['results'][0]
        row['id'] = row['id'][:-1] + bad
    _, _, _, _, value, _ = setup(tmp_path, change)
    # Literal non-sentinel strings remain native identifiers when valid;
    # never normalize them into zero or manufacture cross-source identity.
    if bad == '':
        assert value['failures']
    assert not value['financial_comparison_authorized']


def test_full_primary_replay_admits_only_explicit_synthetic_relation(tmp_path):
    from src.history_demo import fixture, collect_fixture
    from src.scope_models import ScopeRequest
    a, transcript = fixture('equal_control')
    body = next(r['json'] for r in transcript['responses'] if r['source'] == 'usaspending')
    before = body['results'][0]
    after = deepcopy(before)
    after['description'] = 'Synthetic corrected observation'
    after['_c14_revision'] = {'profile': SYNTHETIC_RULE, 'predecessor_native_id': before['id'],
        'predecessor_content_sha256': digest(before), 'relation': 'corrects', 'applicable_at_utc': '2026-01-01T00:00:00Z'}
    body['results'].append(after)
    out = tmp_path / 'primary'
    collect_fixture(out, a, transcript)
    scope = ScopeRequest(piid=a.piid, agency=a.agency_id, parent_piid=a.parent_piid, parent_agency=a.parent_agency_id)
    cases = [{'collections': [str(out)], 'scope': scope.to_dict()}]
    result = report(cases)
    graph = result['cases'][0]['directed_revision_graph']
    assert len(graph['edges']) == 1 and graph['explicit_synthetic_relationships'] == 1
    target = tmp_path / 'report'
    write_report(target, cases)
    assert verify_report(target, cases) == result
    assert not result['resolved_original_synthetic_requirements']


@pytest.mark.parametrize('bad', [[], {}, None, [None], [{}] * 25, [{'unexpected': 1}], [{'parent_history': 'x'}]])
def test_unsupported_case_recipes_fail_before_any_network(bad):
    with pytest.raises((ValueError, KeyError, TypeError)):
        report(bad)


def test_parent_page_size_cap_cannot_be_evaded_by_extra_rows(tmp_path):
    def change(t):
        t['responses'][0]['json']['results'] *= 6
    _, _, _, _, value, _ = setup(tmp_path, change)
    assert value['failures'] and not value['records']


@pytest.mark.parametrize('text', ['{', '{"results":[],"results":[]}', 'null', '<html>unavailable</html>'])
def test_malformed_JSON_body_is_preserved_without_record_promotion(tmp_path, text):
    def change(t):
        t['responses'][0].pop('json')
        t['responses'][0]['text'] = text
    _, cases, _, out, value, _ = setup(tmp_path, change)
    assert (out / 'parent-001.body').read_text() == text
    assert value['failures'] and not value['record_reassessment']['records']
    assert not report(cases)['resolved_original_synthetic_requirements']


@pytest.mark.parametrize('metadata', [{'retrieved_at_utc': None}, {'retrieved_at_utc': 'not-a-time'},
    {'source_update_raw': 'unsafe\nmetadata'}, {'body_complete': 'yes'}])
def test_invalid_provenance_preserves_uncommitted_transport_evidence(tmp_path, metadata):
    _, _, c12, _, _, transcript = setup(tmp_path)
    transcript['responses'][0].update(metadata)
    out = tmp_path / 'invalid-provenance'
    with pytest.raises(ValueError):
        collect(out, c12, synthetic=transcript)
    assert (out / 'parent-001.body').exists() and (out / 'parent-001.json').exists()
    assert not (out / 'parent-commit.json').exists()
    with pytest.raises(ValueError):
        read(out, c12)


@pytest.mark.parametrize('target', ['financial', 'resolved', 'historical_applicability'])
def test_fully_resigned_forged_report_still_requires_original_primary_proof(tmp_path, target):
    _, cases, *_ = setup(tmp_path)
    out = tmp_path / 'report'
    write_report(out, cases)
    forged = report(cases)
    if target == 'financial':
        forged['financial_comparison_authorized'] = True
    elif target == 'resolved':
        forged['resolved_original_real_source_requirements'] = ['forged-real-requirement']
    else:
        forged['cases'][0]['historical_parent_assessments'][0]['historical_parent_applicability_established'] = True
    for name, raw in projections(forged).items():
        (out / name).write_bytes(raw)
    resign(out, 'correction-commit.json', lambda _: None)
    commit = json.loads((out / 'correction-commit.json').read_text())
    commit['report_sha256'] = digest(forged)
    (out / 'correction-commit.json').write_text(canonical(commit) + '\n')
    with pytest.raises(ValueError):
        verify_report(out, cases)


def test_resolution_is_exact_original_parent_identity_obligation_only(tmp_path):
    _, cases, *_ = setup(tmp_path)
    value = report(cases)
    impacts = value['cases'][0]['original_requirement_impacts']
    resolved = [p for p in impacts if p['original_requirement_resolved']]
    assert len(resolved) == 1
    p = resolved[0]
    assert p['dimension'] == 'parent_identity' and p['original_requirement']['reasons'] == ['parent_award_primary_record_not_observed']
    assert p['updated_requirement']['status'] == 'QUALIFIED_EVIDENCE'
    assert p['resolution_primary_references'] and p['resolved_claim_scope'] == 'source_local_parent_award_identity_and_primary_record_existence_only'
    assert p['remaining_dependencies'] == ['historical_parent_applicability_unresolved']
    assert all(not p['original_requirement_resolved'] for p in impacts if p['dimension'] != 'parent_identity')
    assert not set(value['synthetic_partial_plan_ids']) & set(value['resolved_original_synthetic_requirements'])


def test_foreign_original_contexts_and_NOT_EVALUATED_plans_never_resolve(tmp_path):
    from tests.test_source_verification import setup as source_setup
    from src.history_demo import fixture, collect_fixture
    from src.scope_models import ScopeRequest
    from src.acquisition_planning import prepare
    from src.source_verification import VerificationExperiment, experiment
    from tests.test_evidence_acquisition import job
    _, _, _, scenario = source_setup(tmp_path / 'template')
    a, transcript = fixture('equal_control')
    body = next(r['json'] for r in transcript['responses'] if r['source'] == 'usaspending')
    foreign = deepcopy(body['results'][0])
    foreign['id'] = foreign['id'].replace('SYNTH-C7-AGREEMENT', 'FOREIGN-PIID')
    body['results'].append(foreign)
    original = tmp_path / 'original'
    collect_fixture(original, a, transcript)
    scope = ScopeRequest(piid=a.piid, agency=a.agency_id, parent_piid=a.parent_piid, parent_agency=a.parent_agency_id)
    cases = [{'collections': [str(original)], 'scope': scope.to_dict()}]
    queue = prepare(cases)
    spec = job(queue, 'usaspending')
    c12 = tmp_path / 'c12'
    experiment(c12, VerificationExperiment(queue=queue, request_id=spec.request_id, mode='synthetic_only'), synthetic=scenario)
    _, _, _, _, _, parent_transcript = setup(tmp_path / 'other')
    out = tmp_path / 'parent'
    collect(out, c12, synthetic=parent_transcript)
    cases[0].update(c12_capture=str(c12), parent_history=str(out))
    impacts = report(cases)['cases'][0]['original_requirement_impacts']
    foreign = [p for p in impacts if p['native_context'].get('piid') == 'FOREIGN-PIID']
    assert foreign and all(not p['original_requirement_resolved'] and not p['C14_parent_record_subproof'] for p in foreign)
    assert any(p['original_requirement_resolved'] for p in impacts)


def test_parent_transcript_bound_rejected_before_creating_capture(tmp_path):
    _, _, c12, _, _, transcript = setup(tmp_path)
    transcript['responses'] *= 3
    out = tmp_path / 'over-budget'
    with pytest.raises(ValueError):
        collect(out, c12, synthetic=transcript)
    assert not out.exists()
