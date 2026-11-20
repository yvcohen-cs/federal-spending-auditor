"""Authored synthetic transcripts; no primary source or historical authority claims."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import pytest
from src.dependency_resolution import plan,collect,replay
from src.source_verification import VerificationExperiment,DependencyVerificationExperiment,decode_experiment,inspect_experiment
from src.evidence_io import canonical
from tests.test_historical_source_authority import original_case
from tests.test_historical_authority_reporting import transcript

@pytest.fixture
def sample(tmp_path):
 c,a,d=original_case(tmp_path/'original',suffix='C21');c.update(c21_parent_capture=str(tmp_path/'child'),c21_parent_history=str(tmp_path/'parent'))
 return c,transcript(a,d),tmp_path

def run(sample,change=None):
 c,t,p=sample;t=deepcopy(t)
 if change:change(t)
 return collect(p/'journal',c,synthetic=t)

def test_explicit_C21_schema_does_not_relax_legacy_limit(sample):
 c,_,_=sample;p=plan(c);value=p['experiment'];ex=decode_experiment(value)
 assert isinstance(ex,DependencyVerificationExperiment) and ex.spec.limits.max_pages==4
 assert decode_experiment(value).to_dict()==value and p['maximum_requests']==8
 with pytest.raises(ValueError):VerificationExperiment.from_dict({**value,'schema_type':'VerificationExperiment'})

def test_actual_fixture_qualification_unchanged_and_no_financial_promotion(sample):
 r=run(sample);assert len(r['resolved_original_impacts'])==1
 assert not r['financial_comparison_authorized'] and not r['historical_applicability_established']
 assert r['financial_preflight']['amount_comparisons_performed']==0
 assert r['source']['transaction_contract']['histories'][0]['history_complete']=='unknown'
 assert all(c['representation']=='synthetic_transcript_bytes' for c in r['source']['citations'])

@pytest.mark.parametrize('stage,status',[('child',401),('child',403),('child',429),('child',503),('parent',403),('parent',500)])
def test_source_access_failure_never_absence_or_resolution(sample,stage,status):
 def change(t):
  if stage=='child':t['child']['details'][0]['status']=status
  else:t['parent']['responses'][0]['status']=status
 r=run(sample,change);assert not r['resolved_original_impacts'] and not r['financial_comparison_authorized']

@pytest.mark.parametrize('field,bad',[('piid','WRONG'),('sub_agency_id','0000'),('generated_unique_award_id','../parent')])
def test_wrong_native_parent_rejected(sample,field,bad):
 r=run(sample,lambda t:t['child']['details'][0]['json']['parent_award'].__setitem__(field,bad));assert not r['resolved_original_impacts']

@pytest.mark.parametrize('member',['detail-000.json','detail-001.body','experiment-commit.json'])
def test_truncated_or_changed_primary_capture_rejected(sample,member):
 run(sample);c,_,_=sample;(Path(c['c21_parent_capture'])/member).unlink()
 with pytest.raises(ValueError):replay(c)

def test_child_nonterminal_at_maximum_budget_stops_parent(sample):
 def change(t):
  t['child']['transactions']['responses'][0]['json']['page_metadata'].update(hasNext=True,next=2)
  t['child']['transactions']['responses'].append({'source':'usaspending','status':503,'json':{}})
 r=run(sample,change);assert not r['resolved_original_impacts'] and not Path(sample[0]['c21_parent_history']).exists()

def test_no_implicit_live_or_synthetic_live_confusion(sample):
 c,t,p=sample
 with pytest.raises(ValueError):collect(p/'journal',c)
 with pytest.raises(ValueError):collect(p/'journal',c,live=True,synthetic=t)

def test_changed_experiment_schema_cannot_claim_legacy_contract(sample):
 r=run(sample);value=r['source']['experiment'];value['schema_type']='VerificationExperiment'
 with pytest.raises(ValueError):decode_experiment(value)

@pytest.mark.parametrize('key',['new_parent_capture','action_parent_capture','c19_parent_capture','c20_parent_capture'])
def test_prior_capture_rebinding_rejected(sample,key):
 c,_,_=sample
 with pytest.raises(ValueError):plan({**c,key:'old-primary'})

@pytest.mark.parametrize('terminal',[True,False])
def test_four_page_contract_terminal_and_budget_stop(sample,terminal):
 def change(t):
  first=deepcopy(t['child']['transactions']['responses'][0]);rows=first['json']['results'];responses=[]
  for i in range(4):
   r=deepcopy(first);row=deepcopy(rows[0]);old=row['modification_number'];row['id']=row['id'].replace('_'+old+'_','_'+str(i)+'_');row['modification_number']=str(i);row['action_date']='2020-01-0'+str(i+1)
   r['json']['results']=[row];r['json']['page_metadata']={'page':i+1,'previous':i if i else None,'hasPrevious':i>0,'hasNext':i<3 or not terminal,'next':i+2 if i<3 or not terminal else None};responses.append(r)
  t['child']['transactions']['responses']=responses
 r=run(sample,change)
 assert r['source']['request_attempts']==6
 assert bool(r['resolved_original_impacts']) is terminal
 assert (r['parent'] is not None) is terminal
 assert not r['source']['history_complete']=='complete' and not r['financial_comparison_authorized']

@pytest.mark.parametrize('field,bad',[('schema_version',2),('schema_version',True),('mode','unrestricted_live'),('MAX_PAGES',100)])
def test_unsupported_experiment_schema_or_budget_override_rejected(sample,field,bad):
 value=plan(sample[0])['experiment'];value[field]=bad
 with pytest.raises(ValueError):decode_experiment(value)

def test_false_financial_eligibility_rejected(sample,monkeypatch):
 run(sample)
 monkeypatch.setattr('src.dependency_resolution.monetary_preflight',lambda *_a,**_k:{'totals_or_deltas_computed':0,'amount_comparisons_performed':0,'financial_comparison_authorized':True})
 with pytest.raises(ValueError,match='financial_assessment'):replay(sample[0])

def test_interrupted_journal_does_not_replay_or_overwrite_source(sample):
 c,_,p=sample
 (p/'child').mkdir();(p/'child/pilot-plan.json').write_text('{}')
 with pytest.raises(ValueError):replay(c)
 assert (p/'child/pilot-plan.json').read_text()=='{}'
