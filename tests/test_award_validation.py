"""Offline C9 controls: synthetic records are never real API observations."""
from copy import deepcopy
from pathlib import Path

import pytest

from src.award_validation import (validate, pagination, write_report, read_report,
    html, main, snapshot, BOUNDARY)
from src.evidence_io import EvidenceError, canonical, digest
from src.history_demo import CASES, fixture, collect_fixture
from src.scope_models import ScopeRequest
from src.sam_validation import demo


def capture(tmp_path, case='equal_control', change=None):
    award, data = fixture(case)
    if change:
        change(data)
    path = tmp_path/'collection'
    collect_fixture(path, award, data)
    request = ScopeRequest(piid=award.piid, agency=award.agency_id,
        parent_piid=award.parent_piid, parent_agency=award.parent_agency_id)
    return path, request


def hashes(path):
    return {n: s.byte_sha256 for n, s in snapshot(path).items()}


@pytest.mark.parametrize('case', CASES)
def test_existing_history_controls_are_diagnosed_without_authorization(tmp_path, case):
    path, scope = capture(tmp_path, case)
    before = hashes(path)
    result = validate((path,), scope)
    assert result == validate((path,), scope)
    assert result['restrictions'] == BOUNDARY
    assert result['financial_arithmetic'] == 'withheld_by_this_diagnostic'
    assert hashes(path) == before
    assert all('complete_history_not_established' in r['gaps'] for r in result['records'])
    assert all('authoritative_revision_alignment_missing' in r['gaps'] for r in result['records'])
    assert all(p['transaction_history_complete'] == 'unknown' for c in result['pagination'] for p in c['sources'])
    if case == 'contradictory_observations':
        assert result['gap_counts']['same_native_action_variant_content_unresolved'] == 2
    if case == 'scope_mismatch':
        assert result['gap_counts']['counterpart_not_observed_not_proven_absent'] >= 1
    if case == 'empty_feed':
        assert result['gap_counts']['counterpart_not_observed_not_proven_absent'] >= 1
        assert any('empty_observation_query_support_and_scope_unverified' in p['issues'] for c in result['pagination'] for p in c['sources'])


@pytest.mark.parametrize('case', ['equal_control','missing_parent','contradictory_observations','empty_feed'])
def test_report_roundtrip_digests_readonly_and_replay(tmp_path, case):
    path, scope = capture(tmp_path, case); result = validate((path,), scope)
    before = hashes(path)
    assert write_report(tmp_path/'a', result, protected=(path,)) == write_report(tmp_path/'b', result, protected=(path,))
    assert hashes(tmp_path/'a') == hashes(tmp_path/'b')
    assert read_report(tmp_path/'a') == result
    assert hashes(path) == before
    with pytest.raises(OSError):
        write_report(tmp_path/'a', result)
    with pytest.raises(EvidenceError):
        write_report(path/'bad', result, protected=(path,))


@pytest.mark.parametrize('name', ['validation.json','validation.md','validation.html','validation-commit.json','pilot-plan.json'])
@pytest.mark.parametrize('mutation', ['remove','change'])
def test_report_tampering_fails_closed(tmp_path, name, mutation):
    path, scope = capture(tmp_path); out = tmp_path/'out'
    write_report(out, validate((path,), scope))
    target = out/name
    if mutation == 'remove':
        target.unlink()
    else:
        target.write_bytes(target.read_bytes()+b' ')
    with pytest.raises((ValueError,OSError)):
        read_report(out)


@pytest.mark.parametrize('bad', [True, False, 0, -1, 10001, '1', None, 1.5])
def test_page_indices_are_not_coerced(bad):
    with pytest.raises(EvidenceError):
        pagination(((bad, False, (digest('a'),)),))


@pytest.mark.parametrize('bad', [None, 0, 1, 'false', [], {}])
def test_continuation_flags_require_boolean(bad):
    with pytest.raises(EvidenceError):
        pagination(((1, bad, (digest('a'),)),))


@pytest.mark.parametrize('pages,expected', [
    ([], 'empty_observation_query_support_and_scope_unverified'),
    ([(1,True,())], 'empty_nonterminal_page'),
    ([(2,False,('b',))], 'missing_observed_page'),
    ([(1,True,('a',)),(3,False,('b',))], 'missing_observed_page'),
    ([(1,False,('a',)),(2,False,('b',))], 'observations_after_terminal_page'),
    ([(1,True,('a',))], 'nonterminal_observed_chain'),
    ([(1,True,('a',)),(2,False,('a',))], 'duplicate_or_overlapping_record_content'),
    ([(1,False,('a','a'))], 'duplicate_or_overlapping_record_content'),
    ([(1,False,('a',)),(1,False,('b',))], 'contradictory_successful_page_observations'),
    ([(1,True,('a',)),(1,False,('a',))], 'contradictory_successful_page_observations'),
])
def test_adversarial_pagination_is_not_complete(pages, expected):
    result = pagination([(i,f,tuple(digest(h) for h in hs)) for i,f,hs in pages])
    assert expected in result['issues']
    assert result['bounded_observed_chain'] == 'unresolved'
    assert result['transaction_history_complete'] == result['source_wide_complete'] == 'unknown'


def test_consistent_pagination_is_only_a_bounded_observation():
    result = pagination(((1,True,(digest('a'),)),(2,False,(digest('b'),))))
    assert result['bounded_observed_chain'] == 'consistent_terminal'
    assert result['query_recall'] == 'unknown'


@pytest.mark.parametrize('what', ['body','metadata','symlink','hardlink'])
def test_primary_evidence_integrity_revalidated(tmp_path, what):
    path, scope = capture(tmp_path)
    target = path/('c3_attempt_000000.body' if what == 'body' else 'c3_attempt_000000.json')
    if what in ('body','metadata'):
        if what == 'metadata':
            import json
            v=json.loads(target.read_bytes());v['body_sha256']='0'*64;target.write_text(canonical(v))
        else:
            target.write_bytes(target.read_bytes()+b' ')
    elif what == 'symlink':
        data = target.read_bytes(); target.unlink(); other = tmp_path/'other';other.write_bytes(data);target.symlink_to(other)
    else:
        import os
        os.link(target, tmp_path/'linked')
    with pytest.raises((ValueError,OSError)):
        validate((path,), scope)


def test_duplicate_inputs_are_not_independent_evidence(tmp_path):
    path, scope = capture(tmp_path)
    with pytest.raises(EvidenceError, match='duplicate_validation_inventory'):
        validate((path,path), scope)


@pytest.mark.parametrize('collections,sam', [((),()),(tuple(range(9)),()),((),tuple(range(4)))])
def test_input_bounds(collections,sam):
    with pytest.raises(EvidenceError):
        validate(collections, sam_captures=sam)


def test_sam_replay_keeps_namespace_and_financial_gaps(tmp_path):
    path=tmp_path/'sam'; demo(path); before=hashes(path)
    result=validate(sam_captures=(path,))
    assert result['records'] and all(r['source']=='samgov' for r in result['records'])
    assert not result['action_groups']
    assert all(r['action_key'] is None and 'sam_cross_source_namespace_mapping_unverified' in r['gaps'] for r in result['records'])
    assert hashes(path)==before


def test_three_sources_are_not_joined_by_matching_spelling(tmp_path):
    path,scope=capture(tmp_path); sam=tmp_path/'sam';demo(sam)
    result=validate((path,),scope,sam_captures=(sam,))
    assert {r['source'] for r in result['records']}=={'usaspending','fpds','samgov'}
    assert all('samgov' not in g['sources_observed'] for g in result['action_groups'])


def test_cli_offline_success_and_safe_failure(tmp_path,capsys):
    path,scope=capture(tmp_path); selection=tmp_path/'scope.json';selection.write_text(canonical(scope.to_dict()))
    assert main(['--collection',str(path),'--scope',str(selection),'--output',str(tmp_path/'out')])==0
    assert read_report(tmp_path/'out')['requested']==scope.to_dict()
    assert main(['--collection','/private/secret','--output',str(tmp_path/'bad')])==2
    assert '/private/secret' not in capsys.readouterr().out
    assert not (tmp_path/'bad').exists()


def test_static_html_and_markdown_escape_source_text():
    text='<script>alert(1)</script>```\x1b[31m\u202e'
    rendered=html({'value':text})
    assert '<script>' not in rendered and '&lt;script&gt;' in rendered
    assert '\x1b' not in rendered and '\u202e' not in rendered
    assert "default-src 'none'" in rendered


def test_known_usaspending_award_identifier_conflict_is_explicit(tmp_path):
    path,scope=capture(tmp_path, change=lambda d: d['responses'][0]['json']['results'][0].update(award_id='CONT_AWD_OTHER_0001_PARENT_0002'))
    result=validate((path,),scope)
    usa=next(r for r in result['records'] if r['source']=='usaspending')
    assert usa['diagnostic_context_status']=='conflicting'
    assert 'source_record_context_nonmatching_award_identifier' in usa['gaps']
    assert result['restrictions']==BOUNDARY


def test_primary_replay_rejects_resigned_false_report(tmp_path):
    from src.award_validation import verify_report
    path,scope=capture(tmp_path); result=validate((path,),scope)
    false=deepcopy(result); false['records'][0]['gaps']=[]
    write_report(tmp_path/'forged',false)
    # A locally recomputed checksum is not a source authenticity guarantee.
    assert read_report(tmp_path/'forged')==false
    with pytest.raises(EvidenceError,match='validation_primary_replay_conflict'):
        verify_report(tmp_path/'forged',(path,),scope)
    write_report(tmp_path/'good',result)
    assert verify_report(tmp_path/'good',(path,),scope)==result


def test_evidence_changed_between_independent_adapters_is_rejected(tmp_path,monkeypatch):
    import src.award_validation as module
    path,scope=capture(tmp_path); original=module.reconstruct
    def changed(*args,**kwargs):
        run=original(*args,**kwargs)
        target=path/'c3_attempt_000000.body';target.write_bytes(target.read_bytes()+b' ')
        return run
    monkeypatch.setattr(module,'reconstruct',changed)
    with pytest.raises(EvidenceError,match='award_validation_source_changed'):
        validate((path,),scope)


def test_identifier_spelling_preserved_in_native_diagnostics(tmp_path):
    path,scope=capture(tmp_path)
    result=validate((path,),scope)
    for row in result['records']:
        assert row['native_context']['agency']['value']=='0001'
        assert row['native_context']['parent_agency']['value']=='0002'
        assert row['native_context']['piid']['value']==scope.piid
    assert all(g['native_components'][1]=='0001' for g in result['action_groups'])


def test_missing_scope_and_output_traversal_fail_without_writes(tmp_path):
    path,scope=capture(tmp_path)
    with pytest.raises(EvidenceError,match='explicit_native_scope_required'):
        validate((path,))
    assert main(['--collection',str(path),'--output',str(path/'nested')])==2
    assert not (path/'nested').exists()


def test_frozen_protocols_remain_byte_identical():
    import hashlib,json
    root=Path(__file__).resolve().parents[1]
    protocol=json.loads((root/'docs/award-validation-protocol-v1.json').read_bytes())
    assert protocol['starting_main']=='8ae1c14f27afa8ebd9c33876dde5d692e8fb4442'
    assert len(protocol['frozen_files'])>=20
    for name, expected in protocol['frozen_files'].items():
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected


def test_out_of_scope_complete_native_context_is_not_mislabeled_missing(tmp_path):
    path,scope=capture(tmp_path,'scope_mismatch')
    result=validate((path,),scope)
    fpds=next(r for r in result['records'] if r['source']=='fpds')
    assert fpds['action_key'] is not None
    assert not fpds['eligible_for_existing_comparison']
    assert 'identity_or_parent_scope_unresolved' in fpds['gaps']
    assert 'native_action_context_incomplete' not in fpds['gaps']


@pytest.mark.parametrize('version',[2,True,None,'1'])
def test_unsupported_report_version_rejected_even_with_valid_manifest(tmp_path,version):
    path,scope=capture(tmp_path);result=validate((path,),scope)
    result['schema_version']=version
    write_report(tmp_path/'out',result)
    with pytest.raises(EvidenceError,match='unsupported_validation_report'):
        read_report(tmp_path/'out')
