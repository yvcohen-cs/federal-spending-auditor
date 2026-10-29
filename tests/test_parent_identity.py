"""Authored offline records: no dataset fixtures and no live HTTP."""
from dataclasses import replace
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from src.collection import CollectionLimits, collect_selected
from src.collection_sources import FixtureTransport
from src.evidence_io import EvidenceError, canonical, digest, strict_json
from src.financial_ingestion import reconcile_collection
from src.parent_evidence import demo, html_report, main, protocol, read_report, write_report
from src.parent_identity import ParentAssessment, ParentStatus
from src.parent_scope import ParentScopeRun, assess_parent_collection, query_explanation, report_for, transition_metrics
from src.readiness_audit import inventory
from src.research_demo import demo_case
from src.scope_ingestion import assess_collection
from src.scope_models import ScopeRequest, ScopeStatus


@pytest.fixture
def collection(tmp_path):
    counter = 0
    def build(*,kind='D',parent=False,version='1.5',requested_parent=False,transform=None,request_changes=None):
        nonlocal counter
        counter += 1
        award,fixture = demo_case('agreement')
        if not requested_parent:
            award = replace(award,parent_piid=None,parent_agency_id=None)
        text = fixture['responses'][-1]['text']
        if not parent:
            begin = text.index('<f:referencedIDVID>');end = text.index('</f:referencedIDVID>')+len('</f:referencedIDVID>')
            text = text[:begin]+text[end:]
            row = fixture['responses'][0]['json']['results'][0]
            row['id'] = row['id'].replace('0001_0002_','0001_-NONE-_').replace('_SYNTH-PARENT_','_-NONE-_')
        text = text.replace('<f:award>','<f:award'+(' version="'+version+'"' if version else '')+'>')
        if kind is not None:
            text = text.replace('</f:award>','<f:contractData><f:contractActionType description="Source label">'+kind+'</f:contractActionType></f:contractData></f:award>')
        fixture['responses'][-1]['text'] = text
        if transform: transform(fixture)
        path = tmp_path/f'collection-{counter}'
        collect_selected(path,(award,),limits=CollectionLimits(max_awards=1,max_requests=2,retries=0,pace_seconds=0.0),
            transport=FixtureTransport(fixture),profile='fixture:'+digest(fixture),sleep=lambda _:None)
        args = dict(piid=award.piid,agency=award.agency_id,parent_piid=award.parent_piid,parent_agency=award.parent_agency_id)
        args.update(request_changes or {})
        req = ScopeRequest(**args)
        return path,req
    return build


def fpds(run):
    return next(a for a in run.assessments if a.baseline.evidence.reference.source=='fpds')


def assess(collection,**args):
    p,q = collection(**args)
    return p,q,assess_parent_collection((p,),q)


def xml_change(old,new):
    return lambda f:f['responses'][-1].update(text=f['responses'][-1]['text'].replace(old,new))


def test_positive_no_parent_is_narrow_and_does_not_authorize_finance(collection):
    p,q,r = assess(collection)
    a = fpds(r)
    assert a.status is ParentStatus.NONE and a.new_scope_status is ScopeStatus.IN_SCOPE
    assert a.baseline.status is ScopeStatus.AMBIGUOUS
    usa = next(a for a in r.assessments if a.baseline.evidence.reference.source=='usaspending')
    assert usa.status is ParentStatus.UNKNOWN and usa.new_scope_status is ScopeStatus.AMBIGUOUS
    assert reconcile_collection(p,scope_request=q).results == ()
    assert ParentScopeRun.from_dict(r.to_dict()) == r


@pytest.mark.parametrize('kind',[None,'','C','A','B','Z','d',' D '])
def test_missing_parent_never_proves_no_parent_without_supported_instrument(collection,kind):
    _,_,run = assess(collection,kind=kind)
    assert fpds(run).status is ParentStatus.UNKNOWN
    assert fpds(run).new_scope_status is ScopeStatus.AMBIGUOUS


@pytest.mark.parametrize('version',[None,'1.2','1.6','2','1.5.3',' 1.5 '])
def test_unsupported_native_schema_cannot_create_positive_identity(collection,version):
    _,_,run = assess(collection,version=version)
    assert fpds(run).status is ParentStatus.UNSUPPORTED
    assert fpds(run).new_scope_status is not ScopeStatus.IN_SCOPE


def test_order_parent_exact_and_unknown_requested_context_separate(collection):
    _,_,run = assess(collection,kind='C',parent=True,requested_parent=True)
    assert fpds(run).status is ParentStatus.VERIFIED and fpds(run).new_scope_status is ScopeStatus.IN_SCOPE
    _,_,run = assess(collection,kind='C',parent=True)
    assert fpds(run).status is ParentStatus.VERIFIED and fpds(run).new_scope_status is ScopeStatus.AMBIGUOUS


@pytest.mark.parametrize('old,new',[('<f:PIID>SYNTH-PARENT</f:PIID>','<f:PIID>OTHER-PARENT</f:PIID>'),
    ('<f:agencyID>0002</f:agencyID>','<f:agencyID>9999</f:agencyID>')])
def test_incompatible_parent_preserved_and_excluded(collection,old,new):
    _,_,run = assess(collection,kind='C',parent=True,requested_parent=True,transform=xml_change(old,new))
    assert fpds(run).status is ParentStatus.CONFLICT
    assert fpds(run).new_scope_status is ScopeStatus.OUT_OF_SCOPE


@pytest.mark.parametrize('old,new',[('<f:agencyID>0001</f:agencyID>','<f:agencyID>9999</f:agencyID>'),
    ('<f:PIID>SYNTH-C7-AGREEMENT</f:PIID>','<f:PIID>OTHER</f:PIID>'),
    ('<f:modNumber>P00001</f:modNumber>','<f:modNumber>P00002</f:modNumber>'),
    ('<f:transactionNumber>0</f:transactionNumber>','<f:transactionNumber>1</f:transactionNumber>')])
def test_native_identity_and_requested_action_conflicts_cannot_be_overridden(collection,old,new):
    _,_,run = assess(collection,transform=xml_change(old,new),request_changes={'modification':'P00001','transaction':'0'})
    assert fpds(run).new_scope_status is ScopeStatus.OUT_OF_SCOPE


def test_parent_agency_missing_is_not_inferred_from_child_agency(collection):
    _,_,run = assess(collection,kind='C',parent=True,transform=xml_change('<f:agencyID>0002</f:agencyID>',''))
    assert fpds(run).status is ParentStatus.UNKNOWN
    assert fpds(run).new_scope_status is ScopeStatus.AMBIGUOUS


@pytest.mark.parametrize('value',['-NONE-','-none-','NONE','N/A','NULL',' ','0'])
def test_placeholder_parent_does_not_establish_no_parent(collection,value):
    text = '<f:referencedIDVID><f:PIID>'+value+'</f:PIID></f:referencedIDVID>'
    _,_,run = assess(collection,transform=xml_change('</f:awardID>',text+'</f:awardID>'))
    assert fpds(run).status is not ParentStatus.NONE
    assert fpds(run).new_scope_status is not ScopeStatus.IN_SCOPE


@pytest.mark.parametrize('parent_xml,presence,status',[
    ('','omitted',ParentStatus.NONE),
    ('<f:referencedIDVID><f:PIID/><f:agencyID/></f:referencedIDVID>','empty',ParentStatus.NONE),
    ('<f:referencedIDVID><f:PIID xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:nil="true"/></f:referencedIDVID>','null',ParentStatus.UNKNOWN),
])
def test_raw_field_presence_preserved_with_positive_type_rule(collection,parent_xml,presence,status):
    _,_,run = assess(collection,transform=xml_change('</f:awardID>',parent_xml+'</f:awardID>'))
    a = fpds(run)
    assert a.status is status
    field = next(f for f in a.fields if f.path.endswith('/PIID'))
    assert field.presence == presence


def test_definitive_type_with_parent_is_conflict_not_absence(collection):
    _,_,run = assess(collection,parent=True)
    assert fpds(run).status is ParentStatus.CONFLICT
    assert fpds(run).new_scope_status is ScopeStatus.AMBIGUOUS


@pytest.mark.parametrize('change',[
    xml_change('<f:award version="1.5">','<f:IDV version="1.5">'),
    xml_change('<f:contractActionType description="Source label">D</f:contractActionType>','<f:contractActionType>D</f:contractActionType><f:contractActionType>C</f:contractActionType>'),
    xml_change('<f:contractActionType description="Source label">','<f:contractActionType xmlns:f="https://evil.invalid/schema">'),
    xml_change('</f:awardID>','<f:referencedIDVID/><f:referencedIDVID/></f:awardID>'),
    xml_change('<f:contractActionType description="Source label">D</f:contractActionType>','<f:contractActionType><f:code>D</f:code></f:contractActionType>'),
])
def test_malformed_idv_and_schema_spoofs_never_verify(collection,change):
    _,_,run = assess(collection,transform=change)
    assert all(a.new_scope_status is not ScopeStatus.IN_SCOPE for a in run.assessments)


def test_identifiers_preserve_leading_zeros_punctuation_no_similarity(collection):
    _,_,r = assess(collection,kind='C',parent=True,requested_parent=True)
    a = fpds(r)
    assert a.baseline.observed.agency.value=='0001'
    assert a.baseline.observed.piid.value=='SYNTH-C7-AGREEMENT'
    assert a.citation.evidence.artifact.representation.value=='response_bytes'
    assert 'derived_entry_xml' in a.baseline.original_identity_json


def test_duplicate_occurrences_not_contradictions_or_independent_evidence(collection):
    def duplicates(f):
        text=f['responses'][-1]['text'];entry=text[text.index('<entry>'):text.index('</entry>')+8]
        f['responses'][-1]['text']=text.replace('</feed>',entry+'</feed>')
    _,_,r=assess(collection,transform=duplicates)
    rows=[a for a in r.assessments if a.baseline.evidence.reference.source=='fpds']
    assert len(rows)==2 and all(a.status is ParentStatus.NONE for a in rows)
    m=transition_metrics((('synthetic/0',r),))
    assert m['denominator']==3 and m['distinct_source_contents']==2
    assert all(q['duplicate_content_occurrences']==2 for q in query_explanation(r) if q['returned_native']['piid']['value'] and q['citation']['evidence']['reference']['source']=='fpds')


def test_parent_corrections_with_same_atom_id_block_both_versions(collection):
    def conflict(f):
        text=f['responses'][-1]['text'].replace('<entry>','<entry><id>urn:synthetic:action</id>');entry=text[text.index('<entry>'):text.index('</entry>')+8]
        entry=entry.replace('SYNTH-PARENT','OTHER-PARENT')
        f['responses'][-1]['text']=text.replace('</feed>',entry+'</feed>')
    _,_,r=assess(collection,kind='C',parent=True,transform=conflict)
    rows=[a for a in r.assessments if a.baseline.evidence.reference.source=='fpds']
    assert len(rows)==2 and all(a.status is ParentStatus.CONFLICT and a.new_scope_status is ScopeStatus.AMBIGUOUS for a in rows)
    wire=r.to_dict();wire['assessments'][0]['contradictory_versions']=[]
    # Remove a real conflict on whichever sorted occurrence carries it.
    index=next(i for i,a in enumerate(r.assessments) if a.contradictory_versions)
    wire=r.to_dict();wire['assessments'][index]['contradictory_versions']=[]
    with pytest.raises(ValueError): ParentScopeRun.from_dict(wire)


@pytest.mark.parametrize('mutate',[
    lambda d:d.update(status='verified_parent_relationship'),
    lambda d:d.update(new_scope_status='ambiguous_scope'),
    lambda d:d.update(rule_version='native-parent-v2'),
    lambda d:d.update(schema_version=2),
    lambda d:d.update(rationale='unsupported arbitrary positive rule'),
    lambda d:d['fields'][0].update(raw_json='"1.6"'),
    lambda d:d['citation'].update(kind='human_assertion'),
    lambda d:d['baseline'].update(original_identity_json=canonical({'derived_entry_xml':'<entry/>'})),
])
def test_serialized_results_cannot_forge_positive_support(collection,mutate):
    _,_,r=assess(collection)
    data=fpds(r).to_dict();mutate(data)
    with pytest.raises((ValueError,TypeError)): ParentAssessment.from_dict(data)


@pytest.mark.parametrize('damage',['body','metadata','checkpoint','symlink'])
def test_missing_provenance_tampering_and_unsafe_roots(collection,tmp_path,damage):
    p,q=collection()
    if damage=='body': (p/'c3_attempt_000001.body').write_bytes(b'changed')
    elif damage=='metadata': (p/'c3_attempt_000001.json').unlink()
    elif damage=='checkpoint': (p/'c3_checkpoint.json').unlink()
    else:
        link=tmp_path/'link';link.symlink_to(p,target_is_directory=True);p=link
    with pytest.raises((ValueError,OSError)): assess_parent_collection((p,),q)


def test_invalid_root_count_and_overlap_rejected(collection):
    p,q=collection()
    with pytest.raises(ValueError): assess_parent_collection((),q)
    with pytest.raises(ValueError): assess_parent_collection((p,p),q)


def test_unavailable_api_malformed_body_and_empty_feed_no_identity_claim(collection):
    for mutation in (lambda f:f['responses'][-1].update(status=503),
                     lambda f:f['responses'][-1].update(text='<broken>'),
                     lambda f:f['responses'][-1].update(text='<feed xmlns="http://www.w3.org/2005/Atom"/>')):
        _,_,r=assess(collection,transform=mutation)
        assert not any(a.new_scope_status is ScopeStatus.IN_SCOPE for a in r.assessments)
        assert all(a.baseline.evidence.reference.source!='fpds' for a in r.assessments)


def test_source_immutability_replay_legacy_and_financial_compatibility(collection):
    p,q=collection(kind='C',parent=True,requested_parent=True)
    before=inventory(p);old=assess_collection(p,q);fin=reconcile_collection(p,scope_request=q)
    a=assess_parent_collection((p,),q);b=assess_parent_collection((p,),q)
    assert a.substantive_sha256==b.substantive_sha256
    assert inventory(p)==before and assess_collection(p,q)==old
    assert reconcile_collection(p,scope_request=q)==fin
    assert transition_metrics((('synthetic/0',a),))['newly_eligible_financial_comparisons']==0


def test_demo_two_replays_safe_outputs_and_reader(tmp_path):
    a=demo(tmp_path/'a');b=demo(tmp_path/'b')
    assert digest(a)==digest(b)
    assert a['metrics']['changed_occurrences']==1
    assert a['http_requests']==0
    assert 'scope_rule_version' in canonical(a)
    sha=write_report(tmp_path/'report',a,protected=(tmp_path/'a',))
    assert digest(read_report(tmp_path/'report'))==sha
    with pytest.raises((ValueError,OSError)): write_report(tmp_path/'report',a)
    output=tmp_path/'report'/'parent-identity.html';output.write_text('changed')
    with pytest.raises(ValueError): read_report(tmp_path/'report')
    hostile={**a,'limitations':['<script>alert(1)</script> & "']}
    assert '<script>' not in html_report(hostile) and '&lt;script&gt;' in html_report(hostile)


def test_protocol_frozen_lineage_and_no_live_cli(tmp_path):
    p=protocol()
    assert p['baseline_occurrences']['ambiguous_scope']==182
    assert p['downstream'].startswith('experimental_scope_only')
    with pytest.raises(SystemExit): main(['--live','--run-dir',str(tmp_path/'x')])
    assert main(['--root',str(tmp_path/'missing'),'--run-dir',str(tmp_path/'x')])==2
    assert not (tmp_path/'x').exists()


def test_reused_child_action_under_distinct_parents_is_not_inferred_identity(collection):
    def related(f):
        text=f['responses'][-1]['text'];entry=text[text.index('<entry>'):text.index('</entry>')+8]
        f['responses'][-1]['text']=text.replace('</feed>',entry.replace('SYNTH-PARENT','OTHER-PARENT')+'</feed>')
    _,_,r=assess(collection,kind='C',parent=True,requested_parent=True,transform=related)
    rows=[a for a in r.assessments if a.baseline.evidence.reference.source=='fpds']
    assert all(not a.contradictory_versions for a in rows)
    assert {a.new_scope_status for a in rows}=={ScopeStatus.IN_SCOPE,ScopeStatus.OUT_OF_SCOPE}


@pytest.mark.parametrize('extra',[
    '<f:contractData/>',
    '<f:other><f:referencedIDVID><f:PIID>OTHER</f:PIID></f:referencedIDVID></f:other>',
])
def test_duplicate_or_hidden_parent_context_cannot_authorize_absence(collection,extra):
    _,_,r=assess(collection,transform=xml_change('</f:award>',extra+'</f:award>'))
    assert fpds(r).status is ParentStatus.UNSUPPORTED
    assert fpds(r).new_scope_status is not ScopeStatus.IN_SCOPE


def test_partial_referenced_modification_is_not_no_parent(collection):
    text='<f:referencedIDVID><f:modNumber>0</f:modNumber></f:referencedIDVID>'
    _,_,r=assess(collection,transform=xml_change('</f:awardID>',text+'</f:awardID>'))
    assert fpds(r).status is ParentStatus.UNKNOWN


@pytest.mark.parametrize('version',['1.4','1.5'])
def test_documented_schema_versions_support_only_correct_instrument_path(collection,version):
    _,_,r=assess(collection,version=version)
    assert fpds(r).status is ParentStatus.NONE
    change=xml_change('f:contractData','f:contractDetail')
    _,_,r=assess(collection,version=version,transform=change)
    assert fpds(r).status is ParentStatus.UNKNOWN


def test_unavailable_slots_keep_unknown_denominators(collection):
    _,_,run=assess(collection)
    r=report_for((('synthetic/0',run),),protocol=protocol(),unavailable=({'slot':'synthetic/1','reason':'unavailable'},))
    assert r['metrics']['selected_slot_denominator']==2
    assert r['metrics']['inspected_slots']==1
    assert not r['metrics']['occurrence_count_complete']
    r=report_for((),protocol=protocol(),unavailable=({'slot':'synthetic/0','reason':'unavailable'},))
    assert not r['metrics']['occurrence_count_complete']


def test_query_explanation_preserves_actual_provenance_and_not_server_fault(collection):
    _,_,r=assess(collection)
    for q in query_explanation(r):
        assert len(q['submitted_request_contexts'])==1
        c=q['citation']['evidence'];actual=q['submitted_request_contexts'][0]
        assert actual['body_sha256']==c['artifact']['sha256']
        assert actual['retrieved_at_utc']==c['artifact']['retrieved_at_utc']
        assert 'not_server_defect' in q['explanation']
    fp=next(q for q in query_explanation(r) if q['citation']['evidence']['reference']['source']=='fpds')
    assert 'CONTRACTING_AGENCY_ID' in fp['submitted_request_contexts'][0]['request']['parameters']['q']
    assert 'not asserted equivalent' in fp['query_limitations'][0]


def test_all_report_projections_revalidated_before_write(collection,tmp_path):
    _,_,run=assess(collection)
    r=report_for((('synthetic/0',run),),protocol=protocol())
    r['metrics']['new']['verified_in_scope']=100
    with pytest.raises(ValueError): write_report(tmp_path/'forged',r)
    assert not (tmp_path/'forged').exists()


def test_derived_xml_whitespace_tail_bound_to_original_content(collection):
    p,q,r=assess(collection,transform=xml_change('</entry>','</entry>\n    '))
    assert fpds(r).status is ParentStatus.NONE
    data=fpds(r).to_dict()
    old=strict_json(data['baseline']['original_identity_json'].encode())
    old['derived_entry_xml']=old['derived_entry_xml'].replace('>D<','>C<')
    data['baseline']['original_identity_json']=canonical(old)
    with pytest.raises(ValueError): ParentAssessment.from_dict(data)
