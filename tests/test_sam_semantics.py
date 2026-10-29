"""Authored offline adversarial fixtures; never SAM behavioral observations."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from src.evidence_io import EvidenceError, canonical, digest, strict_json
from src.readiness_audit import inventory
from src.sam_pagination_assessment import PaginationObservation, assess
from src.sam_historical_assessment import native_key, PROOF_OBLIGATIONS
from src.sam_semantics_reporting import (report, write_report, read_report, html_report,
    capture_report, pinned, PROTOCOL_SHA, MATRIX_SHA)
from src.sam_semantics import main
from src.sam_validation import synthetic_selection, synthetic_row, demo
from src.sam_validation_capture import collect, replay, protocol as c2_protocol


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.delenv('SAM_GOV_API_KEY', raising=False)


def obs(offset=0, limit=2, total=3, ids=('a','b'), *, submitted=None, counters=None, **changes):
    params={'offset': offset, 'limit': limit, 'piid': 'SYNTH-SAM-0001.A', 'piidSubtierCode': '0001'}
    params.update(submitted or {})
    v=dict(submitted_parameters_json=canonical(params),
        response_counters_json=canonical({'offset':offset, 'limit':limit, 'totalRecords':total} if counters is None else counters),
        record_content_sha256=tuple(digest(i) for i in ids), http_status=200, response_complete=True, error=False)
    v.update(changes)
    return PaginationObservation(**v)


def capture(path, rows=None, *, total=None, status=200, rule='synthetic_row_offset', stamp='2025-01-01T00:00:00Z'):
    rows = [synthetic_row()] if rows is None else rows
    selection=synthetic_selection(rule)
    calls=[]
    def send(request, sequence):
        calls.append(deepcopy(request))
        offset=request['parameters']['offset']; start=offset*2 if rule=='synthetic_page_index' else offset
        body={'awardSummary': rows[start:start+2], 'offset':offset, 'limit':2, 'totalRecords':len(rows) if total is None else total}
        return {'status':status, 'retrieved_at_utc':stamp, 'body_complete':True, 'error_code':None, 'headers':{}}, canonical(body).encode()
    collect(path, selection, live=True, fixture_transport=send, sleep=lambda _:None)
    return calls


def resign(path):
    value={'schema_type':'SAMResearchCommit','schema_version':1,
        'files':{n:s for n,s in inventory(path).items() if n!='sam-research-commit.json'}}
    (path/'sam-research-commit.json').write_text(canonical(value)+'\n')


def rewrite(path, name, change):
    v=strict_json((path/name).read_bytes()); change(v)
    (path/name).write_text(canonical(v)+'\n')


@pytest.mark.parametrize('rule,offset', [('page_index',1),('record_offset',2)])
def test_hypotheses_have_separate_offsets_and_never_enable_live(rule,offset):
    pages=(obs(),obs(offset=offset,ids=('c',)))
    result=assess(pages,profile='synthetic')
    assert result['interpretation']==rule
    assert result['bounded_query_pagination_complete'] is True
    assert result['transaction_history_complete']==result['source_wide_complete']==result['freshness']=='unknown'
    live=assess(pages,profile='live')
    assert live['interpretation']==rule and live['bounded_query_pagination_complete'] is None
    assert live['live_continuation_authorized'] is False


@pytest.mark.parametrize('total,ids', [(0,()),(1,('a',)),(2,('a','b')),(3,('a',)),(8,('a','b'))])
def test_first_page_never_resolves_semantics_or_query_support(total,ids):
    result=assess((obs(total=total,ids=ids),),profile='synthetic')
    assert result['interpretation']=='unresolved'
    assert result['bounded_query_pagination_complete'] is None
    if not ids:
        assert any('empty_feed_inconclusive' in i for i in result['issues'])


@pytest.mark.parametrize('limit',[1,2,5,10])
def test_numeric_string_counters_preserved_no_coercion_of_evidence(limit):
    page=obs(limit=limit,total=1,ids=('a',),counters={'offset':'000','limit':str(limit),'totalRecords':'01'})
    result=assess((page,),profile='synthetic')
    assert result['interpretation']=='unresolved'
    assert '"offset":"000"' in result['observations'][0]['response_counters_json']


@pytest.mark.parametrize('bad', [True,False,-1,1.5,'-1','1.0','1e3',' 1','１','',None,{},[],100000001,'100000001'])
@pytest.mark.parametrize('field', ['offset','limit','totalRecords'])
def test_invalid_numeric_counter_not_silent_complete(field,bad):
    counters={'offset':0,'limit':2,'totalRecords':3};counters[field]=bad
    result=assess((obs(counters=counters),),profile='synthetic')
    assert result['interpretation']=='contradictory_response_metadata'
    assert result['bounded_query_pagination_complete'] is None


@pytest.mark.parametrize('second', [
    obs(offset=0,ids=('c',)), # repeat
    obs(offset=3,ids=()), # skip
    obs(offset=1,ids=('c',),total=4), # changing total
    obs(offset=2,ids=('b',)), # overlap
    obs(offset=2,ids=('b','a'),total=4), # reordered duplicate page
    obs(offset=2,ids=('c',),submitted={'offset':1}), # response/request disagreement
    obs(offset=2,limit=1,ids=('c',)), # changed limit
])
def test_repeated_skipped_overlapping_and_changing_pages_block_completion(second):
    result=assess((obs(),second),profile='synthetic')
    assert result['interpretation']=='contradictory_response_metadata'
    assert result['bounded_query_pagination_complete'] is None


def test_partial_nonterminal_cannot_skip_to_next_page():
    result=assess((obs(ids=('a',)),obs(offset=2,ids=('b',))),profile='synthetic')
    assert result['interpretation']=='contradictory_response_metadata'


def test_reordered_unique_records_do_not_invent_sorting_requirement():
    a=assess((obs(ids=('b','a')),obs(offset=2,ids=('c',))),profile='synthetic')
    b=assess((obs(ids=('a','b')),obs(offset=2,ids=('c',))),profile='synthetic')
    assert a['interpretation']==b['interpretation']=='record_offset'
    assert a['observations']!=b['observations'] # exact order retained


@pytest.mark.parametrize('status',[301,302,401,403,429,500,503,None])
def test_failures_are_incomplete_not_terminal_or_verified(status):
    result=assess((obs(http_status=status),),profile='live')
    assert result['interpretation']=='incomplete_or_interrupted_capture'
    assert result['bounded_query_pagination_complete'] is None


@pytest.mark.parametrize('change',[{'error':True},{'response_complete':False},{'response_counters_json':None}])
def test_incomplete_response_and_interruption(change):
    result=assess((obs(**change),),profile='synthetic')
    assert result['interpretation']=='incomplete_or_interrupted_capture'
    assert assess((obs(),),profile='synthetic',interrupted=True)['interpretation']=='incomplete_or_interrupted_capture'


def test_nonterminal_cap_and_limit_one_ambiguity():
    result=assess((obs(total=8),obs(offset=2,total=8,ids=('c','d'))),profile='synthetic')
    assert result['interpretation']=='record_offset' and result['bounded_query_pagination_complete'] is None
    assert 'nonterminal_page_limit_or_partial_history' in result['issues']
    result=assess((obs(limit=1,total=2,ids=('a',)),obs(offset=1,limit=1,total=2,ids=('b',))),profile='synthetic')
    assert result['interpretation']=='unresolved' and len(result['compatible_hypotheses'])==2


@pytest.mark.parametrize('changes',[
    {'http_status':True},{'http_status':600},{'response_complete':1},{'error':'false'},
    {'submitted_parameters_json':'[]'},{'response_counters_json':'null'},
    {'record_content_sha256':('not-a-hash',)}, {'record_content_sha256':(digest(1),)*11},
    {'submitted_parameters_json':'{"offset":0, "limit":2}'},
])
def test_observation_schema_rejects_unsupported_shapes(changes):
    with pytest.raises((ValueError,TypeError)):obs(**changes)


def test_schema_round_trip_and_profile_caps():
    o=obs();assert PaginationObservation.from_dict(o.to_dict())==o
    v=o.to_dict();v['schema_version']=2
    with pytest.raises(ValueError):PaginationObservation.from_dict(v)
    with pytest.raises(ValueError):assess((o,o,o),profile='synthetic')
    with pytest.raises(ValueError):assess((o,),profile='production')
    with pytest.raises(ValueError):assess((o,),profile='live',interrupted=1)


@pytest.mark.parametrize('rule',['synthetic_page_index','synthetic_row_offset'])
def test_report_replays_primary_keeps_profiles_and_source_immutable(tmp_path,rule):
    p=tmp_path/'capture'; rows=[synthetic_row(str(i)) for i in range(3)]
    calls=capture(p,rows,rule=rule); before=inventory(p)
    value=report((p,)); pagination=value['captures'][0]['pagination'][0]['assessment']
    assert pagination['interpretation']==('page_index' if 'page_index' in rule else 'record_offset')
    assert pagination['bounded_query_pagination_complete'] is True
    assert value['authenticated_metrics'] is None
    assert value['synthetic_metrics']['HTTP_attempted']==len(calls)==2
    assert value['synthetic_metrics']['pages_parsed']==2
    assert value['synthetic_metrics']['native_record_occurrences']==3
    assert value['frozen_reference']['occurrences']==381
    assert value['historical_evidence']['distinct_complete_native_action_contexts']==3
    assert all(value[k] is False for k in ('live_continuation_authorized','production_migration_authorized','financial_eligibility_changed','readiness_upgrade'))
    a=write_report(tmp_path/'a',value,captures=(p,)); b=write_report(tmp_path/'b',report((p,)),captures=(p,))
    assert a==b==digest(value)
    assert read_report(tmp_path/'a',captures=(p,))==value
    assert inventory(p)==before


def test_blocked_access_reports_null_authenticated_metrics_and_repeats(tmp_path):
    value=report(access='unavailable_no_configured_credential')
    assert value['authenticated_metrics'] is value['synthetic_metrics'] is None
    assert value['authenticated_access_status']=='blocked_no_configured_credential'
    assert value['migration_recommendation']=='A. Offline prototype only'
    assert value['historical_evidence']['financial_arithmetic']=='withheld'
    assert len(value['historical_evidence']['future_comparison_proof_obligations'])==len(PROOF_OBLIGATIONS)==8
    assert all(x['status']=='UNKNOWN' for x in value['historical_evidence']['future_comparison_proof_obligations'])
    assert write_report(tmp_path/'a',value)==write_report(tmp_path/'b',value)
    assert read_report(tmp_path/'a')==value


def test_documentation_matrix_separates_states_sources_and_observations():
    v=report();matrix=v['documentation_matrix'];byid={f['id']:f for f in matrix['findings']}
    assert byid['offset']['knowledge_state']==byid['status']['knowledge_state']=='DOCUMENTATION_CONFLICT'
    assert byid['job_deleted']['knowledge_state']=='UNSUPPORTED'
    assert byid['offline_harness']['knowledge_state']=='SYNTHETIC_ONLY'
    assert all(f['authenticated_observed'] is False for f in matrix['findings'])
    assert len(matrix['sources'])==3 and all(len(s['sha256'])==64 for s in matrix['sources'])
    assert pinned('sam-semantics-protocol-v1.json',PROTOCOL_SHA)==v['protocol']
    with pytest.raises(EvidenceError):pinned('sam-documentation-matrix-v1.json','0'*64)


def test_same_content_multiple_retrievals_not_revisions(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b'
    capture(a);capture(b,stamp='2025-01-02T00:00:00Z')
    value=report((a,b));history=value['historical_evidence']
    assert history['record_occurrences']==2 and history['distinct_canonical_record_contents']==1
    assert history['same_content_groups'][0]['retrieval_relation']=='multiple_capture_occurrences_same_content'
    assert history['same_content_groups'][0]['identity_inferred_from_hash'] is False
    assert history['certified_revision_relationships']==0
    with pytest.raises(EvidenceError,match='duplicate_capture'):report((a,a))


def test_conflicting_same_action_preserved_without_correction_or_amount_arithmetic(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';r=synthetic_row();s=deepcopy(r)
    s['awardDetails']['dollars']['actionObligation']='999.99'
    s['awardDetails']['transactionData']['version']='1.4'
    s['oldContractId']={'piid':'SYNTH-PRIOR'};s['deleted']=True
    capture(a,[r]);capture(b,[s])
    v=report((a,b));h=v['historical_evidence']
    assert h['variant_native_context_groups']==1
    assert len(h['native_action_context_groups'][0]['content_variants'])==2
    assert h['certified_corrections']==h['certified_deletions']==h['certified_revision_relationships']==0
    assert h['financial_arithmetic']=='withheld'
    assert len(v['captures'])==2 # no merged winner


@pytest.mark.parametrize('mutation',[
    lambda r:r['contractId'].pop('referencedIDVPiid'),
    lambda r:r['contractId'].__setitem__('referencedIDVPiid',None),
    lambda r:r['contractId'].__setitem__('referencedIDVPiid',''),
    lambda r:r['contractId'].__setitem__('referencedIDVPiid','-NONE-'),
    lambda r:r['contractId'].__setitem__('referencedIDVPiid',123),
    lambda r:r['contractId'].pop('transactionNumber'),
])
def test_missing_empty_null_unsupported_parent_and_action_never_complete_context(tmp_path,mutation):
    r=synthetic_row();mutation(r);p=tmp_path/'capture';capture(p,[r]);v=report((p,))
    row=v['captures'][0]['records'][0]
    assert row['parent']!='verified_no_parent'
    assert v['historical_evidence']['occurrences_without_complete_native_context']==1
    assert v['historical_evidence']['distinct_complete_native_action_contexts']==0


def test_identity_fields_and_temporal_native_types_not_normalized(tmp_path):
    r=synthetic_row();r['coreData']['federalOrganization']={
        'contractingInformation':{'contractingSubtier':{'code':'0099'}},
        'fundingInformation':{'fundingSubtier':{'code':'0088'}}}
    r['contractId']['modificationNumber']='000.P-01'
    p=tmp_path/'capture';capture(p,[r]);v=report((p,));row=v['captures'][0]['records'][0]
    fields={f['path']:f for f in row['source_field_observations']}
    assert row['requested']['agency']==row['returned_native_award']['identity_subtier']=='0001'
    assert row['returned_native_action']['modification']=='000.P-01'
    assert fields['coreData.federalOrganization.contractingInformation.contractingSubtier.code']['original_json']=='"0099"'
    assert fields['coreData.federalOrganization.fundingInformation.fundingSubtier.code']['original_json']=='"0088"'
    assert fields['awardDetails.transactionData.createdDate']['original_json']=='"2024-10-01T09:00:00"'
    assert row['source_native_record_identifier']['status']=='UNKNOWN'
    assert row['citation']['evidence']['artifact']['representation']=='response_bytes'


def test_incomplete_journal_reports_unknown_counts_no_positive_rows(tmp_path):
    p=tmp_path/'partial'
    def interrupted(*args):raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):collect(p,synthetic_selection(),live=True,fixture_transport=interrupted)
    before=inventory(p);v=report((p,));c=v['captures'][0]
    assert c['state']=='incomplete_or_interrupted_capture' and c['metrics'] is None
    assert not c['records'] and not c['pagination']
    assert v['authenticated_metrics'] is v['synthetic_metrics'] is None
    assert write_report(tmp_path/'out',v,captures=(p,))==digest(v)
    assert read_report(tmp_path/'out',captures=(p,))==v
    assert inventory(p)==before


@pytest.mark.parametrize('mutation',[
    lambda v:v['request']['parameters'].__setitem__('offset',1),
    lambda v:v.__setitem__('page_index',1),
    lambda v:v.__setitem__('status',401),
    lambda v:v.__setitem__('body_complete',False),
    lambda v:v.__setitem__('representation','parsed_json'),
])
def test_rehashed_tampered_primary_controls_cannot_generate_positive_evidence(tmp_path,mutation):
    p=tmp_path/'capture';capture(p)
    rewrite(p,'sam-attempt-000.json',mutation);resign(p)
    v=report((p,));c=v['captures'][0]
    assert c['state']=='invalid_evidence_integrity_or_controls'
    assert not c['records'] and c['metrics'] is None


@pytest.mark.parametrize('name',['sam-attempt-000.body','sam-attempt-000-reserved.json','sam-result.json'])
def test_unrehashed_tamper_blocks_primary_claims(tmp_path,name):
    p=tmp_path/'capture';capture(p);(p/name).write_bytes(b'{}')
    assert report((p,))['captures'][0]['state']=='invalid_evidence_integrity_or_controls'


@pytest.mark.parametrize('field,value',[
    ('live_continuation_authorized',True),('financial_eligibility_changed',True),('readiness_upgrade',True),
    ('authenticated_metrics',{'HTTP_successful':100}),('migration_recommendation','D. Production migration'),
])
def test_forged_rehashed_report_recomputed_from_primary(tmp_path,field,value):
    p=tmp_path/'capture';capture(p);v=report((p,));out=tmp_path/'out';write_report(out,v,captures=(p,))
    def forge(doc):doc['report'][field]=value;doc['substantive_sha256']=digest(doc['report'])
    rewrite(out,'sam-semantics.json',forge)
    commit={'schema_type':'SAMSemanticsOutputCommit','schema_version':1,
        'files':{n:s for n,s in inventory(out).items() if n!='sam-semantics-commit.json'}}
    (out/'sam-semantics-commit.json').write_text(canonical(commit)+'\n')
    with pytest.raises(EvidenceError,match='projection'):read_report(out,captures=(p,))


@pytest.mark.parametrize('name',['sam-semantics.md','sam-semantics.html','pilot-plan.json'])
def test_readable_or_plan_tamper_rejected(tmp_path,name):
    p=tmp_path/'out';write_report(p,report());(p/name).write_bytes(b'bad')
    with pytest.raises(EvidenceError):read_report(p)


def test_static_html_escapes_native_text_and_primary_writer_rejects_forgery(tmp_path):
    p=tmp_path/'capture';r=synthetic_row();r['oldContractId']={'piid':'<script>alert(1)</script>'};capture(p,[r])
    v=report((p,));html=html_report(v)
    assert '<script>' not in html and '&lt;script&gt;' in html
    forged=deepcopy(v);forged['readiness_upgrade']=True
    with pytest.raises(EvidenceError):write_report(tmp_path/'no',forged,captures=(p,))
    with pytest.raises(EvidenceError):write_report(p/'nested',v,captures=(p,))
    out=tmp_path/'out';write_report(out,v,captures=(p,))
    with pytest.raises((OSError,ValueError)):write_report(out,v,captures=(p,))


def test_cli_offline_demo_replay_and_invalid_modes(tmp_path,capsys):
    assert main(['--offline','--run-dir',str(tmp_path/'offline')])==1
    assert read_report(tmp_path/'offline')['authenticated_metrics'] is None
    assert main(['--demo','--run-dir',str(tmp_path/'demo')])==1
    p=tmp_path/'demo-synthetic-evidence'
    assert main(['--root',str(p),'--run-dir',str(tmp_path/'replay')])==1
    assert read_report(tmp_path/'replay',captures=(p,))['synthetic_metrics']['pages_parsed']==2
    assert main(['--live','--run-dir',str(tmp_path/'no')])==2
    assert main(['--offline','--selection','forbidden','--run-dir',str(tmp_path/'no')])==2
    assert not (tmp_path/'no').exists()
    assert 'SAM_GOV_API_KEY' not in capsys.readouterr().out


def test_live_no_binding_zero_network_and_no_directory(tmp_path):
    selected=replace(synthetic_selection(),profile='live',pagination_rule='unvalidated')
    selection=tmp_path/'selection.json';selection.write_text(selected.to_json())
    assert main(['--live','--selection',str(selection),'--capture-dir',str(tmp_path/'capture'),
        '--run-dir',str(tmp_path/'out')])==2
    assert not (tmp_path/'capture').exists() and not (tmp_path/'out').exists()


def test_frozen_protocol_hashes_and_c2_backward_compatibility(tmp_path):
    protocol=report()['protocol']
    for name,sha in protocol['frozen_protocols'].items():
        assert hashlib.sha256((Path('docs')/name).read_bytes()).hexdigest()==sha
    assert c2_protocol()['pagination'].startswith('live_first_page_only')
    p=tmp_path/'demo';old=demo(p)
    assert replay(p)[0].profile=='synthetic' and old['metrics']['native_record_occurrences']==3
    assert report((p,))['synthetic_metrics']['native_record_occurrences']==3


@pytest.mark.parametrize('status',[301,401,403,429,500])
def test_failed_captures_report_exact_attempts_not_success_or_no_history(tmp_path,status):
    p=tmp_path/'capture';calls=capture(p,status=status)
    v=report((p,));m=v['synthetic_metrics'];a=v['captures'][0]['pagination'][0]['assessment']
    assert m['HTTP_attempted']==len(calls)==1 and m['HTTP_successful']==m['pages_parsed']==0
    assert v['authenticated_metrics'] is None and not v['captures'][0]['records']
    assert a['interpretation']=='incomplete_or_interrupted_capture'
    assert v['historical_evidence']['transaction_history_complete']=='unknown'


def test_counter_conflict_on_unparsed_page_is_preserved_and_assessed(tmp_path):
    p=tmp_path/'capture'
    def send(*args):
        return {'status':200,'retrieved_at_utc':'2025-01-01T00:00:00Z','body_complete':True,'error_code':None,'headers':{}},canonical({
            'awardSummary':[synthetic_row()], 'offset':'bad','limit':'2','totalRecords':'1'}).encode()
    collect(p,synthetic_selection(),live=True,fixture_transport=send)
    v=report((p,));a=v['captures'][0]['pagination'][0]['assessment']
    assert not v['captures'][0]['records']
    assert a['interpretation']=='contradictory_response_metadata'
    assert '"offset":"bad"' in a['observations'][0]['response_counters_json']


def test_source_change_between_validated_projection_and_metadata_rejected(tmp_path,monkeypatch):
    import src.sam_semantics_reporting as module
    p=tmp_path/'capture';capture(p);original=module.c2_report
    def changed(*args,**kwargs):
        value=original(*args,**kwargs)
        (p/'sam-attempt-000.body').write_bytes(b'{}')
        return value
    monkeypatch.setattr(module,'c2_report',changed)
    with pytest.raises(EvidenceError,match='source_changed'):report((p,))


def test_symlink_and_extra_report_artifacts_rejected(tmp_path):
    p=tmp_path/'capture';capture(p);(p/'extra').symlink_to(tmp_path/'missing')
    with pytest.raises((ValueError,OSError)):report((p,))
    out=tmp_path/'out';write_report(out,report());(out/'extra').write_text('extra')
    with pytest.raises(EvidenceError):read_report(out)


def test_versioned_proof_obligations_cannot_be_silently_promoted(tmp_path):
    v=report();v['historical_evidence']['future_comparison_proof_obligations'][0]['status']='PASS'
    with pytest.raises(EvidenceError,match='projection'):write_report(tmp_path/'out',v)


def test_live_continuation_still_impossible_even_with_synthetic_success():
    from src.sam_validation_capture import SAMResearchSelection
    for rule in ('synthetic_row_offset','synthetic_page_index'):
        with pytest.raises(ValueError,match='unvalidated'):
            replace(synthetic_selection(rule),profile='live')


def test_retrieval_time_is_source_evidence_but_output_path_is_not(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';capture(a);capture(b,stamp='2025-01-02T00:00:00Z')
    assert digest(report((a,)))!=digest(report((b,)))
    import shutil
    c=tmp_path/'c';shutil.copytree(a,c)
    assert digest(report((a,)))==digest(report((c,)))


def test_failed_live_attempt_is_not_authenticated_behavior():
    for status in (None,401,403,429):
        value=assess((obs(http_status=status),),profile='live')
        assert value['evidence_basis']=='UNKNOWN'
    assert assess((obs(),),profile='live')['evidence_basis']=='AUTHENTICATED_OBSERVED'
