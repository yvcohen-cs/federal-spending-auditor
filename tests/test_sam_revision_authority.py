"""C18 offline SAM fixtures, never authenticated federal observations."""
from copy import deepcopy
from dataclasses import replace
import pytest
from src.sam_revision_authority import assess
from src.sam_validation import synthetic_row
from src.evidence_io import canonical
from tests.test_sam_validation import parse


def records(rows):return parse({'awardSummary':rows,'totalRecords':len(rows),'limit':2,'offset':0}).records


def old_id(**changes):
    v=deepcopy(synthetic_row()['contractId']);v.update(changes);return v


def test_explicit_prior_identifier_is_not_a_correction_or_verified_alias():
    row=synthetic_row();row['contractId']['referencedIDVModificationNumber']='0'
    row['oldContractId']=[old_id(piid='SYNTH-OLD-00001')]
    r=assess(records([row]),profile='synthetic');o=r['observations'][0]
    assert o['native_identity_supported'] and o['parent_modification_reference_observed']
    assert o['old_identifier_observations'][0]['status']=='DISTINCT_NATIVE_IDENTIFIER_CONTEXT_CANDIDATE'
    assert not o['old_identifier_observations'][0]['verified_identity_alias']
    assert not r['authoritative_correction_edges'] and not r['historical_parent_applicability_intervals']
    assert not r['financial_comparison_authorized'] and o['evidence_class']=='SYNTHETIC_FIXTURE'


@pytest.mark.parametrize('value',[None,{},'old',1,True])
def test_unsupported_old_identifier_shapes_remain_explicit(value):
    row=synthetic_row();row['oldContractId']=value
    o=assess(records([row]),profile='synthetic')['observations'][0]
    assert o['old_contract_id_presence'] in ('NULL','UNSUPPORTED_SHAPE')
    assert not o['verified_identifier_aliases'] and not o['directed_correction_edges']


@pytest.mark.parametrize('entry',[None,'PIID',1,True,[]])
def test_malformed_array_entries_do_not_become_identifiers(entry):
    row=synthetic_row();row['oldContractId']=[entry]
    o=assess(records([row]),profile='synthetic')['observations'][0]
    assert o['old_identifier_observations'][0]['status']=='UNSUPPORTED_ENTRY'


@pytest.mark.parametrize('field',['piid','subtier','referencedIDVPiid','referencedIDVSubtier','modificationNumber','transactionNumber'])
def test_missing_native_prior_components_are_not_imputed(field):
    entry=old_id();entry.pop(field)
    row=synthetic_row();row['oldContractId']=[entry]
    o=assess(records([row]),profile='synthetic')['observations'][0]
    assert o['old_identifier_observations'][0]['status']=='INSUFFICIENT_NATIVE_COMPONENTS'


@pytest.mark.parametrize('bad',[0,False,None,'-NONE-'])
def test_native_agency_is_not_coerced_or_aliased(bad):
    row=synthetic_row();row['oldContractId']=[old_id(subtier={'code':bad})]
    o=assess(records([row]),profile='synthetic')['observations'][0]
    assert o['old_identifier_observations'][0]['status']=='INSUFFICIENT_NATIVE_COMPONENTS'


def test_leading_zeros_and_punctuation_preserved_in_old_identifiers():
    row=synthetic_row();row['oldContractId']=[old_id(piid='00001.A-B',subtier={'code':'0001'})]
    o=assess(records([row]),profile='synthetic')['observations'][0]['old_identifier_observations'][0]
    assert o['native_context']['piid']['value']=='00001.A-B'
    assert o['native_context']['agency']['value']=='0001'


def test_multiple_prior_contexts_are_ambiguous_without_a_winner():
    row=synthetic_row();row['oldContractId']=[old_id(piid='SYNTH-OLD-01'),old_id(piid='SYNTH-OLD-02')]
    r=assess(records([row]),profile='synthetic')
    assert r['observations'][0]['multiple_prior_contexts_require_disambiguation']
    assert not r['authoritative_correction_edges']


def test_same_identifier_context_does_not_establish_revision():
    row=synthetic_row();row['oldContractId']=[old_id()]
    o=assess(records([row]),profile='synthetic')['observations'][0]
    assert o['old_identifier_observations'][0]['status']=='SAME_NATIVE_CONTEXT_NOT_REVISION'


def test_repeated_and_competing_rows_preserved_without_independent_corroboration():
    a=synthetic_row();b=deepcopy(a);b['oldContractId']=[old_id(piid='SYNTH-OLD')]
    r=assess(records([a,b]),profile='synthetic')
    assert r['observed_record_occurrences']==2 and r['repeated_or_competing_observations'][0]['status']=='CONFLICTING_OR_VARIANT_SOURCE_CONTENT'
    assert r['repeated_or_competing_observations'][0]['selected_winner'] is None
    rr=assess(records([a,a]),profile='synthetic')
    assert rr['repeated_or_competing_observations'][0]['status']=='REPEATED_SOURCE_OBSERVATION'
    assert not rr['repeated_or_competing_observations'][0]['independent_corroboration']


def test_reused_modification_with_distinct_transactions_not_collapsed():
    a=synthetic_row();b=deepcopy(a);b['contractId']['transactionNumber']='1'
    r=assess(records([a,b]),profile='synthetic')
    assert r['reused_modification_label_contexts'][0]['native_transaction_values']==['0','1']
    assert not r['authoritative_correction_edges'] and len(r['observations'])==2


@pytest.mark.parametrize('field,value',[('version','999'),('lastModifiedDate','2099-01-01T00:00:00Z'),('status',{'code':'FINAL'})])
def test_versions_dates_and_status_do_not_supply_direction(field,value):
    row=synthetic_row();row['awardDetails']['transactionData'][field]=value;row['oldContractId']=[old_id(piid='SYNTH-OLD')]
    r=assess(records([row]),profile='synthetic')
    assert not r['authoritative_correction_edges'] and not r['historical_parent_applicability_intervals']


@pytest.mark.parametrize('mod',['0','00','P00001','WRONG',None,0])
def test_parent_reference_is_literal_and_never_an_effective_rule(mod):
    row=synthetic_row();row['contractId']['referencedIDVModificationNumber']=mod
    r=assess(records([row]),profile='synthetic')
    assert not r['observations'][0]['historical_applicability_established']
    assert not r['financial_comparison_authorized']


def test_live_profile_cannot_be_applied_to_synthetic_primary():
    with pytest.raises(ValueError):assess(records([synthetic_row()]),profile='live')


def test_oversized_prior_list_and_untyped_records_rejected():
    row=synthetic_row();row['oldContractId']=[old_id()]*21
    with pytest.raises(ValueError):assess(records([row]),profile='synthetic')
    with pytest.raises(ValueError):assess([{}],profile='synthetic')
    with pytest.raises(ValueError):assess([],profile='production')


def test_unsupported_record_schema_never_has_supported_identity():
    row=synthetic_row();row['coreData']['coreVersionId']='999'
    o=assess(records([row]),profile='synthetic')['observations'][0]
    assert not o['native_identity_supported'] and not o['parent_modification_reference_observed']


@pytest.mark.parametrize('mod,expected_status',[('0','CONSISTENT_LITERAL_REFERENCE_NOT_APPLICABILITY'),
    ('00','CONFLICTING_SOURCE_REFERENCE_NOT_CORRECTION'),('P00001','CONFLICTING_SOURCE_REFERENCE_NOT_CORRECTION'),
    ('WRONG','CONFLICTING_SOURCE_REFERENCE_NOT_CORRECTION'),(None,'UNKNOWN_REFERENCE'),(0,'UNKNOWN_REFERENCE')])
def test_literal_reference_disagreement_cannot_create_authority(mod,expected_status):
    from src.sam_revision_authority import compare_reference
    row=synthetic_row();row['contractId']['referencedIDVModificationNumber']=mod
    value=assess(records([row]),profile='synthetic')
    original=canonical(value);expected={k:c['value'] for k,c in value['observations'][0]['current_native_context'].items()}
    compared=compare_reference(value,expected,['0'])
    assert compared['observations'][0]['preserved_FPDS_reference_comparison']==expected_status
    assert not compared['historical_parent_applicability_intervals'] and not compared['authoritative_correction_edges']
    assert canonical(value)==original


def test_wrong_native_context_and_forged_authority_flags_rejected():
    from src.sam_revision_authority import compare_reference
    value=assess(records([synthetic_row()]),profile='synthetic')
    expected={k:c['value'] for k,c in value['observations'][0]['current_native_context'].items()}
    with pytest.raises(ValueError):compare_reference(value,{**expected,'agency':'9999'},['0'])
    forged=deepcopy(value);forged['financial_comparison_authorized']=True
    with pytest.raises(ValueError):compare_reference(forged,expected,['0'])
