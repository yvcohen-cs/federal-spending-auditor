"""C13 offline synthetic controls, not independent federal source certification."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import hashlib,json,os
import pytest

from src.evidence_io import EvidenceError,canonical,digest
from src.revision_lineage import (LineageObservation,LineageRelation,RelationKind,HistoryFacet,CoverageState,graph,facets,NATIVE)
from src.historical_probe import collect,read,plan_for
from src.historical_lineage_reporting import report,write_report,verify_report,html,main
from tests.test_source_verification import capture as c12_capture
from tests.test_evidence_acquisition import inventory


def setup(tmp_path):
    root,cases,p,c12,v=c12_capture(tmp_path)
    cases=[{**cases[0],'c12_capture':str(c12)}]
    body=json.loads((c12/'transactions/c3_attempt_000000.body').read_text())
    transcript={'schema_version':1,'responses':[{'source':'usaspending','json':body}]}
    return root,cases,c12,transcript


def captured(tmp_path,change=None):
    root,cases,c12,s=setup(tmp_path)
    if change:change(s)
    probe=tmp_path/'probe';v=collect(probe,c12,synthetic=s)
    cases[0]['historical_probe']=str(probe)
    return root,cases,c12,probe,v


def node(tmp_path):
    _,cases,_,_=setup(tmp_path)
    raw=next(n for n in report(cases)['cases'][0]['graph']['nodes'] if n['identity_supported'] and n['source']=='usaspending')
    return LineageObservation.from_dict({k:v for k,v in raw.items() if k!='node_id'})


def variant(n,label,**kw):
    return replace(n,original_occurrence_id=label,content_sha256=digest(label),**kw)


def resign(path,change):
    change(path)
    names={n:h for n,h in inventory(path).items() if n!='probe-commit.json'}
    (path/'probe-commit.json').write_text(canonical({'schema_version':1,'files':names})+'\n')


def test_original_and_C12_source_actions_are_retained_with_citations(tmp_path):
    root,cases,c12,s=setup(tmp_path);before=inventory(root);v=report(cases);c=v['cases'][0]
    assert c['before_source_native_action_counts']==c['after_source_native_action_counts']
    assert c['current_parent_proof_is_prior_C12_evidence'] and c['new_current_parent_primary_proofs']==0
    assert c['graph']['nodes'] and not c['graph']['correction_winners']
    assert all(n['citation_json'] and n['provenance_sha256'] for n in c['graph']['nodes'])
    assert inventory(root)==before and not v['financial_comparison_authorized']


def test_reverse_probe_preserves_request_direction_and_window_not_history(tmp_path):
    root,cases,c12,probe,v=captured(tmp_path)
    assert v['valid_observed_descending_window'] and v['window_agreement']=='same_observed_native_ids_and_record_contents'
    assert v['request_attempts']==1 and v['historical_interval_complete']=='unknown'
    assert json.loads((probe/'page-001.json').read_text())['request']['parameters']['order']=='desc'
    r=report(cases);c=r['cases'][0]
    assert c['new_bidirectional_window_subproofs']==1 and not c['new_historical_completeness_certificates']
    assert c['before_source_native_action_counts']==c['after_source_native_action_counts']
    assert not r['resolved_original_real_source_requirements'] and not r['resolved_original_synthetic_requirements']
    assert all(not i['original_requirement_resolved'] for i in c['original_requirement_impacts'])


@pytest.mark.parametrize('kind',['variant','duplicate','changed_update','changed_money'])
def test_competing_source_occurrences_never_choose_revision_winner(tmp_path,kind):
    n=node(tmp_path)
    if kind=='duplicate':other=replace(n,original_occurrence_id='second')
    elif kind=='changed_update':other=variant(n,'second',update_metadata_json=canonical([{'source_version':'later','updated':'2026-01-01T00:00:00Z'}]))
    elif kind=='changed_money':other=variant(n,'second',monetary_fields_json=canonical([{'original_field':'federal_action_obligation','value':{'raw_text':'-99.00'}}]))
    else:other=variant(n,'second')
    g=graph((n,other))
    assert len(g['nodes'])==2 and not g['correction_winners']
    assert all(not e['revision_precedence_established'] and not e['financial_comparison_authorized'] for e in g['relations'])
    assert any(e['kind']==(RelationKind.DUPLICATE.value if kind=='duplicate' else RelationKind.VARIANT.value) for e in g['relations'])


def test_modification_labels_do_not_imply_missing_actions_or_numeric_order(tmp_path):
    n=node(tmp_path);c=json.loads(n.native_context_json);c['modification']='P99999'
    other=variant(n,'late-label',native_context_json=canonical(c),native_action_id='literal-late-label',action_date='2020-01-01')
    n=replace(n,action_date='2025-01-01')
    g=graph((n,other));assert not g['missing_modifications']['identifiers']
    edges=[e for e in g['relations'] if e['kind']==RelationKind.DATE_ORDER.value]
    assert len(edges)==1 and edges[0]['left']==other.node_id and not edges[0]['revision_precedence_established']


@pytest.mark.parametrize('reuse',[False,True])
def test_changed_parent_pair_is_not_automatically_a_historical_transition(tmp_path,reuse):
    n=node(tmp_path);c=json.loads(n.native_context_json);c['parent_piid']='OTHER-PARENT'
    other=variant(n,'different-parent',native_context_json=canonical(c),native_action_id=n.native_action_id if reuse else 'OTHER-SOURCE-ID',action_date='2026-01-01')
    g=graph((n,other))
    assert g['possible_parent_variations'] and not g['possible_parent_variations'][0]['historical_transition_established']
    if reuse:assert any(e['kind']==RelationKind.REUSED.value for e in g['relations'])
    assert not g['correction_winners']


def test_unknown_updates_and_equal_dates_are_not_revision_alignment(tmp_path):
    n=replace(node(tmp_path),action_date=None,update_metadata_json='[]');other=variant(n,'different-content')
    g=graph((n,other))
    assert not any(e['kind']==RelationKind.DATE_ORDER.value for e in g['relations'])
    assert not any(e['revision_precedence_established'] for e in g['relations'])


@pytest.mark.parametrize('dimension',['parent_identity','modification_coverage','historical_interval','correction_lineage','freshness','monetary_semantics'])
def test_unimplemented_historical_certificates_are_rejected(dimension):
    with pytest.raises(ValueError):HistoryFacet(dimension=dimension,status=CoverageState.COMPLETE,defined_scope='finite_revalidated_observations_not_universal_history',reasons=('unsupported',),node_ids=('revision-node:v1:abc',))


@pytest.mark.parametrize('kwargs',[{'financial_comparison_authorized':True},{'revision_precedence_established':True}])
def test_relation_cannot_authorize_financial_arithmetic_or_revision_winner(kwargs):
    with pytest.raises(ValueError):LineageRelation(left='revision-node:v1:a',right='revision-node:v1:b',kind=RelationKind.VARIANT,rationale='unverified',**kwargs)


def test_local_capture_completeness_does_not_certify_full_history(tmp_path):
    n=node(tmp_path);v=facets((n,),pagination_verified=True,interval_known=True)
    assert next(f for f in v if f['dimension']=='pagination')['status']==CoverageState.COMPLETE.value
    assert all(f['status']!=CoverageState.COMPLETE.value for f in v if f['dimension'] in ('historical_interval','correction_lineage','freshness','modification_coverage','parent_identity'))
    assert all(not f['financial_comparison_authorized'] for f in v)


@pytest.mark.parametrize('field',['piid','agency','parent_piid','parent_agency','modification','transaction'])
def test_partial_identifier_components_do_not_join_cross_source_records(tmp_path,field):
    n=node(tmp_path);c=json.loads(n.native_context_json);c[field]=None
    other=variant(n,'fpds-partial',source='fpds',native_identifiers_json='[]',native_context_json=canonical(c),native_action_id='FPDS-LITERAL',parent_assertion_basis='direct_FPDS_referenced_IDV_fields',identity_supported=False)
    assert not graph((n,other))['cross_source_observations']


def test_supported_cross_source_components_are_associated_without_financial_comparison(tmp_path):
    n=node(tmp_path);other=variant(n,'fpds',source='fpds',native_identifiers_json='[]',native_action_id='FPDS-LITERAL',parent_assertion_basis='direct_FPDS_referenced_IDV_fields')
    g=graph((n,other));assert len(g['cross_source_observations'])==1
    assert g['cross_source_observations'][0]['money_relationship'].startswith('not_compared')
    assert not g['financial_comparison_authorized']


def test_SAM_never_joins_USA_FPDS_from_matching_namespaces_or_amounts(tmp_path):
    n=node(tmp_path);s=variant(n,'sam',source='samgov',native_identifiers_json='[]',native_action_id=None,parent_assertion_basis='direct_SAM_contractId_fields',monetary_fields_json='[]')
    g=graph((n,s));assert not g['cross_source_observations']
    assert any(v['status']=='unsupported_cross_source_mapping' for v in g['counterpart_obligations'])


@pytest.mark.parametrize('change',[lambda d:d.__setitem__('schema_version',2),lambda d:d.__setitem__('provenance_sha256','0'*64),lambda d:d.__setitem__('parent_assertion_basis','direct_FPDS_referenced_IDV_fields'),lambda d:d.__setitem__('native_action_id',1),lambda d:d.__setitem__('action_date','01/02/2025'),lambda d:d.__setitem__('unexpected',True)])
def test_invalid_node_contracts_fail_closed(tmp_path,change):
    n=node(tmp_path);d=n.to_dict();change(d)
    with pytest.raises(ValueError):LineageObservation.from_dict(d)


def test_duplicates_and_profile_mixing_are_not_independent_evidence(tmp_path):
    n=node(tmp_path)
    with pytest.raises(ValueError):graph((n,n))
    with pytest.raises(ValueError):graph((n,replace(n,profile='live')))


def test_graph_work_limits_apply_before_quadratic_materialization(tmp_path):
    n=node(tmp_path)
    with pytest.raises(ValueError):graph(tuple(variant(n,str(i)) for i in range(150)))
    with pytest.raises(ValueError):graph(tuple(variant(n,str(i)) for i in range(1001)))


@pytest.mark.parametrize('status',[301,302,401,403,404,429,500,503])
def test_source_failures_stop_without_retry_or_unsupported_absence_claim(tmp_path,status):
    _,cases,c12,probe,v=captured(tmp_path,lambda s:s['responses'][0].__setitem__('status',status))
    assert v['request_attempts']==1 and v['failures'] and not v['valid_observed_descending_window']
    assert not v['previously_unobserved_native_action_ids'] and v['historical_interval_complete']=='unknown'
    assert (probe/'page-001.body').exists()
    assert report(cases)['cases'][0]['new_bidirectional_window_subproofs']==0


@pytest.mark.parametrize('kind',['missing_pointer','wrong_pointer','partial_body','empty','wrong_piid','wrong_parent','wrong_modification','invalid_date'])
def test_bad_probe_fields_fail_without_completeness_promotion(tmp_path,kind):
    def change(s):
        response=s['responses'][0];body=response['json'];row=body['results'][0]
        if kind=='missing_pointer':body['page_metadata'].pop('previous')
        elif kind=='wrong_pointer':body['page_metadata']['next']=99
        elif kind=='partial_body':response['body_complete']=False
        elif kind=='empty':body['results']=[]
        elif kind=='wrong_piid':row['id']=row['id'].replace('SYNTH-C7-AGREEMENT','FOREIGN')
        elif kind=='wrong_parent':row['id']=row['id'].replace('SYNTH-PARENT','FOREIGN')
        elif kind=='wrong_modification':row['modification_number']='P00009'
        else:row['action_date']='2025-02-30'
    _,cases,_,_,v=captured(tmp_path,change)
    assert not v['valid_observed_descending_window']
    r=report(cases);assert not r['resolved_original_real_source_requirements'] and not r['resolved_original_synthetic_requirements']
    assert not r['cases'][0]['new_bidirectional_window_subproofs']


@pytest.mark.parametrize('kind',['overlap','variant','reverse_dates'])
def test_duplicate_or_out_of_order_reverse_windows_are_rejected(tmp_path,kind):
    def change(s):
        body=s['responses'][0]['json'];body['results'].append(deepcopy(body['results'][0]))
        if kind=='variant':body['results'][-1]['federal_action_obligation']=999
        if kind=='reverse_dates':body['results'][-1]['action_date']='2026-01-01'
    _,_,_,_,v=captured(tmp_path,change);assert not v['valid_observed_descending_window'] and v['failures']


def test_nonterminal_window_and_interrupted_second_request_preserve_evidence(tmp_path):
    root,cases,c12,s=setup(tmp_path)
    s['responses'][0]['json']['page_metadata'].update(hasNext=True,next=2)
    out=tmp_path/'partial'
    with pytest.raises(ValueError):collect(out,c12,synthetic=s)
    assert (out/'page-001.body').exists() and (out/'page-002-reservation.json').exists()
    with pytest.raises(ValueError):read(out,c12)
    with pytest.raises((ValueError,OSError)):collect(out,c12,synthetic=s)


@pytest.mark.parametrize('kind',['body','metadata','reservation','manifest','extra','schema','truncate'])
def test_mutated_probe_cannot_pass_even_with_resigned_outer_manifest(tmp_path,kind):
    _,cases,c12,probe,v=captured(tmp_path)
    def change(p):
        if kind=='body':(p/'page-001.body').write_text('{}')
        elif kind=='metadata':(p/'page-001.json').write_text('{}')
        elif kind=='reservation':(p/'page-001-reservation.json').write_text('{}')
        elif kind=='extra':(p/'page-003.json').write_text('{}')
        elif kind=='schema':
            d=json.loads((p/'pilot-plan.json').read_text());d['schema_version']=2;(p/'pilot-plan.json').write_text(canonical(d)+'\n')
        elif kind=='truncate':(p/'page-001.body').unlink()
        else:(p/'probe-commit.json').write_text('{}')
    resign(probe,change)
    if kind=='manifest':(probe/'probe-commit.json').write_text('{}')
    with pytest.raises(ValueError):read(probe,c12)


@pytest.mark.parametrize('kind',['symlink','hardlink'])
def test_probe_path_substitution_is_rejected(tmp_path,kind):
    _,_,c12,probe,_=captured(tmp_path);p=probe/'page-001.body';other=tmp_path/'other';p.rename(other)
    if kind=='symlink':p.symlink_to(other)
    else:os.link(other,p)
    with pytest.raises((ValueError,OSError)):read(probe,c12)


def test_changed_C12_anchor_is_not_silently_rebound(tmp_path):
    _,_,c12,probe,_=captured(tmp_path);(c12/'detail-001.body').write_text('{}')
    with pytest.raises(ValueError):read(probe,c12)


@pytest.mark.parametrize('kwargs',[{}, {'live':True},{'live':'yes'}])
def test_probe_offline_default_never_initializes_live_transport(tmp_path,monkeypatch,kwargs):
    _,_,c12,s=setup(tmp_path)
    monkeypatch.setattr('src.historical_probe.HTTPTransport',lambda *a,**kw:pytest.fail('network initialized'))
    with pytest.raises(ValueError):collect(tmp_path/'no',c12,**kwargs)
    assert not (tmp_path/'no').exists()


def test_synthetic_probe_cannot_look_up_credentials_or_initialize_HTTP(tmp_path,monkeypatch):
    monkeypatch.setattr('src.historical_probe.HTTPTransport',lambda *a,**kw:pytest.fail('network initialized'))
    monkeypatch.setattr('src.sam_validation_capture.credential',lambda:pytest.fail('credential discovery'))
    _,_,_,_,v=captured(tmp_path);assert v['knowledge_basis']=='SYNTHETIC_ONLY'


def test_money_changes_are_retained_without_totals_or_financial_eligibility(tmp_path):
    def change(s):s['responses'][0]['json']['results'][0]['federal_action_obligation']=-99.99
    _,cases,_,_,v=captured(tmp_path,change);r=report(cases)
    assert v['window_agreement']=='different_or_partial_observed_window'
    assert any(c.get('monetary_fields_differ') for c in r['cases'][0]['graph']['competing_observations'])
    assert not r['financial_comparison_authorized'] and not r['resolved_original_real_source_requirements']
    assert not r['cases'][0]['new_bidirectional_window_subproofs']


def test_reports_repeat_and_verify_all_projections_against_primary_inputs(tmp_path):
    _,cases,_,_,_=captured(tmp_path);a=tmp_path/'a';b=tmp_path/'b'
    assert write_report(a,cases)==write_report(b,cases) and inventory(a)==inventory(b)
    assert verify_report(a,cases)==report(cases)
    (a/'lineage.json').write_text('{}')
    with pytest.raises(ValueError):verify_report(a,cases)


@pytest.mark.parametrize('name',['lineage.md','lineage.html','lineage-commit.json','pilot-plan.json'])
def test_truncated_and_unsupported_reports_fail_closed(tmp_path,name):
    _,cases,_,_,_=captured(tmp_path);out=tmp_path/'r';write_report(out,cases);(out/name).write_text('{}')
    with pytest.raises(ValueError):verify_report(out,cases)


def test_fully_resigned_false_completeness_report_still_requires_primary_replay(tmp_path):
    _,cases,_,_,_=captured(tmp_path);out=tmp_path/'r';write_report(out,cases)
    d=json.loads((out/'lineage.json').read_text());d['resolved_original_real_source_requirements']=d['original_resolution_plan_ids']
    from src.historical_lineage_reporting import projections
    for name,raw in projections(d).items():(out/name).write_bytes(raw)
    names={n:h for n,h in inventory(out).items() if n!='lineage-commit.json'}
    (out/'lineage-commit.json').write_text(canonical({'schema_version':1,'files':names,'report_sha256':digest(d)})+'\n')
    with pytest.raises(ValueError):verify_report(out,cases)


def test_HTML_is_static_escaped_and_never_exposes_raw_source_person_fields(tmp_path):
    _,cases,_,_=setup(tmp_path);v=report(cases);v['limitations'].append('<script>alert(1)</script>')
    text=html(v);assert '<script>' not in text and '&lt;script&gt;' in text and "default-src 'none'" in text
    assert 'api_key' not in canonical(v)


def test_case_sequences_are_explicit_and_unknown_recipes_rejected():
    for cases in ([],{},iter([{}]),[{'unexpected':True}],[{'historical_probe':'x'}]):
        with pytest.raises(ValueError):report(cases)


def test_CLI_offline_and_partial_exit_codes(tmp_path,capsys):
    _,cases,_,_,_=captured(tmp_path,lambda s:s['responses'][0].__setitem__('status',500))
    p=tmp_path/'cases.json';p.write_text(canonical(cases))
    assert main(['--cases',str(p),'--output',str(tmp_path/'report')])==1
    assert main(['--cases',str(p),'--output',str(tmp_path/'none'),'--live'])==2
    assert not (tmp_path/'none').exists()


def test_SAM_preserved_native_versions_status_money_and_dates_are_not_crosswalks(tmp_path):
    from src.sam_validation import demo
    from src.scope_models import ScopeRequest
    root=tmp_path/'sam';demo(root)
    # The frozen demo's subject is authoritative for this synthetic scope.
    plan=json.loads((root/'sam-research-plan.json').read_text()) if (root/'sam-research-plan.json').exists() else json.loads((root/'pilot-plan.json').read_text())
    scope=plan['selection']['subjects'][0]
    r=report([{'sam_captures':[str(root)],'scope':scope}])
    ns=r['cases'][0]['graph']['nodes'];assert ns and all(n['source']=='samgov' and n['native_action_id'] is None for n in ns)
    assert any(json.loads(n['monetary_fields_json']) for n in ns)
    assert not r['cases'][0]['graph']['cross_source_observations']
    assert not r['financial_comparison_authorized']


def two_pages(s):
    template=s['responses'][0]['json']['results'][0]
    rows=[]
    for index,mod in enumerate(('P00003','P00002','P00001','0')):
        r=deepcopy(template);r['id']=r['id'].replace('_P00001_','_'+mod+'_');r['modification_number']=mod;r['action_date']='2025-01-0'+str(4-index);rows.append(r)
    s['responses']=[{'source':'usaspending','json':{'results':rows[:2],'page_metadata':{'page':1,'hasNext':True,'hasPrevious':False,'next':2,'previous':None}}},
        {'source':'usaspending','json':{'results':rows[2:],'page_metadata':{'page':2,'hasNext':False,'hasPrevious':True,'next':None,'previous':1}}}]


def test_valid_two_page_reverse_chain_preserves_four_actions_without_full_history_claim(tmp_path):
    _,cases,_,_,v=captured(tmp_path,two_pages)
    assert v['request_attempts']==2 and len(v['records'])==4 and v['valid_observed_descending_window']
    assert v['window_agreement']=='different_or_partial_observed_window'
    assert len(v['previously_unobserved_native_action_ids'])==3
    r=report(cases);assert r['cases'][0]['after_source_native_action_counts']['usaspending']==4
    assert not r['resolved_original_synthetic_requirements'] and not r['financial_comparison_authorized']


@pytest.mark.parametrize('field,bad',[('page',3),('hasPrevious',False),('previous',0),('next',3),('hasNext',True)])
def test_bad_second_page_keeps_first_observations_but_not_window_certification(tmp_path,field,bad):
    def change(s):two_pages(s);s['responses'][1]['json']['page_metadata'][field]=bad
    _,cases,_,_,v=captured(tmp_path,change)
    assert v['request_attempts']==2 and not v['valid_observed_descending_window']
    assert not report(cases)['cases'][0]['new_bidirectional_window_subproofs']


def test_maximum_pages_is_partial_even_with_coherent_last_next_pointer(tmp_path):
    def change(s):two_pages(s);s['responses'][1]['json']['page_metadata'].update(hasNext=True,next=3)
    _,cases,_,probe,v=captured(tmp_path,change)
    assert v['request_attempts']==2 and not v['valid_observed_descending_window']
    assert not (probe/'page-003-reservation.json').exists()
    assert not report(cases)['cases'][0]['new_bidirectional_window_subproofs']


def test_same_day_different_modifications_do_not_get_revision_precedence(tmp_path):
    n=node(tmp_path);c=json.loads(n.native_context_json);c['modification']='A00099'
    other=variant(n,'same-date',native_context_json=canonical(c),native_action_id='OTHER-ID')
    assert not any(e['kind']==RelationKind.DATE_ORDER.value for e in graph((n,other))['relations'])


def test_missing_parent_components_do_not_join_date_timelines(tmp_path):
    n=node(tmp_path);c=json.loads(n.native_context_json);c['parent_piid']=c['parent_agency']=None
    a=replace(n,native_context_json=canonical(c),action_date='2020-01-01');b=variant(a,'later',native_action_id='OTHER',action_date='2025-01-01')
    assert not any(e['kind']==RelationKind.DATE_ORDER.value for e in graph((a,b))['relations'])


def test_outside_requested_records_do_not_acquire_current_parent_or_cross_source_credit(tmp_path):
    n=replace(node(tmp_path),outside_requested_context=True)
    other=variant(n,'fpds',source='fpds',native_action_id='FPDS',native_identifiers_json='[]',parent_assertion_basis='direct_FPDS_referenced_IDV_fields')
    assert not graph((n,other))['cross_source_observations']
    assert next(f for f in facets((n,),pagination_verified=True) if f['dimension']=='pagination')['status']!=CoverageState.COMPLETE.value


def test_synthetic_results_are_separate_from_real_source_metrics(tmp_path):
    _,cases,_,_,_=captured(tmp_path);r=report(cases)
    assert r['profile']=='synthetic' and r['new_synthetic_window_subproofs']==1 and r['new_real_source_window_subproofs']==0


def test_missing_and_future_source_update_markers_never_certify_freshness(tmp_path):
    n=node(tmp_path)
    for marker in ('[]',canonical([{'source_update':'2099-01-01T00:00:00Z'}])):
        changed=replace(n,update_metadata_json=marker)
        assert next(f for f in facets((changed,)) if f['dimension']=='freshness')['status']==CoverageState.INSUFFICIENT.value


def test_former_or_corrected_identifiers_are_not_directed_replacement_proof(tmp_path):
    n=node(tmp_path);other=variant(n,'corrected',update_metadata_json=canonical([{'oldContractId':'prior','version':'2','native_status':'corrected'}]))
    g=graph((n,other))
    assert any(e['kind']==RelationKind.VARIANT.value for e in g['relations'])
    assert not g['correction_winners'] and not any(e['revision_precedence_established'] for e in g['relations'])


def test_source_native_identifier_namespace_and_bounded_complete_scope_are_validated(tmp_path):
    n=node(tmp_path)
    with pytest.raises(ValueError):replace(n,native_identifiers_json=canonical([{'source':'samgov','namespace':'id','value':'x'}]))
    with pytest.raises(ValueError):replace(n,source='samgov',native_identifiers_json='[]',parent_assertion_basis='direct_SAM_contractId_fields')
    with pytest.raises(ValueError):HistoryFacet(dimension='pagination',status=CoverageState.COMPLETE,defined_scope='all_contract_history',reasons=('unsupported',),node_ids=(n.node_id,))


def test_original_C12_and_frozen_protocol_evidence_is_read_only(tmp_path):
    root,cases,c12,probe,_=captured(tmp_path);before={str(p):inventory(p) for p in (root,c12,probe)}
    report(cases)
    assert before=={str(p):inventory(p) for p in (root,c12,probe)}


@pytest.mark.parametrize('issue,dimension',[('within_record_native_component_conflict','award_identity'),('within_record_parent_component_conflict','parent_identity')])
def test_within_record_contradictions_are_distinct_from_insufficient_history(tmp_path,issue,dimension):
    n=replace(node(tmp_path),identity_supported=False,issues=(issue,))
    assert next(f for f in facets((n,)) if f['dimension']==dimension)['status']==CoverageState.CONFLICT.value


def test_requested_interval_is_separate_from_frozen_original_requirement_scope(tmp_path):
    from src.history_qualification import HistoricalInterval
    _,cases,_,_,_=captured(tmp_path)
    before=report(cases);cases[0]['comparison_interval']=HistoricalInterval(start_date='2017-01-01',end_date='2026-01-01').to_dict()
    after=report(cases)
    assert after['original_resolution_plan_ids']==before['original_resolution_plan_ids']
    c=after['cases'][0]
    assert c['requested_historical_interval']['start_date']=='2017-01-01'
    assert c['original_qualification_requested_interval']['start_date'] is None
    assert c['unresolved_intervals'][0]['status']=='entire_requested_interval_uncertified'
    assert not c['new_historical_completeness_certificates']


def test_replayed_identical_case_cannot_double_source_subproof_counts(tmp_path):
    _,cases,_,_,_=captured(tmp_path)
    with pytest.raises(ValueError):report(cases+cases)


def test_synthetic_transcripts_cannot_exceed_two_reserved_requests(tmp_path):
    _,_,c12,s=setup(tmp_path);s['responses']=s['responses']*3
    with pytest.raises(ValueError):collect(tmp_path/'none',c12,synthetic=s)
    assert not (tmp_path/'none').exists()


def test_original_partial_or_minimal_windows_do_not_inherit_new_window_completeness(tmp_path):
    _,cases,_,_,_=captured(tmp_path);r=report(cases);c=r['cases'][0]
    assert c['new_bidirectional_window_subproofs']==1
    # Frozen synthetic original C3 metadata omits optional C3 pointers, so only
    # the later C12/C13 windows satisfy the stricter contract.
    assert not all(w['USA_windows_verified'] for w in c['original_window_checks'])
    us=next(s for s in c['historical_assessments'] if s['source']=='usaspending')
    assert next(f for f in us['facets'] if f['dimension']=='pagination')['status']!=CoverageState.COMPLETE.value


def test_unattempted_sources_are_not_evaluated_and_empty_captures_insufficient(tmp_path):
    _,cases,_,_=setup(tmp_path);c=report(cases)['cases'][0]
    sam=next(s for s in c['historical_assessments'] if s['source']=='samgov')
    assert all(f['status']==CoverageState.NOT_EVALUATED.value for f in sam['facets'])
    fpds=next(s for s in c['historical_assessments'] if s['source']=='fpds')
    assert fpds['overall_historical_status']==CoverageState.INSUFFICIENT.value


def test_probe_HTTP_update_metadata_is_preserved_without_freshness_claim(tmp_path):
    _,cases,_,_,_=captured(tmp_path,lambda s:s['responses'][0].__setitem__('source_update_raw','Wed, 01 Jan 2025 00:00:00 GMT'))
    c=report(cases)['cases'][0]
    assert any('Wed, 01 Jan 2025' in n['update_metadata_json'] for n in c['graph']['nodes'])
    assert all(next(f for f in s['facets'] if f['dimension']=='freshness')['status']!=CoverageState.COMPLETE.value for s in c['historical_assessments'])


def test_CLI_rejects_original_case_mismatch_before_source_access(tmp_path,monkeypatch):
    _,cases,c12,s=setup(tmp_path);cases[0]['scope']={**cases[0]['scope'],'piid':'FOREIGN'};cases[0]['historical_probe']=str(tmp_path/'new-probe')
    p=tmp_path/'cases.json';p.write_text(canonical(cases))
    monkeypatch.setattr('src.historical_lineage_reporting.collect_probe',lambda *a,**kw:pytest.fail('source access before binding'))
    assert main(['--cases',str(p),'--capture-probe','--live','--output',str(tmp_path/'report')])==2
    assert not (tmp_path/'new-probe').exists()


def test_frozen_C12_and_prior_protocol_documents_remain_byte_identical():
    root=Path(__file__).resolve().parents[1]
    v=json.loads((root/'docs/historical-lineage-protocol-v1.json').read_text())
    assert v['starting_main']=='e96a2ae4af41fbc3f8a9282580c9a3a4c0abab44' and len(v['frozen_files'])==55
    for name,sha in v['frozen_files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==sha


def test_cross_source_graph_requires_existing_verified_scope_not_only_components(tmp_path):
    n=replace(node(tmp_path),existing_native_scope_verified=False)
    other=variant(n,'fpds',source='fpds',native_identifiers_json='[]',native_action_id='FPDS',parent_assertion_basis='direct_FPDS_referenced_IDV_fields',existing_native_scope_verified=True)
    assert not graph((n,other))['cross_source_observations']


def test_window_subproof_never_attaches_to_foreign_context_resolution_plans(tmp_path):
    from tests.test_source_verification import setup as c12_setup
    from src.history_demo import fixture,collect_fixture
    from src.scope_models import ScopeRequest
    from src.acquisition_planning import prepare
    from src.source_verification import VerificationExperiment,experiment
    from tests.test_evidence_acquisition import job
    _,_,_,scenario=c12_setup(tmp_path/'seed')
    a,body=fixture('equal_control')
    us=next(r for r in body['responses'] if r['source']=='usaspending')['json']
    foreign=deepcopy(us['results'][0]);foreign['id']=foreign['id'].replace('SYNTH-C7-AGREEMENT','FOREIGN-PIID');us['results'].append(foreign)
    original=tmp_path/'original';collect_fixture(original,a,body)
    scope=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    cases=[{'collections':[str(original)],'scope':scope.to_dict()}]
    q=prepare(cases);spec=job(q,'usaspending')
    c12=tmp_path/'c12';experiment(c12,VerificationExperiment(queue=q,request_id=spec.request_id,mode='synthetic_only'),synthetic=scenario)
    probe=tmp_path/'probe';collect(probe,c12,synthetic=scenario['transactions'])
    cases[0].update(c12_capture=str(c12),historical_probe=str(probe))
    impacts=report(cases)['cases'][0]['original_requirement_impacts']
    outside=[p for p in impacts if p['native_context'].get('piid')=='FOREIGN-PIID']
    assert outside and all(p['partial_subproof'] is None and not p['new_evidence_node_ids'] for p in outside)
    assert any(p['partial_subproof'] is not None for p in impacts)
