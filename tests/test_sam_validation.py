"""Offline authored SAM research fixtures. No real credentials or HTTP."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import http.client
import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import pytest
import requests

from src.evidence_io import EvidenceError,canonical,digest,strict_json
from src.parent_identity import RULE as PARENT_RULE
from src.readiness_audit import inventory
from src.sam_validation import demo,main,synthetic_row,synthetic_selection
from src.sam_validation_capture import (SAMResearchSelection,SAMResearchTransport,artifact_for,body_safe,
    collect,plan_for,protocol,public_request,replay,secret_free)
from src.sam_validation_models import SAMObservedRecord,SAMPage,Presence,fields_for,parse_page
from src.sam_validation_reporting import report,write_report,read_report,html_report
from src.scope_models import ScopeStatus

KEY='SYNTHETIC_C2_CREDENTIAL_NOT_REAL'


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.delenv('SAM_GOV_API_KEY',raising=False)


def response(rows=None,total=1,offset=0,limit=2,**extra):
    return {'awardSummary':[synthetic_row()] if rows is None else rows,'totalRecords':total,'offset':offset,'limit':limit,**extra}


def fields(status=200,**changes):
    v={'status':status,'retrieved_at_utc':'2025-01-01T00:00:00Z' if status is not None else None,
        'body_complete':True,'error_code':None,'headers':{}}
    v.update(changes);return v


def transport(responses):
    calls=[]
    def send(request,sequence):
        calls.append(deepcopy(request))
        item=responses[sequence]
        if isinstance(item,BaseException):raise item
        meta,body=item
        return meta,canonical(body).encode() if isinstance(body,dict) else body
    send.calls=calls
    return send


def capture(tmp_path,responses,selection=None,name='capture'):
    selection=selection or synthetic_selection()
    send=transport(responses);path=tmp_path/name
    result=collect(path,selection,live=True,fixture_transport=send,sleep=lambda _:None)
    return path,send,result


def parse(body,*,selection=None,offset=0,headers=None):
    s=selection or synthetic_selection()
    raw=canonical(body).encode();req=public_request(s.subjects[0],s.limit,offset);meta=fields()
    artifact=artifact_for('sam-attempt-000.body',raw,req,meta,'synthetic')
    return parse_page(raw,s.subjects[0],artifact,'sam-attempt-000.json',offset=offset,limit=s.limit,pagination_rule=s.pagination_rule)


def test_no_opt_in_and_no_credential_no_directory_or_network(tmp_path):
    selection=replace(synthetic_selection(),profile='live',pagination_rule='unvalidated')
    with pytest.raises(ValueError,match='opt_in'):collect(tmp_path/'no',selection)
    with pytest.raises(ValueError,match='credentials_unavailable'):collect(tmp_path/'no',selection,live=True)
    assert not (tmp_path/'no').exists()
    with pytest.raises(ValueError):collect(tmp_path/'no',synthetic_selection(),live=True)


@pytest.mark.parametrize('bad',[
    {'limit':0},{'limit':11},{'limit':True},{'profile':'production'},
    {'profile':'live','pagination_rule':'synthetic_row_offset'}, {'pagination_rule':'row_offset'},
    {'subjects':()}, {'subjects':synthetic_selection().subjects*4},
])
def test_limits_profiles_and_subject_freeze_are_strict(bad):
    with pytest.raises((ValueError,TypeError)):replace(synthetic_selection(),**bad)


@pytest.mark.parametrize('token',['A&b','A|B','A~B','A!B','A%26B','A\\B','A"B',' A','A?api_key=x','A#B'])
def test_no_query_operators_or_silent_native_string_modification(token):
    subject=replace(synthetic_selection().subjects[0],piid=token)
    with pytest.raises(ValueError):replace(synthetic_selection(),subjects=(subject,))


@pytest.mark.parametrize('rule',['synthetic_row_offset','synthetic_page_index'])
def test_two_pages_correct_synthetic_progression_and_independent_history_gates(tmp_path,rule):
    s=synthetic_selection(rule)
    offset=2 if rule=='synthetic_row_offset' else 1
    p,send,result=capture(tmp_path,[(fields(),response([synthetic_row('0'),synthetic_row('P00001')],total=3)),
        (fields(),response([synthetic_row('P00002')],total=3,offset=offset))],s)
    before=inventory(p);selection,pages,actual,_,issues=replay(p)
    assert len(send.calls)==2 and actual==result and not issues
    assert [call['parameters']['offset'] for call in send.calls]==[0,offset]
    assert pages[-1][2].bounded_query_terminal is True
    assert all(page.history_complete==page.source_wide_complete==page.freshness=='unknown' for _,_,page in pages)
    assert inventory(p)==before
    assert report(p)['authenticated_live_metrics'] is None


def test_unknown_live_contract_stops_even_apparent_terminal_or_empty(tmp_path):
    s=replace(synthetic_selection(),pagination_rule='unvalidated')
    for i,body in enumerate((response(),response([],total=0))):
        p,send,result=capture(tmp_path,[(fields(),body)],s,name=str(i))
        assert len(send.calls)==1 and result['stop_reason']=='offset_contract_unvalidated_stop'
        assert replay(p)[1][0][2].bounded_query_terminal is None
        assert replay(p)[-1]==('offset_contract_unvalidated_stop',)


@pytest.mark.parametrize('bad',[
    {'offset':-1},{'offset':1},{'offset':True},{'offset':'bogus'},{'limit':0},{'limit':100},
    {'totalRecords':-1},{'totalRecords':True},{'awardSummary':{}},{'totalRecords':0},
    {'next':'https://evil.invalid/'},{'apiVersion':'v2'},
])
def test_malformed_counter_envelope_and_unsafe_continuation_rejected(bad):
    body=response();body.update(bad)
    with pytest.raises(ValueError):parse(body)


@pytest.mark.parametrize('mutate,expected',[
    (lambda r:r['contractId'].update(piid='OTHER'),ScopeStatus.OUT_OF_SCOPE),
    (lambda r:r['contractId']['subtier'].update(code='9999'),ScopeStatus.OUT_OF_SCOPE),
    (lambda r:r['contractId'].update(referencedIDVPiid='OTHER'),ScopeStatus.OUT_OF_SCOPE),
    (lambda r:r['contractId']['referencedIDVSubtier'].update(code='9999'),ScopeStatus.OUT_OF_SCOPE),
    (lambda r:r['coreData'].update(awardOrIDV='IDV'),ScopeStatus.OUT_OF_SCOPE),
    (lambda r:r['coreData'].update(coreVersionId='99'),ScopeStatus.UNSUPPORTED),
    (lambda r:r['contractId'].update(piid=1),ScopeStatus.UNSUPPORTED),
])
def test_native_identity_no_crosswalk_or_idv_child_substitution(mutate,expected):
    row=synthetic_row();mutate(row)
    rec=parse(response([row])).records[0]
    assert rec.scope is expected
    assert rec.action.revision_relationship.startswith('unknown')
    assert rec.action.deletion_relationship.startswith('unknown')
    assert SAMObservedRecord.from_dict(rec.to_dict())==rec


@pytest.mark.parametrize('presence,value,expected',[
    ('omitted',None,Presence.OMITTED),('null',None,Presence.NULL),('empty','',Presence.EMPTY),
    ('value','-NONE-',Presence.VALUE),('number',0,Presence.UNSUPPORTED),('object',{},Presence.UNSUPPORTED),
])
def test_missing_null_empty_and_placeholder_parents_do_not_prove_absence(presence,value,expected):
    row=synthetic_row()
    if presence=='omitted':row['contractId'].pop('referencedIDVPiid')
    else:row['contractId']['referencedIDVPiid']=value
    rec=parse(response([row])).records[0]
    field=next(f for f in rec.fields if f.path=='contractId.referencedIDVPiid')
    assert field.presence is expected and rec.parent_status!='verified_no_parent'


def test_correct_parent_pair_unknown_requested_parent_never_filled_from_returned_record():
    s=synthetic_selection();s=replace(s,subjects=(replace(s.subjects[0],parent_piid=None,parent_agency=None),))
    rec=parse(response(),selection=s).records[0]
    assert rec.parent_status=='verified_parent_relationship' and rec.scope is ScopeStatus.AMBIGUOUS


def test_native_standalone_D_does_not_transfer_FPDS_no_parent_rule():
    row=synthetic_row();row['coreData']['awardOrIDVType']['code']='D'
    row['contractId'].pop('referencedIDVPiid');row['contractId'].pop('referencedIDVSubtier')
    s=synthetic_selection();s=replace(s,subjects=(replace(s.subjects[0],parent_piid=None,parent_agency=None),))
    rec=parse(response([row]),selection=s).records[0]
    assert rec.parent_status=='parent_relationship_unknown' and rec.scope is ScopeStatus.AMBIGUOUS
    assert PARENT_RULE=='parent-scope-v1'


@pytest.mark.parametrize('field,value',[('modificationNumber','P00002'),('transactionNumber','1')])
def test_requested_action_constraints_checked_locally(field,value):
    s=synthetic_selection();s=replace(s,subjects=(replace(s.subjects[0],modification='P00001',transaction='0'),))
    row=synthetic_row();row['contractId'][field]=value
    assert parse(response([row]),selection=s).records[0].scope is ScopeStatus.OUT_OF_SCOPE


def test_financial_native_dates_status_prior_ids_and_revision_unknowns():
    row=synthetic_row();row['oldContractId']={'piid':'OLD'}
    rec=parse(response([row])).records[0]
    assert rec.award.identity_subtier=='0001' and rec.award.parent_subtier=='0002'
    assert rec.action.modification=='P00001' and rec.action.document_version=='1.5'
    money=next(f for f in rec.fields if f.path=='awardDetails.dollars.actionObligation')
    assert money.original_json=='"-12.00"' and money.units.endswith('unverified')
    local=next(f for f in rec.fields if f.path.endswith('createdDate'))
    assert local.original_json=='"2024-10-01T09:00:00"' # no invented zone.
    assert next(f for f in rec.fields if f.path.endswith('.status')).presence is Presence.UNSUPPORTED
    assert rec.action.correction_relationship.startswith('unknown')


@pytest.mark.parametrize('second,reason',[
    (response([synthetic_row('P00002')],total=4,offset=2),'changing_total_count'),
    (response([synthetic_row('P00001')],total=3,offset=2),'duplicate_page_content_occurrences'),
    (response([],total=3,offset=2),'unexpected_schema_or_pagination'),
    (response([synthetic_row('P00002')],total=8,offset=2),'changing_total_count'),
])
def test_page_contradictions_duplicates_and_empty_nonterminal_stop(tmp_path,second,reason):
    p,send,result=capture(tmp_path,[(fields(),response([synthetic_row('0'),synthetic_row('P00001')],total=3)),(fields(),second)])
    assert len(send.calls)==2 and result['stop_reason']==reason
    assert replay(p)[-1]==(reason,)


def test_page_cap_stops_nonterminal_without_claiming_history(tmp_path):
    p,send,result=capture(tmp_path,[(fields(),response([synthetic_row('0'),synthetic_row('P00001')],total=8)),
        (fields(),response([synthetic_row('P00002'),synthetic_row('P00003')],total=8,offset=2))])
    assert len(send.calls)==2 and result['stop_reason']=='page_cap_unverified_coverage'
    assert replay(p)[-1]==('page_cap_unverified_coverage',)


@pytest.mark.parametrize('status',[301,302,401,403,429,500,503])
def test_source_auth_rate_limit_redirect_failures_no_retry(tmp_path,status):
    p,send,result=capture(tmp_path,[(fields(status),{'message':'Synthetic source error'})])
    assert len(send.calls)==1
    assert result['stop_reason']==('authentication_failure' if status in (401,403) else 'source_error_or_unsafe_capture')
    assert replay(p)[1]==()


def test_interrupt_reservation_retained_and_never_resumed(tmp_path):
    send=transport([KeyboardInterrupt()]);p=tmp_path/'partial'
    with pytest.raises(KeyboardInterrupt):collect(p,synthetic_selection(),live=True,fixture_transport=send)
    assert (p/'sam-attempt-000-reserved.json').exists() and not (p/'sam-research-commit.json').exists()
    with pytest.raises(ValueError,match='interrupted'):replay(p)
    with pytest.raises((ValueError,OSError)):collect(p,synthetic_selection(),live=True,fixture_transport=send)
    assert len(send.calls)==1


@pytest.mark.parametrize('filename',['sam-attempt-000.body','sam-attempt-000.json','sam-attempt-000-reserved.json','sam-result.json','pilot-plan.json'])
def test_tampered_evidence_rejected(tmp_path,filename):
    p,_,_=capture(tmp_path,[(fields(),response())])
    (p/filename).write_bytes(b'changed')
    with pytest.raises(ValueError):replay(p)


@pytest.mark.parametrize('value',[
    {'api_key':KEY},{'exportToken':'fictional-token'},{'url':'https://api.sam.gov/?api_key='+KEY},
    {'url':'https://evil.invalid/?api_key='+quote(quote(KEY))},{'message':KEY},
    {'nested':{'Authorization':'redacted'}},
])
def test_secret_echo_and_token_fields_are_not_persisted(tmp_path,value):
    # Synthetic profile tests structural rejection. Live transport tests below
    # also check exact configured-key echo regardless of JSON field name.
    raw=canonical(value).encode()
    assert not body_safe(raw,KEY)
    if value=={'message':KEY}: return
    p,_,result=capture(tmp_path,[(fields(),raw)])
    assert not (p/'sam-attempt-000.body').exists()
    assert replay(p)[1]==()


def test_actual_transport_injects_key_only_in_memory_no_logs_or_redirect(monkeypatch,tmp_path,caplog):
    s=replace(synthetic_selection(),profile='live',pagination_rule='unvalidated')
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    raw=canonical(response()).encode()
    res=Mock(status_code=200,headers={'Content-Type':'application/json','ETag':'synthetic','Last-Modified':KEY})
    res.iter_content.return_value=[raw]
    call=Mock(return_value=res);monkeypatch.setattr(requests.Session,'request',call)
    p=tmp_path/'live-mocked'
    collect(p,s,live=True,sleep=lambda _:None)
    args,kw=call.call_args
    assert args==('GET','https://api.sam.gov/contract-awards/v1/search')
    assert kw['params']['api_key']==KEY and kw['allow_redirects'] is False
    assert kw['timeout']==(10,10) and kw.get('verify') is not False
    assert call.call_count==1 and KEY not in caplog.text
    assert all(KEY.encode() not in f.read_bytes() for f in p.iterdir())
    assert replay(p)[1][0][2].bounded_query_terminal is None


@pytest.mark.parametrize('kind',['echo','timeout','size','wiredebug'])
def test_live_transport_security_failure_boundaries(monkeypatch,tmp_path,kind):
    s=replace(synthetic_selection(),profile='live',pagination_rule='unvalidated')
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    raw=canonical({'arbitrary':KEY}).encode() if kind=='echo' else b'x'*1048577
    res=Mock(status_code=200,headers={});res.iter_content.return_value=[raw]
    call=Mock(side_effect=requests.Timeout(KEY)) if kind=='timeout' else Mock(return_value=res)
    monkeypatch.setattr(requests.Session,'request',call)
    if kind=='wiredebug':
        monkeypatch.setattr(http.client.HTTPConnection,'debuglevel',1)
        with pytest.raises(ValueError):collect(tmp_path/'capture',s,live=True)
        call.assert_not_called();assert not (tmp_path/'capture').exists();return
    p=tmp_path/'capture';collect(p,s,live=True)
    assert all(KEY.encode() not in f.read_bytes() for f in p.iterdir())
    assert replay(p)[1]==()


def test_api_version_change_stops_without_positive_claims(tmp_path):
    p,_,r=capture(tmp_path,[(fields(headers={'x-api-version':'v2'}),response())])
    assert r['stop_reason']=='unexpected_schema_or_pagination'
    assert not report(p)['identity_evidence_table']


@pytest.mark.parametrize('change',[
    lambda d:d.update(scope='ambiguous_scope'),lambda d:d.update(parent_status='verified_no_parent'),
    lambda d:d.update(schema_version=2),lambda d:d['action'].update(revision_relationship='same_revision'),
    lambda d:d['fields'][0].update(original_json='"fabricated"'),
])
def test_serialized_record_cannot_forge_status_or_revision(change):
    rec=parse(response()).records[0];wire=rec.to_dict();change(wire)
    with pytest.raises(ValueError):SAMObservedRecord.from_dict(wire)


def test_unsupported_artifact_hash_or_request_cannot_support_record():
    s=synthetic_selection();raw=canonical(response()).encode();req=public_request(s.subjects[0],2,0)
    a=artifact_for('sam-attempt-000.body',raw,req,fields(),'synthetic')
    with pytest.raises(ValueError):parse_page(raw,s.subjects[0],replace(a,sha256='0'*64),'meta.json',limit=2)
    with pytest.raises(ValueError):parse_page(raw,s.subjects[0],a,'meta.json',offset=1,limit=2)


def test_offline_report_unknown_live_readiness_and_no_c4_c5_or_protocol_upgrade(tmp_path):
    value=report()
    assert value['authenticated_live_metrics'] is None
    assert value['migration_recommendation']=='A. Offline prototype only'
    assert all(r['status']=='UNKNOWN' for r in value['readiness'])
    assert not value['C4_C5_eligibility_changed'] and not value['production_migration_authorized'] and not value['readiness_upgrade']
    sha=write_report(tmp_path/'report',value)
    assert digest(read_report(tmp_path/'report'))==sha
    assert protocol()['baseline_commit']=='cc4ed245adccc9809317380f00afe3690bbda589'
    assert main(['--offline','--run-dir',str(tmp_path/'cli')])==1


def test_two_demos_replay_reader_html_escaping_and_source_immutability(tmp_path):
    a=demo(tmp_path/'a');b=demo(tmp_path/'b');assert digest(a)==digest(b)
    assert a['profile']=='synthetic' and a['authenticated_live_metrics'] is None
    assert a['metrics']['pages_parsed']==2 and a['metrics']['native_record_occurrences']==3
    assert all(x['status']=='UNKNOWN' for x in a['readiness'] if x['dimension'] not in ('provenance_security','operational_reproducibility'))
    before=inventory(tmp_path/'a')
    sha=write_report(tmp_path/'report',a,protected=(tmp_path/'a',),capture=tmp_path/'a')
    assert digest(read_report(tmp_path/'report',capture=tmp_path/'a'))==sha
    assert inventory(tmp_path/'a')==before
    hostile={**a,'limitations':['<script>alert(1)</script>']}
    assert '<script>' not in html_report(hostile) and '&lt;script&gt;' in html_report(hostile)
    with pytest.raises(ValueError):write_report(tmp_path/'a'/'nested',a,protected=(tmp_path/'a',),capture=tmp_path/'a')
    (tmp_path/'report'/'sam-validation.html').write_text('changed')
    with pytest.raises(ValueError):read_report(tmp_path/'report',capture=tmp_path/'a')


def resign(path):
    files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir() if p.name!='sam-research-commit.json'}
    (path/'sam-research-commit.json').write_text(canonical({'schema_type':'SAMResearchCommit','schema_version':1,'files':files})+'\n')


@pytest.mark.parametrize('mutation',[
    lambda p:edit(p/'sam-result.json',lambda d:d.update(stop_reason=None)),
    lambda p:edit(p/'pilot-plan.json',lambda d:d.update(maximum_requests=13)),
    lambda p:edit(p/'sam-attempt-000-reserved.json',lambda d:d['request']['parameters'].update(offset=1)),
    lambda p:edit(p/'sam-attempt-000.json',lambda d:d.update(schema_version=2)),
    lambda p:edit(p/'sam-attempt-000.json',lambda d:d['headers'].update(Link='https://evil.invalid/')),
    lambda p:edit(p/'sam-result.json',lambda d:d.update(history='complete')),
    lambda p:edit(p/'sam-attempt-000.json',lambda d:d.update(capture_rejected=True)),
])
def test_resigned_controls_still_require_semantic_integrity(tmp_path,mutation):
    p,_,_=capture(tmp_path,[(fields(),response())],replace(synthetic_selection(),pagination_rule='unvalidated'))
    mutation(p);resign(p)
    with pytest.raises(ValueError):replay(p)


def edit(path,mutate):
    doc=strict_json(path.read_bytes());mutate(doc);path.write_text(canonical(doc)+'\n')


def test_three_subject_two_page_fixture_never_exceeds_six_requests(tmp_path):
    s=synthetic_selection()
    s=replace(s,subjects=tuple(replace(s.subjects[0],piid='SYNTH-'+str(i)) for i in range(3)))
    calls=[]
    def send(req,n):
        calls.append(req)
        row=synthetic_row('0' if n%2==0 else 'P00002');row['contractId']['piid']=req['parameters']['piid']
        rows=[row,synthetic_row('P00001')] if n%2==0 else [row]
        for r in rows:r['contractId']['piid']=req['parameters']['piid']
        return fields(),canonical(response(rows,total=3,offset=req['parameters']['offset'])).encode()
    p=tmp_path/'six';r=collect(p,s,live=True,fixture_transport=send)
    assert len(calls)==6<=protocol()['maximum_HTTP_requests'] and r['stop_reason'] is None
    assert len(replay(p)[1])==6
    assert report(p)['metrics']['subjects_attempted']==3


def test_conflicting_revisions_and_unstable_order_never_establish_alignment(tmp_path):
    a=synthetic_row();b=deepcopy(a);b['awardDetails']['dollars']['actionObligation']='999.00'
    p,_,_=capture(tmp_path,[(fields(),response([b,a],total=2))])
    value=report(p)
    assert value['metrics']['complete_native_action_keys_with_content_variants']==1
    assert value['metrics']['revision_relationships_established']==0
    assert value['metrics']['financial_comparisons_authorized']==0
    assert value['metrics']['financial_observations_withheld']==4
    assert 'Unstable ordering' in value['limitations'][-1]


@pytest.mark.parametrize('encode',[
    lambda s:''.join('%%%02X'%ord(c) for c in s),
    lambda s:''.join('&#'+str(ord(c))+';' for c in s),
    lambda s:''.join('\\u%04x'%ord(c) for c in s),
])
def test_encoded_key_echo_is_rejected(encode):
    encoded=encode(KEY)
    raw=('{"message":"'+encoded+'"}').encode()
    assert not body_safe(raw,KEY)


def test_report_forgeries_rejected_before_storage(tmp_path):
    value=report();value['production_migration_authorized']=True
    with pytest.raises(ValueError):write_report(tmp_path/'forged',value)
    assert not (tmp_path/'forged').exists()


def test_interrupted_nonmetadata_transport_failure_is_sanitized(tmp_path):
    p,_,result=capture(tmp_path,[ValueError(KEY)])
    assert KEY not in canonical(report(p)) and result['stop_reason']=='source_error_or_unsafe_capture'
    assert replay(p)[1]==()


def test_no_source_error_or_auth_failure_is_a_migration_candidate(monkeypatch,tmp_path):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    res=Mock(status_code=403,headers={});res.iter_content.return_value=[canonical({'message':'Forbidden'}).encode()]
    monkeypatch.setattr(requests.Session,'request',Mock(return_value=res))
    s=replace(synthetic_selection(),profile='live',pagination_rule='unvalidated')
    p=tmp_path/'mocked';collect(p,s,live=True)
    value=report(p)
    assert value['migration_recommendation']=='A. Offline prototype only'
    assert next(r for r in value['readiness'] if r['dimension']=='authorized_access')['status']=='FAIL'


def test_page_serialization_cannot_invent_history_or_terminal():
    p=parse(response());wire=p.to_dict();wire['history_complete']='complete'
    with pytest.raises(ValueError):SAMPage.from_dict(wire)
    wire=p.to_dict();wire['bounded_query_terminal']=False
    with pytest.raises(ValueError):SAMPage.from_dict(wire)


def test_legacy_and_frozen_protocol_bytes_unchanged():
    base=Path(__file__).resolve().parents[1]
    for name,expected in protocol()['frozen_protocols'].items():
        assert hashlib.sha256((base/'docs'/name).read_bytes()).hexdigest()==expected
    # Existing first-page CLI contract remains contractId-only.
    from src.sam_contracts import public_request as old_request
    assert old_request(synthetic_selection().subjects[0])['parameters']['includeSections']=='contractId'


def test_base64_and_deeply_encoded_key_echo_never_saved():
    import base64
    assert not body_safe(canonical({'message':base64.b64encode(KEY.encode()).decode()}).encode(),KEY)
    text=KEY
    for _ in range(7):text=''.join('%%%02X'%ord(c) for c in text)
    assert not body_safe(canonical({'message':text}).encode(),KEY)


def test_https_subclass_wire_debug_blocked_before_request(monkeypatch,tmp_path):
    monkeypatch.setenv('SAM_GOV_API_KEY',KEY)
    from urllib3 import connection
    monkeypatch.setattr(connection.HTTPSConnection,'debuglevel',1)
    call=Mock();monkeypatch.setattr(requests.Session,'request',call)
    selection=replace(synthetic_selection(),profile='live',pagination_rule='unvalidated')
    with pytest.raises(ValueError,match='wire_debug'):collect(tmp_path/'no',selection,live=True)
    call.assert_not_called();assert not (tmp_path/'no').exists()


def test_source_schema_failure_stops_before_other_selected_subjects(tmp_path):
    selection=synthetic_selection();selection=replace(selection,subjects=(selection.subjects[0],replace(selection.subjects[0],piid='OTHER')))
    row=synthetic_row();row['coreData']['coreVersionId']='2.0'
    p,send,r=capture(tmp_path,[(fields(),response([row]))],selection)
    assert len(send.calls)==1 and r['stop_reason']=='unexpected_schema_or_pagination'
    value=report(p)
    assert value['metrics']['subjects_requested']==2 and value['metrics']['subjects_attempted']==1
    assert value['metrics']['scope_counts']['unsupported_schema']==1


def test_replay_does_not_read_credentials(monkeypatch,tmp_path):
    from src import sam_validation_capture
    p,_,_=capture(tmp_path,[(fields(),response())])
    monkeypatch.setattr(sam_validation_capture,'credential',Mock(side_effect=AssertionError('no credential access on replay')))
    assert report(p)['profile']=='synthetic'


def test_row_cap_checked_before_constructing_any_records(monkeypatch):
    from src import sam_validation_models
    constructor=Mock(side_effect=AssertionError('oversized page must not construct records'))
    monkeypatch.setattr(sam_validation_models,'record',constructor)
    with pytest.raises(ValueError,match='envelope'):
        parse(response([synthetic_row(),synthetic_row(),synthetic_row()],total=3))
    constructor.assert_not_called()
