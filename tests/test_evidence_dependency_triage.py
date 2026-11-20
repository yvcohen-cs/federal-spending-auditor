"""Literal synthetic proof obligations, not source access or confidence scores."""
from copy import deepcopy
from dataclasses import replace
import json
import pytest
from src.evidence_io import canonical,digest
from src.history_qualification import requirement,QualificationStatus as Q
from src.evidence_dependency_triage import assess_dependencies,RequirementDependency,DependencyGroup,PARENT,OUTSIDE
from src.parent_authority_acquisition import plan
from src.correction_reporting import report as c14_report
from tests.test_historical_source_authority import original_case


def entry(dimension,reasons,*,status=Q.INSUFFICIENT,namespace='usaspending',name='ONE'):
    req=requirement(dimension,status,tuple(reasons),('history-observation:v1:'+digest(name),)).to_dict()
    return {'original_plan_id':'evidence-resolution:v1:'+digest(name),'dimension':dimension,
        'native_context':{'namespace':namespace,'piid':'00001','agency':'0001','parent_piid':'IDV-00001','parent_agency':'0001'},
        'original_requirement':req,'original_remaining_dependencies':list(reasons)}


def case(*entries):return {'profile':'synthetic','original_case_sha256':digest('CASE'),'original_requirement_impacts':list(entries)}
def assessed(*entries,**kwargs):return assess_dependencies([case(*entries)],[p['original_plan_id'] for p in entries],**kwargs)


@pytest.mark.parametrize('dimension,reasons,group',[
    ('parent_identity',[PARENT],'parent_primary_existence'),
    ('parent_identity',['parent_applicability_or_pair_unknown'],'historical_parent_applicability'),
    ('counterpart_coverage',['counterpart_not_observed_not_proven_absent'],'source_native_crosswalk'),
    ('native_identity',['native_action_or_award_context_missing'],'source_native_crosswalk'),
    ('revision_completeness',['no_authoritative_correction_deletion_or_revision_lineage'],'revision_correction_authority'),
    ('as_of_alignment',['no_common_native_revision_or_asof_certificate','requested_asof_unknown'],'revision_correction_authority'),
    ('source_completeness',['authoritative_history_interval_and_source_coverage_missing','nonterminal_observed_chain'],'history_completeness'),
    ('monetary_semantics',['missing_supported_action_obligation_field_no_award_total_substitution'],'financial_semantics'),
    ('currency_amount',['missing_invalid_or_unsupported_amount_currency_or_precision'],'financial_semantics'),
    ('freshness',['retrieval_or_declared_update_not_freshness_certificate'],'other_unsupported_dependencies')])
def test_grouping_uses_actual_missing_proof(dimension,reasons,group):
    r=assessed(entry(dimension,reasons));assert r['requirements'][0]['group']==group
    assert sum(r['exclusive_group_counts'].values())==1 and not r['financial_comparison_authorized']


@pytest.mark.parametrize('dimension',['native_identity','parent_identity','counterpart_coverage','source_completeness',
    'revision_completeness','as_of_alignment','monetary_semantics','currency_amount','freshness'])
def test_outside_context_is_not_relabelled_financial_or_source_failure(dimension):
    r=assessed(entry(dimension,[OUTSIDE],status=Q.NOT_EVALUATED))
    assert r['requirements'][0]['group']=='other_unsupported_dependencies'
    assert r['requirements'][0]['blocker']=='explicit_reselection_not_a_discrepancy'
    assert not r['candidate_plans'] and r['original_status_counts']=={'NOT_EVALUATED':1}
    assert r['dimension_status_counts'][dimension]=={'NOT_EVALUATED':1}


def test_unknown_dependency_preserved_without_guessing():
    p=entry('parent_identity',['SYNTH-UNKNOWN-RULE']);r=assessed(p)
    assert r['requirements'][0]['group']=='other_unsupported_dependencies'
    assert r['requirements'][0]['missing_dependencies']==['SYNTH-UNKNOWN-RULE']


@pytest.mark.parametrize('namespace',['fpds','samgov'])
def test_USA_access_does_not_establish_other_source_parent_access(namespace):
    r=assessed(entry('parent_identity',[PARENT],namespace=namespace))
    assert r['requirements'][0]['acquisition_path']=='SOURCE_NATIVE_PARENT_ADAPTER_OR_CROSSWALK_VALIDATION_REQUIRED'
    assert not r['next_acquisition_shortlist']


@pytest.mark.parametrize('field',['piid','agency','parent_piid','parent_agency'])
def test_missing_native_context_stays_blocked(field):
    p=entry('parent_identity',[PARENT]);p['native_context'][field]=None
    r=assessed(p);assert r['requirements'][0]['acquisition_path']=='EXACT_NATIVE_CHILD_PARENT_CONTEXT_REQUIRED'


def test_duplicate_missing_or_unknown_original_IDs_fail_closed():
    p=entry('parent_identity',[PARENT]);key=p['original_plan_id']
    with pytest.raises(ValueError):assess_dependencies([case(p,p)],[key])
    with pytest.raises(ValueError):assess_dependencies([case(p)],[key,key])
    with pytest.raises(ValueError):assess_dependencies([case(p)],['evidence-resolution:v1:'+digest('OTHER')])
    with pytest.raises(ValueError):assessed(p,resolved_now=['evidence-resolution:v1:'+digest('OTHER')])


def test_mixed_profiles_and_already_qualified_requirements_reject():
    p=entry('parent_identity',[PARENT]);q=entry('parent_identity',[PARENT],name='TWO')
    c=case(q);c.update(profile='live',original_case_sha256=digest('CASE2'))
    with pytest.raises(ValueError):assess_dependencies([case(p),c],[p['original_plan_id'],q['original_plan_id']])
    p['original_requirement']=requirement('parent_identity',Q.QUALIFIED,('SYNTH-EVIDENCE',),('SYNTH-CITATION',)).to_dict()
    with pytest.raises(ValueError):assessed(p)


def test_partition_and_current_disposition_do_not_overwrite_original_proof():
    a=entry('parent_identity',[PARENT]);b=entry('source_completeness',['requested_history_interval_unknown'],name='TWO')
    before=canonical([a,b]);r=assessed(a,b,resolved_now=[a['original_plan_id']])
    assert r['baseline_unresolved_count']==2 and r['current_remaining_count']==1
    assert r['resolved_in_current_phase']==[a['original_plan_id']] and canonical([a,b])==before
    assert all(json.loads(p['original_requirement_json'])['status']=='INSUFFICIENT_EVIDENCE' for p in r['requirements'])


def test_serialized_group_or_financial_authorization_cannot_override_dependencies():
    p=entry('parent_identity',[PARENT]);row=assessed(p)['requirements'][0]
    with pytest.raises(ValueError):RequirementDependency.from_dict({**row,'group':'financial_semantics'})
    with pytest.raises(ValueError):RequirementDependency.from_dict({**row,'financial_comparison_authorized':True})
    with pytest.raises(ValueError):RequirementDependency.from_dict({**row,'confidence_score':0.99})


@pytest.fixture
def candidate(tmp_path):
    c,_,_=original_case(tmp_path/'original');old=c14_report([c])['cases'][0];p=plan(c)
    key=p['original_requirement_id']
    return old,key,{'plan':p,'preserved_query_terminal':True,'preserved_record_occurrences':2,
                    'preserved_query_citations':[{'synthetic_citation':'authored-original-query'}]}


def test_valid_prospective_plan_does_not_claim_current_access(candidate):
    old,key,p=candidate;r=assess_dependencies([old],[key],candidates=[p])
    c=r['next_acquisition_shortlist'][0]
    assert c['access_status']=='NOT_TESTED_CURRENT_CONTEXT' and not c['source_current_access_verified']
    assert not c['original_requirement_resolution_guaranteed'] and not c['financial_comparison_authorized']


@pytest.mark.parametrize('field,value',[('original_requirement_id','evidence-resolution:v1:'+'0'*64),
    ('original_case_sha256','0'*64),('maximum_requests',50),('retries',False),('redirects',True),('profile','live')])
def test_changed_candidate_binding_or_budget_rejects(candidate,field,value):
    old,key,p=candidate;p=deepcopy(p);p['plan'][field]=value
    with pytest.raises(ValueError):assess_dependencies([old],[key],candidates=[p])


def test_replayed_plan_and_unresolved_pagination_do_not_inflate_shortlist(candidate):
    old,key,p=candidate
    with pytest.raises(ValueError):assess_dependencies([old],[key],candidates=[p,deepcopy(p)])
    p['preserved_query_terminal']=False;r=assess_dependencies([old],[key],candidates=[p])
    c=r['next_acquisition_shortlist'][0]
    assert not c['bounded_same_budget_candidate'] and c['next_action']=='VALIDATE_CHILD_PAGINATION_CONTRACT_AND_BUDGET_FIRST'
    assert not assess_dependencies([old],[key],candidates=[p],resolved_now=[key])['next_acquisition_shortlist']


def test_order_independent_deterministic_assessment():
    a=entry('parent_identity',[PARENT]);b=entry('freshness',['retrieval_or_declared_update_not_freshness_certificate'],name='TWO')
    assert canonical(assessed(a,b))==canonical(assessed(b,a))
