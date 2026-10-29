from dataclasses import replace
import json
import shutil

import pytest

from src.evidence_io import EvidenceError,digest
from src.readiness import load_protocol,assess,main
from src.readiness_audit import audit_frozen,inventory
from src.readiness_models import (DIMENSIONS,CONTROLS,MODES,Result,Decision,ReadinessAssessment,Measurement,ReadinessProtocol)
from src.readiness_rules import mode_decisions,conclusions,remediation
from src.readiness_reporting import projection,write_readiness,read_readiness,html_report
from readiness_fixtures import frozen


@pytest.fixture(scope='module')
def baseline(tmp_path_factory):
    source=tmp_path_factory.mktemp('readiness')/'pilot'
    protocol,ids=frozen(source)
    result=assess(source,protocol=protocol)
    return source,protocol,ids,result


def test_all_dimensions_categorical_units_and_no_weighted_score(baseline):
    _,_,_,r=baseline
    assert tuple(d.name for d in r.dimensions)==DIMENSIONS
    assert tuple(g.name for g in r.hard_gates)==CONTROLS
    assert tuple(m.mode for m in r.modes)==MODES
    assert all(m.collection_permission is False for m in r.modes)
    assert r.modes[0].result is Decision.GO
    assert all(m.result is Decision.NO_GO for m in r.modes[1:])
    assert next(d for d in r.dimensions if d.name=='source_modernization').result is Result.UNKNOWN


@pytest.mark.parametrize('field,value',[('holdout_award_limit',12),('holdout_http_limit',48),('holdout_frame_limit',100),
    ('holdout_fiscal_year',2024),('version','readiness-protocol-v2'),('dimension_rule','weighted_score'),('hard_gate_rule','average_overrides_failure')])
def test_protocol_cannot_silently_change_preregistered_criteria(field,value):
    with pytest.raises(ValueError): replace(load_protocol(),**{field:value})


def test_live_frozen_cohort_lineage_is_locked():
    with pytest.raises(ValueError): replace(load_protocol(),frozen_sample_sha256='0'*64)


@pytest.mark.parametrize('n,d,complete',[(-1,1,True),(2,1,True),(None,1,True),(True,1,True),(1,False,True)])
def test_invalid_or_fabricated_denominators_rejected(n,d,complete):
    with pytest.raises((ValueError,TypeError)): Measurement(name='scope_verified',numerator=n,denominator=d,unit='enumerated_record_occurrences',complete=complete)


def test_zero_denominator_is_not_100_percent_or_pass(baseline):
    _,_,_,r=baseline
    d=next(d for d in r.dimensions if d.name=='revision_alignment')
    assert d.result is Result.UNKNOWN
    assert d.numerator==0
    assert not any(d.result is Result.NOT_APPLICABLE for d in r.dimensions)


@pytest.mark.parametrize('control',CONTROLS)
def test_non_negotiable_violation_cannot_be_overridden_by_favorable_averages(baseline,control):
    _,_,_,r=baseline
    dims=tuple(replace(d,result=Result.PASS) for d in r.dimensions)
    gates=tuple(replace(g,result=Result.FAIL if g.name==control else Result.PASS) for g in r.hard_gates)
    decisions=mode_decisions(dims,gates,distinct_holdout=True)
    assert all(m.result is Decision.NO_GO for m in decisions)
    assert all('non_negotiable:'+control in m.blockers for m in decisions)


def test_progressively_stronger_modes_do_not_grant_collection(baseline):
    _,_,_,r=baseline
    dims=tuple(replace(d,result=Result.PASS) for d in r.dimensions)
    decisions=mode_decisions(dims,r.hard_gates,distinct_holdout=True)
    assert decisions[0].result is Decision.GO and decisions[1].result is Decision.CONDITIONAL_GO
    assert decisions[2].result is Decision.GO and decisions[3].result is Decision.GO
    assert decisions[4].result is Decision.NO_GO  # No scale/throughput evidence in v1.
    assert not any(m.collection_permission for m in decisions)


def test_reanalysis_reproducible_across_filesystem_paths(baseline,tmp_path):
    source,protocol,_,first=baseline
    copied=tmp_path/'copied';shutil.copytree(source,copied)
    second=assess(copied,protocol=protocol)
    assert first.substantive_sha256==second.substantive_sha256
    assert inventory(source)==inventory(copied)


def test_execution_metadata_does_not_change_substantive_result(baseline):
    _,_,_,r=baseline
    a=replace(r,executed_at_utc='2026-01-01T00:00:00Z');b=replace(r,executed_at_utc='2026-02-01T00:00:00Z')
    assert a.substantive_sha256==b.substantive_sha256 and digest(projection(a))==digest(projection(b))


def test_roundtrip_and_forged_go_rejected(baseline):
    _,_,_,r=baseline
    assert ReadinessAssessment.from_dict(r.to_dict())==r
    data=r.to_dict();data['modes'][-1]['result']='GO'
    with pytest.raises(ValueError): ReadinessAssessment.from_dict(data)
    data=r.to_dict();data['dimensions'][0]['result']='NOT_APPLICABLE'
    with pytest.raises(ValueError): ReadinessAssessment.from_dict(data)


def test_missing_frozen_evidence_not_replaced_with_synthetic_data(tmp_path):
    r=assess(tmp_path/'missing')
    assert not r.cohorts[0].available and r.cohorts[0].selected_count==24
    assert r.cohorts[0].sample_sha256 is None and r.cohorts[0].inventory_sha256 is None
    assert all(s.selected_native_id is None for s in r.cohorts[0].slots)
    assert all(m.result is Decision.NO_GO for m in r.modes)


def test_tampering_is_not_hidden_by_other_good_slots(baseline,tmp_path):
    source,protocol,_,_=baseline;copy=tmp_path/'changed';shutil.copytree(source,copy)
    body=next(copy.glob('award-*/research/evidence/*/c3_attempt_*.body'))
    body.write_bytes(body.read_bytes()+b' changed')
    before=inventory(copy);r=assess(copy,protocol=protocol)
    assert any(g.result is Result.FAIL for g in r.hard_gates)
    assert all(m.result is Decision.NO_GO for m in r.modes)
    assert inventory(copy)==before


def test_cause_subjects_are_not_double_counted_and_backlog_is_engineering_only(baseline):
    _,_,_,r=baseline
    for c in r.cohorts:
        for s in c.slots:
            assert len({(a.unit,a.subject_key) for a in s.causes})==len(s.causes)
    backlog=remediation(r.cohorts)
    assert all(x['affected_selected_slots']<=x['slot_denominator'] for x in backlog)
    assert all(x['feasibility_basis']=='engineering_assumption_not_measured_delivery_estimate' for x in backlog)


def test_safe_reports_and_commit_validation(baseline,tmp_path):
    source,_,_,r=baseline;before=inventory(source);out=tmp_path/'out'
    write_readiness(out,r,protected=(source,))
    assert read_readiness(out)==r and inventory(source)==before
    with pytest.raises(OSError): write_readiness(out,r)
    with pytest.raises(EvidenceError): write_readiness(source/'bad',r,protected=(source,))
    report=projection(r);report['assessment']['dimensions'][0]['rationale']='<script>alert(1)</script>'
    assert '<script>' not in html_report(report) and '&lt;script&gt;' in html_report(report)
    (out/'readiness.md').write_text('tampered')
    with pytest.raises(EvidenceError): read_readiness(out)


def test_historical_baseline_units_are_not_interchangeable(baseline):
    p=projection(baseline[3]);refs=p['baseline_references']
    assert [(r['phase'],r['numerator'],r['denominator']) for r in refs]==[('4A',12,24),('4B1',24,24),('4B2',18,58),('4B3',331,None)]
    assert len({r['unit'] for r in refs})==4
    assert p['modernization']['authenticated_live_verification']=='not_performed'


@pytest.mark.parametrize('args',[[],['--live','--holdout-root','x'],['--live','--execution-time']])
def test_cli_invalid_modes_do_not_collect(tmp_path,args):
    with pytest.raises(SystemExit) if not args else __import__('contextlib').nullcontext():
        result=main(args+(['--root','missing'] if args else [])+['--run-dir',str(tmp_path/'out')])
        assert result==2
    assert not (tmp_path/'out').exists()


@pytest.mark.parametrize('change',[{'schema_version':2},{'schema_version':True},{'version':'other'},{'undocumented_threshold':0.1}])
def test_protocol_readback_rejects_unsupported_or_extra_fields(change):
    doc=load_protocol().to_dict();doc.update(change)
    with pytest.raises(ValueError): ReadinessProtocol.from_dict(doc)


def test_measurement_units_and_partition_cannot_be_relabelled(baseline):
    with pytest.raises(ValueError): Measurement(name='scope_verified',numerator=1,denominator=1,unit='selected_slots')
    slot=baseline[3].cohorts[0].slots[0]
    with pytest.raises(ValueError): replace(slot,measurements=tuple(m for m in slot.measurements if m.name!='scope_out'))


def test_historical_external_descriptors_are_relocated_without_reading_old_paths(baseline,tmp_path):
    source,protocol,_,_=baseline;local=tmp_path/'original';shutil.copytree(source,local)
    folder=local/'award-000';plan_path=folder/'research/research-plan.json';plan=json.loads(plan_path.read_text())
    descriptor=plan['sources'][0];body=folder/'research'/descriptor['path']
    discovery=folder/'discovery';shutil.copytree(body,discovery)
    descriptor.update(managed=False,path=str(discovery));plan_path.write_text(json.dumps(plan))
    moved=tmp_path/'relocated';shutil.copytree(local,moved)
    first=assess(local,protocol=protocol);shutil.rmtree(local)
    second=assess(moved,protocol=protocol)
    assert first.substantive_sha256==second.substantive_sha256
