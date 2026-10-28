from copy import deepcopy
from dataclasses import replace
from decimal import localcontext
import json

import pytest

from src.evidence import Completeness
from src.evidence_io import EvidenceError,digest
from src.history_demo import CASES,collect_fixture,fixture
from src.history_ingestion import reconstruct
from src.history_models import Alignment, HistoricalStatus as S, HistoryVerificationRun, temporal, FreshnessAssessment
from src.history_reporting import metrics,research_report
from src.history_rules import alignment,compare,compare_observations
from src.scope_models import ScopeRequest


def make(tmp_path,case='equal_control',transform=None,name='source'):
    a,data=fixture(case)
    if transform: transform(data)
    root=tmp_path/name;collect_fixture(root,a,data)
    request=ScopeRequest(piid=a.piid,agency=a.agency_id,parent_piid=a.parent_piid,parent_agency=a.parent_agency_id)
    return root,request,reconstruct((root,),request)


@pytest.fixture(scope='module')
def cases(tmp_path_factory):
    p=tmp_path_factory.mktemp('history-cases')
    return {case:make(p,case,name=case)[2] for case in CASES}


@pytest.mark.parametrize('case,status,count',[
    ('initial_and_modifications',S.AGREEMENT,4),('equal_revision_unknown',S.REVISION_UNKNOWN,1),('equal_control',S.AGREEMENT,1),
    ('unequal_control',S.UNEQUAL,1),('different_revisions',S.REVISION_DIFFERENCE,1),('missing_intermediate',S.AGREEMENT,2),
    ('multiple_transactions',S.AGREEMENT,2),('out_of_order',S.AGREEMENT,3),('duplicate_observations',S.AGREEMENT,3),
    ('contradictory_observations',S.SCOPE_UNCERTAIN,3),('missing_parent',S.SCOPE_UNCERTAIN,3),
    ('scope_mismatch',S.SCOPE_UNCERTAIN,1),('malformed_date',S.UNSUPPORTED,1),('incompatible_signed_date',S.INCOMPATIBLE,1),
    ('cumulative_only',S.UNSUPPORTED,1),('partial_pagination',S.REVISION_UNKNOWN,1),('empty_feed',S.HISTORY_INSUFFICIENT,1)])
def test_known_answer_cases(cases,case,status,count):
    run=cases[case]
    assert sum(c.status is status for c in run.comparisons)==count
    assert all(c.difference_left_minus_right is None for c in run.comparisons if c.status not in (S.AGREEMENT,S.UNEQUAL))


def test_negative_zero_initial_and_positive_modifications_remain_normal(cases):
    run=cases['initial_and_modifications']
    values={m.observation.value.normalized for o in run.observations for m in o.money if m.observation.original_field=='federal_action_obligation'}
    assert values=={'100','-20','0','50'}
    assert all(c.status is S.AGREEMENT for c in run.comparisons)
    assert metrics(run)['distinct_eligible_action_identities']==4


def test_same_modification_different_transactions_and_no_gap_inference(cases):
    run=cases['multiple_transactions']
    assert metrics(run)['distinct_eligible_action_identities']==2
    assert metrics(run)['distinct_eligible_modifications']==1
    for c in cases['missing_intermediate'].coverage:
        assert c.authoritative_sequence_rule is None and c.historical_completeness is Completeness.UNKNOWN


def test_retrieval_order_and_action_dates_remain_distinct(cases):
    report=research_report(cases['out_of_order'])
    assert 'not_authoritative' in report['ordering_basis']
    fpds=next(o for o in cases['equal_control'].observations if o.scope_assessment.evidence.reference.source=='fpds')
    times={t.meaning:json.loads(t.original_json) for t in fpds.freshness.temporal_fields}
    assert times['signed']=='2024-10-01' and times['effective']=='2024-09-30'
    assert fpds.freshness.content_freshness=='unknown'


@pytest.mark.parametrize('change',[{'schema_version':2},{'rule_version':'history-v2'},{'comparisons':[]},{'observations':[]}])
def test_strict_run_rejects_versions_and_omitted_evidence(cases,change):
    data=cases['equal_control'].to_dict();data.update(change)
    with pytest.raises(ValueError): HistoryVerificationRun.from_dict(data)


def test_roundtrip_and_execution_time_separation(cases):
    run=cases['equal_control']
    assert HistoryVerificationRun.from_dict(run.to_dict())==run
    a=replace(run,executed_at_utc='2026-01-01T00:00:00Z');b=replace(run,executed_at_utc='2026-02-01T00:00:00Z')
    assert a.substantive_sha256==b.substantive_sha256
    assert digest(research_report(a))==digest(research_report(b))


def test_forged_comparison_status_delta_and_revision_cannot_upgrade(cases):
    c=cases['equal_revision_unknown'].comparisons[0]
    with pytest.raises(ValueError): replace(c,status=S.AGREEMENT,difference_left_minus_right='0')
    with pytest.raises(ValueError): replace(c.alignment,status=Alignment.SAME)
    c=cases['unequal_control'].comparisons[0]
    with pytest.raises(ValueError): replace(c,difference_left_minus_right='-999')


def test_positive_same_occurrence_and_different_action_rules(cases):
    obs=cases['initial_and_modifications'].observations
    a=obs[0];b=next(b for b in obs if b.action_key!=a.action_key)
    assert alignment(a,a)[0] is Alignment.SAME
    assert alignment(a,b)[0] is Alignment.DIFFERENT_ACTION
    assert compare(a,b).difference_left_minus_right is None


def test_incremental_and_cumulative_are_never_interchangeable(cases):
    run=cases['equal_control'];a=next(o for o in run.observations if o.scope_assessment.evidence.reference.source=='usaspending');b=next(o for o in run.observations if o!=a)
    c=compare(a,b,right_field='totalDollarValues/obligatedAmount')
    assert c.status is S.INCOMPATIBLE and c.difference_left_minus_right is None


def test_decimal_context_independent_exact_difference(cases):
    a,b=cases['unequal_control'].comparisons[0].left,cases['unequal_control'].comparisons[0].right
    with localcontext() as ctx:
        ctx.prec=1
        assert compare(a,b).difference_left_minus_right=='-1'


@pytest.mark.parametrize('raw,parsed',[(None,None),('not-a-date',None),('2024-13-01',None),('2024-10-01','2024-10-01'),
    ('2025-01-01T00:00:00Z','2025-01-01T00:00:00+00:00'),('2025-01-01 12:34:56','2025-01-01T12:34:56')])
def test_temporal_values_preserve_original_and_do_not_invent_zone(raw,parsed):
    t=temporal('source_field','updated',raw)
    assert json.loads(t.original_json)==raw and t.parsed==parsed


@pytest.mark.parametrize('change',[{'content_freshness':'current'},{'reason':'recent_retrieval'}])
def test_unknown_freshness_cannot_be_promoted(change):
    with pytest.raises(ValueError): FreshnessAssessment(retrieved_at_utc='2026-10-28T00:00:00Z',**change)


@pytest.mark.parametrize('field,value',[('historical_completeness',Completeness.COMPLETE),('source_wide_completeness',Completeness.COMPLETE),('authoritative_sequence_rule','incrementing_mod_number')])
def test_coverage_cannot_invent_full_history_or_sequence(cases,field,value):
    with pytest.raises(ValueError): replace(cases['equal_control'].coverage[0],**{field:value})


def test_pagination_terminal_and_partial_do_not_certify_history(cases):
    assert all(c.pagination is Completeness.COMPLETE for c in cases['equal_control'].coverage)
    assert any(c.pagination is Completeness.PARTIAL for c in cases['partial_pagination'].coverage)
    assert all(c.historical_completeness is Completeness.UNKNOWN for c in cases['empty_feed'].coverage)


def test_same_source_known_update_changes_have_no_revision_delta(tmp_path):
    def dated(date):
        def apply(data):
            data['responses'][-1]['text']=data['responses'][-1]['text'].replace('</f:award>',f'<f:transactionInformation><f:lastModifiedDate>{date}</f:lastModifiedDate></f:transactionInformation></f:award>')
        return apply
    p,req,a=make(tmp_path,'equal_revision_unknown',dated('2025-01-01 12:00:00'),name='a')
    q,_,b=make(tmp_path,'equal_revision_unknown',dated('2025-02-01 12:00:00'),name='b')
    run=reconstruct((p,q),req)
    c=next(c for c in run.comparisons if c.left.scope_assessment.evidence.reference.source==c.right.scope_assessment.evidence.reference.source=='fpds')
    assert c.alignment.status is Alignment.DIFFERENT_REVISION and c.difference_left_minus_right is None


def test_same_update_and_close_retrieval_do_not_align_cross_source(cases):
    run=cases['equal_revision_unknown']
    assert run.comparisons[0].alignment.status is Alignment.UNKNOWN
    assert run.comparisons[0].difference_left_minus_right is None


def test_cross_snapshot_contradictions_block_all_control_comparisons(tmp_path):
    p,req,a=make(tmp_path,name='a')
    def change(d):
        d['responses'][0]['json']['results'][0]['federal_action_obligation']=101
        d['responses'][0]['retrieved_at_utc']='2025-02-01T00:00:00Z'
    q,_,b=make(tmp_path,transform=change,name='b')
    run=reconstruct((p,q),req)
    assert any(c.context_conflict for c in run.comparisons)
    assert all(c.difference_left_minus_right is None for c in run.comparisons if c.context_conflict)
    subjects=[o for o in run.observations if o.scope_assessment.evidence.reference.source=='usaspending']
    assert compare(*subjects).status is S.HISTORY_INSUFFICIENT
    assert reconstruct((q,p),req).substantive_sha256==run.substantive_sha256


def test_repeated_content_does_not_lose_retrieval_provenance(tmp_path):
    p,req,_=make(tmp_path,name='a')
    def later(d):
        for r in d['responses']: r['retrieved_at_utc']='2025-02-01T00:00:00Z'
    q,_,_=make(tmp_path,transform=later,name='b')
    run=reconstruct((p,q),req)
    assert len(run.observations)==4 and metrics(run)['duplicate_record_occurrences']==2
    assert not any(c.context_conflict for c in run.comparisons)


def test_missing_transaction_identity_is_preserved_but_not_grouped(tmp_path):
    def change(d): d['responses'][-1]['text']=d['responses'][-1]['text'].replace('<f:transactionNumber>0</f:transactionNumber>','')
    _,_,run=make(tmp_path,transform=change)
    fpds=next(o for o in run.observations if o.scope_assessment.evidence.reference.source=='fpds')
    assert fpds.modification.transaction is None and fpds.action_key is None
    assert not any(c.difference_left_minus_right is not None for c in run.comparisons)


def test_limits_reject_whole_operation(cases,tmp_path):
    with pytest.raises(EvidenceError): compare_observations(cases['equal_control'].observations*501)
    with pytest.raises(EvidenceError): reconstruct(('same','same'),cases['equal_control'].scope.requested)
    with pytest.raises(EvidenceError): reconstruct(('x',)*9,cases['equal_control'].scope.requested)


def test_same_occurrence_cannot_claim_two_temporal_states(cases):
    a=cases['equal_control'].observations[0]
    with pytest.raises(ValueError,match='signed date contradicts'):
        replace(a,freshness=replace(a.freshness,temporal_fields=()))


@pytest.mark.parametrize('first,second',[
    ('2025-01-01T12:00:00Z','2025-01-01T12:00:00+00:00'),
    ('2025-01-01T12:00:00Z','2025-01-01T07:00:00-05:00'),
    ('2025-01-01 12:00:00','2025-01-01T12:00:00Z')])
def test_timestamp_spelling_or_unknown_zone_does_not_invent_distinct_revisions(tmp_path,first,second):
    def dated(value):
        def change(d):
            d['responses'][-1]['text']=d['responses'][-1]['text'].replace('</f:award>',f'<f:transactionInformation><f:lastModifiedDate>{value}</f:lastModifiedDate></f:transactionInformation></f:award>')
        return change
    p,req,_=make(tmp_path,'equal_revision_unknown',dated(first),name='a')
    q,_,_=make(tmp_path,'equal_revision_unknown',dated(second),name='b')
    run=reconstruct((p,q),req)
    assert all(c.alignment.status is not Alignment.DIFFERENT_REVISION for c in run.comparisons if c.alignment)


def test_http_last_modified_is_not_a_record_revision_or_freshness_certificate(tmp_path):
    def change(d): d['responses'][-1]['source_update_raw']='Wed, 01 Jan 2025 12:00:00 GMT'
    _,_,run=make(tmp_path,'equal_revision_unknown',change)
    f=next(o for o in run.observations if o.scope_assessment.evidence.reference.source=='fpds')
    assert any(t.meaning=='http_last_modified' for t in f.freshness.temporal_fields)
    assert not f.revision.update_markers and f.freshness.content_freshness=='unknown'


def test_retrieval_timeline_sorts_instants_not_timestamp_spellings(tmp_path):
    def at(stamp):
        def change(d):
            for r in d['responses']: r['retrieved_at_utc']=stamp
        return change
    p,req,_=make(tmp_path,transform=at('2025-01-01T00:00:00Z'),name='a')
    q,_,_=make(tmp_path,transform=at('2025-01-01T00:00:00.500Z'),name='b')
    run=reconstruct((q,p),req);report=research_report(run)
    usa=[r['observation_id'] for r in report['observed_timeline'] if r['source']=='usaspending']
    lookup={o.history_observation_id:o.freshness.retrieved_at_utc for o in run.observations}
    assert [lookup[i] for i in usa]==['2025-01-01T00:00:00Z','2025-01-01T00:00:00.500Z']
