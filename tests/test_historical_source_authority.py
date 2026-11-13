"""Authored offline observations, never real historical-authority certificates."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import pytest
from src.evidence_io import canonical,digest
from src.history_demo import fixture,collect_fixture
from src.identity_matching import decode_usa_id
from src.scope_models import ScopeRequest
from src.parent_modification_authority import assess as prior_assess
from src.historical_source_authority import assess,documentation,VisibleText,REFERENCES


def original_case(root,suffix='ONE'):
    award,data=fixture('equal_control');old_child,old_parent=award.piid,award.parent_piid
    award=replace(award,piid='SYNTH-C19-'+suffix,parent_piid='SYNTH-PARENT-C19-'+suffix,generated_id='SYNTH-NATIVE-C19-'+suffix)
    for r in data['responses']:
        if r['source']=='usaspending':
            for row in r['json']['results']:row['id']=row['id'].replace(old_child,award.piid).replace(old_parent,award.parent_piid)
        else:r['text']=r['text'].replace(old_child,award.piid).replace(old_parent,award.parent_piid)
    collect_fixture(root,award,data)
    scope=ScopeRequest(piid=award.piid,agency=award.agency_id,parent_piid=award.parent_piid,parent_agency=award.parent_agency_id)
    return {'collections':[str(root)],'scope':scope.to_dict()},award,data


def historical_case(root):
    case,a,_=original_case(root)
    native_id=f'CONT_TX_{a.parent_agency_id}_-NONE-_{a.parent_piid}_0_-NONE-_-NONE-'
    native,issues=decode_usa_id(native_id);assert not issues
    parent={'source_native_record_id':native_id,'native_action_components':{k:v.to_dict() for k,v in native.items()},
        'modification_number':'0','action_date':'2020-01-01','evidence':{'source':'usaspending','archive_sha256':'1'*64,
        'body_sha256':'2'*64,'metadata_sha256':'3'*64,'locator':'/results/0',
        'retrieved_at_utc':'2026-01-01T00:00:00Z','representation':'synthetic_transcript_bytes'}}
    return case,prior_assess(case,[parent],modification='P00001',transaction='0')


def documents(root):
    root.mkdir()
    for name,(_,url,_) in REFERENCES.items():
        body=b'<p>Authored synthetic reference</p><script>alert(1)</script>'
        (root/(name+'.body')).write_bytes(body)
        meta={'request':{'method':'GET','url':url,'redirects':False},'status':200,'retrieved_at_utc':'2026-01-01T00:00:00Z',
              'body_complete':True,'body_sha256':hashlib.sha256(body).hexdigest(),
              'representation':'HTTP_entity_bytes_after_content_decoding','location':None}
        (root/(name+'.json')).write_text(canonical(meta))
    return root


@pytest.fixture(scope='module')
def historical(tmp_path_factory):return historical_case(tmp_path_factory.mktemp('c19-historical')/'original')[1]


def test_five_separate_obligations_preserve_primary_citations(historical):
    r=assess(historical,profile='synthetic')
    assert [p['state'] for p in r['evidence_levels']]==['OBSERVED']*3+['UNSUPPORTED','INSUFFICIENT']
    assert r['primary_child_citations'] and r['primary_parent_citations']
    assert not r['verified_historical_relationships'] and not r['financial_comparison_authorized']


@pytest.mark.parametrize('field',['piid','agency','parent_piid','parent_agency','modification','transaction'])
def test_conflicting_selected_components_reject(historical,field):
    h=deepcopy(historical);h['selected_native_action'][field]='WRONG'
    with pytest.raises(ValueError):assess(h,profile='synthetic')


@pytest.mark.parametrize('bad',[None,0,False,'','../parent','A/B'])
def test_invalid_native_identifiers_never_normalized(historical,bad):
    h=deepcopy(historical);h['selected_native_action']['piid']=bad
    with pytest.raises(ValueError):assess(h,profile='synthetic')


@pytest.mark.parametrize('field',['archive_sha256','body_sha256','metadata_sha256'])
def test_missing_or_wrong_parent_hash_reject(historical,field):
    h=deepcopy(historical);h['parent_modification_candidates'][0]['evidence'][field]='bad'
    with pytest.raises(ValueError):assess(h,profile='synthetic')


def test_missing_parent_primary_remains_insufficient(historical):
    h=deepcopy(historical);h['parent_modification_candidates']=[];r=assess(h,profile='synthetic')
    assert r['evidence_levels'][2]['state']=='INSUFFICIENT' and 'referenced_parent_primary_action' in r['missing_proof_obligations']


def test_conflicting_parent_references_preserved(historical):
    h=deepcopy(historical);c=deepcopy(next(c for c in h['original_child_evidence'] if c['source']=='fpds'))
    c['referenced_parent_modification']='P00002';h['original_child_evidence'].append(c);r=assess(h,profile='synthetic')
    assert r['literal_parent_modification_references']==['0','P00002'] and r['conflicting_observations_preserved']
    assert not r['verified_historical_relationships']


def test_reused_parent_label_and_duplicates_not_revision(historical):
    h=deepcopy(historical);p=deepcopy(h['parent_modification_candidates'][0])
    p['source_native_record_id']=p['source_native_record_id'][:-len('_-NONE-')]+ '_1'
    native,issues=decode_usa_id(p['source_native_record_id']);assert not issues
    p['native_action_components']={k:v.to_dict() for k,v in native.items()};h['parent_modification_candidates'] += [p,deepcopy(p)]
    r=assess(h,profile='synthetic');assert r['reused_parent_modification_label']
    assert r['parent_observation_occurrences']==3 and len(r['parent_native_record_ids'])==2
    assert not r['repeated_observations_are_independent_corroboration']


@pytest.mark.parametrize('claim',[{'oldContractId':['OLD']},{'lastModifiedDate':'2099-01-01'},
                                 {'effective_date':'2020-01-01'},{'rule':'higher_modification_wins'}])
def test_unsupported_predecessor_and_effective_claims_reject(historical,claim):
    with pytest.raises(ValueError):assess(historical,profile='synthetic',authority_claims=[claim])


@pytest.mark.parametrize('field,value',[('financial_comparison_authorized',True),
    ('historical_parent_applicability_intervals',[{'start':'2020-01-01'}]),
    ('authoritative_correction_relationships',[{'from':'OLD','to':'NEW'}]),('schema_version',True)])
def test_forged_authority_states_reject(historical,field,value):
    h=deepcopy(historical);h[field]=value
    with pytest.raises(ValueError):assess(h,profile='synthetic')


def test_serialized_positive_levels_do_not_supply_primary_proof(historical):
    h=deepcopy(historical);h['evidence_levels']={k:True for k in h['evidence_levels']}
    r=assess(h,profile='synthetic');assert r['evidence_levels'][-1]['state']=='INSUFFICIENT' and not r['verified_historical_relationships']


@pytest.mark.parametrize('profile',['live','production',None])
def test_synthetic_cannot_be_relabelled_live(historical,profile):
    with pytest.raises(ValueError):assess(historical,profile=profile)


@pytest.mark.parametrize('field,bad',[('retrieved_at_utc',None),('representation','byte_exact_HTTP_response')])
def test_missing_parent_provenance_and_false_representation_reject(historical,field,bad):
    h=deepcopy(historical);h['parent_modification_candidates'][0]['evidence'][field]=bad
    with pytest.raises(ValueError):assess(h,profile='synthetic')


def test_assessment_is_deterministic_without_mutating_input(historical):
    before=canonical(historical)
    assert digest(assess(historical,profile='synthetic'))==digest(assess(deepcopy(historical),profile='synthetic'))
    assert canonical(historical)==before


@pytest.mark.parametrize('field,bad',[('status',True),('status',403),('body_complete',False),
    ('retrieved_at_utc',None),('location','https://other.invalid/'),('body_sha256','0'*64),('representation','parsed_json')])
def test_document_metadata_cannot_fabricate_authority(tmp_path,field,bad):
    root=documents(tmp_path/'docs');p=root/'sam-guide.json';m=json.loads(p.read_text());m[field]=bad;p.write_text(canonical(m))
    with pytest.raises(ValueError):documentation(root)


def test_unknown_document_version_never_admits_rule(tmp_path):
    r=documentation(documents(tmp_path/'docs'))
    assert all(o['interpretation']=='UNREVIEWED_DOCUMENT_VERSION' and not o['historical_rule_admitted'] for o in r)


def test_visible_text_ignores_scripts_without_claiming_byte_identity():
    a,b=VisibleText(),VisibleText();a.feed('<p>Correction workflow</p><script>token-A</script>')
    b.feed('<p>Correction workflow</p><script>token-B</script><style>secret</style>')
    assert a.values==b.values==['Correction workflow']
