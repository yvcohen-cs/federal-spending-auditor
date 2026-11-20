"""Synthetic document/version pins; never actual historical certificates."""
from copy import deepcopy
from pathlib import Path
import hashlib,json
import pytest
import src.source_reference_semantics as module
from src.source_reference_semantics import read_documents,reference_assessment,visible_projection
from src.historical_source_authority import assess
from src.evidence_io import canonical
from src.identity_matching import decode_usa_id
from tests.test_historical_source_authority import historical_case


def documents(root,monkeypatch,*,reviewed=True,script_only=False):
    root.mkdir()
    for name,(source,url,known,quote) in list(module.DOCUMENTS.items()):
        encoding='cp1252' if name.startswith('fpds-') else 'utf-8'
        declaration='windows-1252' if encoding=='cp1252' else 'utf-8'
        prose='Authored synthetic source’s reference: '+quote
        body=(f'<meta charset="{declaration}"><p>Authored synthetic fixture</p>'
              +(f'<script>{prose}</script>' if script_only else f'<p>{prose}</p><script>synthetic_do_not_execute()</script>')).encode(encoding)
        (root/(name+'.body')).write_bytes(body)
        digest=hashlib.sha256(body).hexdigest()
        meta={'schema_version':1,'request':{'method':'GET','url':url,'redirects':False},'status':200,
            'retrieved_at_utc':'2026-01-01T00:00:00Z','body_complete':True,'body_sha256':digest,
            'representation':'HTTP_entity_bytes_after_content_decoding','location':None,'content_type':'text/html'}
        (root/(name+'.json')).write_text(canonical(meta))
        if reviewed:monkeypatch.setitem(module.DOCUMENTS,name,(source,url,digest,quote))
    return root


@pytest.fixture(scope='module')
def historical(tmp_path_factory):return historical_case(tmp_path_factory.mktemp('c20-reference')/'original')[1]


def test_reviewed_native_reference_is_not_historical_authority(tmp_path,monkeypatch,historical):
    docs=read_documents(documents(tmp_path/'docs',monkeypatch))
    old=assess(deepcopy(historical),profile='synthetic');r=reference_assessment(old,docs,profile='synthetic')
    assert r['source_native_reference_interpretation']=='DOCUMENTED_INSTRUCTION_AND_SELECTED_REFERENCE_OBSERVED'
    assert r['supporting_primary_references'] and r['supporting_document_citation']['metadata']['body_sha256']
    assert not r['historical_applicability_rule_established'] and not r['historical_applicability_independently_verified']
    assert not r['verified_historical_relationships'] and not r['authoritative_correction_edges'] and not r['financial_comparison_authorized']


def test_declared_legacy_encoding_preserves_entity_and_projection(tmp_path,monkeypatch):
    root=documents(tmp_path/'docs',monkeypatch);raw=(root/'fpds-glossary.body').read_bytes()
    before=hashlib.sha256(raw).hexdigest();r=read_documents(root)
    assert b'\x92' in raw and r[0]['projection_encoding']=='cp1252'
    assert hashlib.sha256((root/'fpds-glossary.body').read_bytes()).hexdigest()==before
    assert r[0]['publisher_document_version'] is None and r[0]['historical_document_applicability']=='unknown'


@pytest.mark.parametrize('raw,header',[(b'<meta charset="windows-1252">','text/html; charset=utf-8'),
    (b'<meta charset="unknown-charset">','text/html'),(b'\x92','text/html'),(b'ASCII',None)])
def test_unsupported_or_conflicting_encoding_is_not_guessed(raw,header):
    with pytest.raises(ValueError):visible_projection(raw,header)


def test_script_text_cannot_supply_reviewed_semantic_clause(tmp_path,monkeypatch,historical):
    docs=read_documents(documents(tmp_path/'docs',monkeypatch,script_only=True))
    assert all(d['state']=='REVIEWED_CLAUSE_MISSING' for d in docs)
    r=reference_assessment(assess(deepcopy(historical),profile='synthetic'),docs,profile='synthetic')
    assert r['source_native_reference_interpretation']=='INSUFFICIENT_DOCUMENT_OR_PRIMARY_REFERENCE'


def test_unreviewed_document_version_never_admits_rule(tmp_path,monkeypatch,historical):
    docs=read_documents(documents(tmp_path/'docs',monkeypatch,reviewed=False))
    assert all(d['state']=='UNREVIEWED_DOCUMENT_VERSION' for d in docs)
    r=reference_assessment(assess(deepcopy(historical),profile='synthetic'),docs,profile='synthetic')
    assert not r['supporting_document_citation'] and not r['historical_applicability_rule_established']


@pytest.mark.parametrize('field,bad',[('schema_version',True),('status',True),('body_complete',1),
    ('body_sha256','0'*64),('retrieved_at_utc',None),('representation','byte_exact_wire_HTTP')])
def test_forged_document_metadata_rejects(tmp_path,monkeypatch,field,bad):
    root=documents(tmp_path/'docs',monkeypatch);p=root/'fpds-glossary.json'
    v=json.loads(p.read_text());v[field]=bad;p.write_text(canonical(v))
    with pytest.raises(ValueError):read_documents(root)


def test_unapproved_document_endpoint_is_rejected_without_request(tmp_path,monkeypatch):
    root=documents(tmp_path/'docs',monkeypatch);p=root/'fpds-glossary.json'
    v=json.loads(p.read_text());v['request']['url']='https://unapproved.invalid/reference';p.write_text(canonical(v))
    with pytest.raises(ValueError):read_documents(root)


@pytest.mark.parametrize('status',[401,403,429,500,503])
def test_unavailable_public_document_remains_inconclusive(tmp_path,monkeypatch,status):
    root=documents(tmp_path/'docs',monkeypatch);p=root/'fpds-glossary.json'
    v=json.loads(p.read_text());v['status']=status;p.write_text(canonical(v))
    r=read_documents(root)[0];assert r['state']=='UNAVAILABLE_OR_INCOMPLETE' and r['clause'] is None
    assert not r['historical_effective_rule_established']


def test_redirect_and_truncation_cannot_be_treated_as_document_content(tmp_path,monkeypatch):
    root=documents(tmp_path/'docs',monkeypatch);p=root/'fpds-glossary.json'
    v=json.loads(p.read_text());v.update(status=301,location='https://sam.gov/contracting');p.write_text(canonical(v))
    assert read_documents(root)[0]['state']=='UNAVAILABLE_OR_INCOMPLETE'
    v.update(status=200,location=None,body_complete=False);p.write_text(canonical(v))
    assert read_documents(root)[0]['state']=='UNAVAILABLE_OR_INCOMPLETE'


@pytest.mark.parametrize('field,value',[('financial_comparison_authorized',True),('namespace_mapping_verified',True),
    ('selected_revision_verified',True),('verified_historical_relationships',[{'from':'OLD','to':'NEW'}]),
    ('authoritative_correction_edges',[{'direction':'later_wins'}]),('schema_version',True)])
def test_caller_authority_claims_do_not_override_primary_replay(tmp_path,monkeypatch,historical,field,value):
    docs=read_documents(documents(tmp_path/'docs',monkeypatch));old=assess(deepcopy(historical),profile='synthetic');old[field]=value
    with pytest.raises(ValueError):reference_assessment(old,docs,profile='synthetic')


@pytest.mark.parametrize('component',['piid','agency','parent_piid','parent_agency','modification','transaction'])
def test_conflicting_selected_historical_identity_rejects(tmp_path,monkeypatch,historical,component):
    docs=read_documents(documents(tmp_path/'docs',monkeypatch));old=assess(deepcopy(historical),profile='synthetic')
    old['selected_native_action'][component]='WRONG'
    with pytest.raises(ValueError):reference_assessment(old,docs,profile='synthetic')


def test_wrong_parent_modification_reference_cannot_be_certified(tmp_path,monkeypatch,historical):
    docs=read_documents(documents(tmp_path/'docs',monkeypatch));old=assess(deepcopy(historical),profile='synthetic')
    next(c for c in old['primary_child_citations'] if c['source']=='fpds')['referenced_parent_modification']='WRONG'
    with pytest.raises(ValueError):reference_assessment(old,docs,profile='synthetic')


def test_reused_modification_labels_remain_unresolved(tmp_path,monkeypatch,historical):
    h=deepcopy(historical);p=deepcopy(h['parent_modification_candidates'][0])
    p['source_native_record_id']=p['source_native_record_id'][:-len('_-NONE-')]+'_1'
    native,issues=decode_usa_id(p['source_native_record_id']);assert not issues
    p['native_action_components']={k:v.to_dict() for k,v in native.items()};h['parent_modification_candidates'].append(p)
    docs=read_documents(documents(tmp_path/'docs',monkeypatch));r=reference_assessment(assess(h,profile='synthetic'),docs,profile='synthetic')
    assert r['preserved_five_level_assessment']['reused_parent_modification_label']
    assert not r['historical_applicability_independently_verified'] and not r['authoritative_correction_edges']


def test_forged_review_state_or_profile_does_not_promote_unknown_source(tmp_path,monkeypatch,historical):
    docs=read_documents(documents(tmp_path/'docs',monkeypatch,reviewed=False));docs[0]['state']='REVIEWED_CLAUSE_OBSERVED'
    old=assess(deepcopy(historical),profile='synthetic');assert reference_assessment(old,docs,profile='synthetic')['supporting_document_citation'] is None
    with pytest.raises(ValueError):reference_assessment(old,docs,profile='live')


def test_missing_historical_primary_and_unsupported_predecessor_preserved(tmp_path,monkeypatch,historical):
    h=deepcopy(historical);h['parent_modification_candidates']=[]
    old=assess(h,profile='synthetic');docs=read_documents(documents(tmp_path/'docs',monkeypatch))
    r=reference_assessment(old,docs,profile='synthetic')
    assert r['preserved_five_level_assessment']['evidence_levels'][2]['state']=='INSUFFICIENT'
    assert not r['verified_historical_relationships']


def test_determinism_and_no_source_mutation(tmp_path,monkeypatch,historical):
    root=documents(tmp_path/'docs',monkeypatch);before={p.name:p.read_bytes() for p in root.iterdir()}
    old=assess(deepcopy(historical),profile='synthetic');doc=read_documents(root)
    assert canonical(reference_assessment(old,doc,profile='synthetic'))==canonical(reference_assessment(deepcopy(old),deepcopy(doc),profile='synthetic'))
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before
