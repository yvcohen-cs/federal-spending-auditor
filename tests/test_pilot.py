"""Deterministic offline Phase 4A controls; no real contract ground truth."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from src.evidence_io import EvidenceError, canonical, digest, strict_json
from src.pilot_evaluation import evaluate, rate, reasons
from src.pilot_pipeline import (bridge_selection, collect_frame, main, run_pilot,
                                synthetic_rows)
from src.pilot_sampling import PilotConfig, amount_band, frame_requests, select_sample
from src.pilot_store import PilotStore
from src.research_models import implementation_digest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session,"request",Mock(side_effect=AssertionError("network forbidden")))


def config(mode="synthetic",**kwargs):
    return PilotConfig(mode=mode,implementation_sha256=implementation_digest(),**kwargs)


def test_sampling_order_independent_and_bias_explicit():
    c=config()
    rows=synthetic_rows()
    a=select_sample(rows,c)
    b=select_sample(rows[::-1],c)
    assert a==b and len(a["selected"])==6 and a["target"]==24
    assert a["population_total"] is None
    assert "not statistically representative" in " ".join(a["limitations"])
    assert len({r["agency"] for r in a["selected"]})==3
    assert all(r["frame_refs"] and r["stratum"] for r in a["selected"])


def test_seeded_ranking_is_repeatable_and_used_within_strata():
    row=synthetic_rows()[0]
    rows=[{**row,"generated_id":f"00-{i}","source_row":{"id":f"00-{i}"}} for i in range(30)]
    a=select_sample(rows,config(target=10))
    assert len(a["selected"])==10
    assert a==select_sample(rows,config(target=10))
    assert a["selected"]!=select_sample(rows,config(target=10,seed="other"))["selected"]


def test_duplicate_and_conflicting_frame_ids_not_silently_resolved():
    r=synthetic_rows()[0]
    duplicate={**r,"frame_ref":"another-ref"}
    a=select_sample([r,duplicate],config())
    assert len(a["selected"])==1 and len(a["selected"][0]["frame_refs"])==2
    conflict={**r,"source_row":{"changed":True}}
    a=select_sample([r,conflict,{**r,"generated_id":123}],config())
    assert not a["selected"]
    assert a["exclusions"]["conflicting_generated_identifier"]==2
    assert a["exclusions"]["missing_identifier_or_provenance"]==1


@pytest.mark.parametrize("raw,band",[(None,"unknown"),(True,"unknown"),("NaN","unknown"),(-1,"negative"),(0,"under_100k"),("100000","100k_to_1m"),(1000000,"1m_plus")])
def test_amount_bands_no_float_financial_inference(raw,band):
    assert amount_band(raw)==band


@pytest.mark.parametrize("count,total",[(0,0),(0,2),(1,3),(3,3)])
def test_rates_show_counts_and_null_zero_denominator(count,total):
    r=rate(count,total)
    assert r["count"]==count and r["denominator"]==total
    assert (r["percent"] is None)==(total==0)


@pytest.mark.parametrize("count,total",[(-1,2),(3,2),(True,2),(1,False)])
def test_rates_reject_invented_denominators(count,total):
    with pytest.raises(ValueError):
        rate(count,total)


@pytest.mark.parametrize("change",[{"target":31},{"target":0},{"target":True},{"mode":"auto"},{"frame_limit":11},{"seed":""},{"version":"pilot-v2"}])
def test_config_caps_and_explicit_versions(change):
    values={"mode":"synthetic","implementation_sha256":implementation_digest(),**change}
    with pytest.raises((ValueError,TypeError)):
        PilotConfig(**values)


def frame_plan(c):
    return {"config":c.to_dict()}


def response(status=200,rows=None,timestamp="2025-01-01T00:00:00Z"):
    return {"status":status,"retrieved_at_utc":timestamp,"body_complete":True,"error_code":None},canonical({"results":rows or [],"page_metadata":{"hasNext":False}}).encode()


def test_blocked_frame_stops_without_scraping_or_synthetic_fallback(tmp_path):
    c=config("live")
    transport=Mock(return_value=response(403))
    with PilotStore(tmp_path/"run",frame_plan(c)) as s:
        rows,status=collect_frame(s,c,transport=transport,sleep=lambda _:None)
    assert not rows and status["reserved_queries"]==1 and status["successful_queries"]==0
    assert transport.call_count==1
    with PilotStore(tmp_path/"run",frame_plan(c),True) as s:
        assert collect_frame(s,c,transport=Mock(side_effect=AssertionError("no replay")),sleep=lambda _:None)==(rows,status)


def test_uncertain_reserved_frame_request_is_not_replayed(tmp_path):
    c=config("live")
    with PilotStore(tmp_path/"run",frame_plan(c)) as s:
        s.write("frame-000.request.json",frame_requests(c)[0])
    with PilotStore(tmp_path/"run",frame_plan(c),True) as s:
        rows,status=collect_frame(s,c,transport=Mock(side_effect=AssertionError("no replay")),sleep=lambda _:None)
    assert not rows and status["observations"][0]["error_code"]=="uncertain_reserved_request"


def test_partial_frame_api_access_preserves_available_subset(tmp_path):
    c=config("live")
    row={"generated_internal_id":"00.AWARD/1","Awarding Agency":"Agency","Award Amount":"100"}
    transport=Mock(side_effect=[response(rows=[row]),response(503),response(403)])
    with PilotStore(tmp_path/"run",frame_plan(c)) as s:
        rows,status=collect_frame(s,c,transport=transport,sleep=lambda _:None)
    assert len(rows)==1 and rows[0]["generated_id"]=="00.AWARD/1"
    assert rows[0]["modifications"]=="unknown"
    assert status["successful_queries"]==1 and status["reserved_queries"]==3


@pytest.mark.parametrize("timestamp",[None,"yesterday","2025-01-01"])
def test_frame_missing_provenance_never_eligible(tmp_path,timestamp):
    c=config("live")
    with PilotStore(tmp_path/"run",frame_plan(c)) as s:
        rows,status=collect_frame(s,c,transport=Mock(return_value=response(rows=[{"generated_internal_id":"0001"}],timestamp=timestamp)),sleep=lambda _:None)
    assert not rows and status["successful_queries"]==0
    assert all(o["error_code"]=="missing_or_invalid_frame_provenance" for o in status["observations"])


def test_frame_bytes_tamper_and_symlink_rejected(tmp_path):
    c=config("live")
    p=tmp_path/"run"
    with PilotStore(p,frame_plan(c)) as s:
        collect_frame(s,c,transport=Mock(return_value=response(403)),sleep=lambda _:None)
    (p/"frame-000.body").write_bytes(b"changed")
    with PilotStore(p,frame_plan(c),True) as s:
        with pytest.raises(EvidenceError,match="hash_conflict"):
            collect_frame(s,c,transport=Mock(),sleep=lambda _:None)
    link=tmp_path/"link"
    link.symlink_to(p,target_is_directory=True)
    with pytest.raises((OSError,ValueError)):
        with PilotStore(link,frame_plan(c),True):
            pass


def test_research_lanes_do_not_escalate_deobligation_zero_or_value():
    identity=SimpleNamespace(decisions=[])
    finance=SimpleNamespace(results=[SimpleNamespace(difference_usa_minus_fpds="0",status=SimpleNamespace(value="verified_match"))])
    assert all(r["lane"]!="financial_question" for r in reasons(identity,finance))
    finance.results[0].difference_usa_minus_fpds="1"
    assert {r["code"] for r in reasons(identity,finance)}=={"unequal_compatible_saved_values","history_and_freshness_unknown"}


@pytest.fixture(scope="module")
def full_pilot(tmp_path_factory):
    p=tmp_path_factory.mktemp("pilot")
    a,code=run_pilot(p/"a",config())
    b,other=run_pilot(p/"b",config())
    return p,a,b,code,other


def test_full_controls_deterministic_and_false_positive_behavior(full_pilot):
    p,a,b,code,other=full_pilot
    assert code==other==1 and digest(a)==digest(b)
    assert a["mode"]=="synthetic" and a["evaluation"]["packets_generated"]==24
    assert a["evaluation"]["rates"]["unequal_comparable_observations"]["count"]==1
    assert a["evaluation"]["rates"]["unknown_source_freshness"]["count"]==6
    assert a["evaluation"]["resources"]["live_request_slots_reserved"]==0
    assert len(a["audit_candidates"])==3
    mod=next(c for c in a["cases"] if "MODIFICATIONS" in c["generated_id"])
    assert mod["counts"]["finance"]["verified_match"]==3
    assert all(r["lane"]!="financial_question" for r in mod["reasons"])
    scope=next(c for c in a["cases"] if "SCOPE-MISMATCH" in c["generated_id"])
    assert scope["metrics"]["numeric_comparisons"]==0
    ambiguous=next(c for c in a["cases"] if "AMBIGUOUS" in c["generated_id"])
    assert any(r["code"]=="ambiguous_native_identity" for r in ambiguous["reasons"])
    duplicate=next(c for c in a["cases"] if "DUPLICATES" in c["generated_id"])
    assert duplicate["metrics"]["row_occurrences"]>duplicate["metrics"]["distinct_record_contents"]
    assert a["evaluation"]["rates"]["row_provenance_sufficient"]["denominator"]>0
    assert a["evaluation"]["rates"]["evidence_integrity_verified_entries"]["percent"]!="100.00"
    for c in a["cases"]:
        assert all((p/"a"/ref).is_file() for ref in c["packet_refs"])


def test_resume_revalidates_without_duplicate_collection(full_pilot):
    p,a,_,_,_=full_pilot
    again,code=run_pilot(p/"a",config(),resume=True)
    assert code==1 and digest(again)==digest(a)


def test_bridge_uses_only_supported_transaction_components(full_pilot):
    p,a,_,_,_=full_pilot
    c=next(c for c in a["cases"] if "AGREEMENT" in c["generated_id"])
    source=p/"a"/f"award-{c['slot']:03d}/research/evidence/agreement"
    award,sha,refs=bridge_selection(source,c["generated_id"])
    assert award.piid=="SYNTH-C7-AGREEMENT" and award.agency_id=="0001" and refs
    assert len(sha)==64


def test_no_cases_reports_undefined_rates_not_success(tmp_path):
    report,code=run_pilot(tmp_path/"blocked",config("live"),frame_transport=Mock(return_value=response(403)),sleep=lambda _:None)
    assert code==2 and report["evaluation"]["selected_awards"]==0
    assert report["evaluation"]["rates"]["award_identity_match"]["percent"] is None
    assert report["recommendations"][0].startswith("Validate official source availability")


def test_partial_processing_failure_not_hidden(tmp_path,monkeypatch):
    import src.pilot_pipeline as module
    monkeypatch.setattr(module,"execute_case",Mock(side_effect=EvidenceError("test_failure")))
    report,code=run_pilot(tmp_path/"failed",config(target=2))
    assert code==2 and report["evaluation"]["processing_failures"]==2
    assert report["evaluation"]["missing_processing_results"]==2
    assert report["evaluation"]["rates"]["source_retrieval_success"]==rate(0,4)
    assert report["evaluation"]["rates"]["exact_observed_agreement"]==rate(0,0)


def test_cli_requires_explicit_mode_and_honors_limits(tmp_path,capsys):
    with pytest.raises(SystemExit):
        main(["--run-dir",str(tmp_path/"none")])
    assert main(["--synthetic","--target","31","--run-dir",str(tmp_path/"bad")])==2
    assert not (tmp_path/"bad").exists()
    assert main(["--synthetic","--retry-failed","--run-dir",str(tmp_path/"bad")])==2


def test_config_change_and_unexpected_files_rejected(full_pilot,tmp_path):
    p,_,_,_,_=full_pilot
    with pytest.raises(EvidenceError,match="incompatible_pilot_plan"):
        run_pilot(p/"a",config(seed="changed"),resume=True)
    with PilotStore(tmp_path/"extra",{"config":config().to_dict(),"requests":[],"schema_type":"PilotPlan","schema_version":1,
            "protocol":"docs/pilot-validation.md#predeclared-selection-and-measurement"}) as s:
        s.write("unexpected.json",{})
    with pytest.raises(EvidenceError,match="unexpected_pilot_artifact"):
        run_pilot(tmp_path/"extra",config(),resume=True)


def test_saved_evaluation_is_readonly_and_deterministic(full_pilot,tmp_path):
    from src.evaluate_pilot import evaluate_saved
    p,a,_,_,_=full_pilot
    before={f.relative_to(p/"a").as_posix():f.read_bytes() for f in (p/"a").rglob("*") if f.is_file()}
    report,code=evaluate_saved(p/"a",tmp_path/"evaluation")
    assert code==1 and report==a
    assert before=={f.relative_to(p/"a").as_posix():f.read_bytes() for f in (p/"a").rglob("*") if f.is_file()}
    assert strict_json((tmp_path/"evaluation/pilot-report-000.json").read_bytes())["substantive_sha256"]==digest(report)


def test_failed_parsing_stays_in_integrity_and_availability_denominators(tmp_path,monkeypatch):
    import src.research_pipeline as research
    from src.research_demo import demo_case
    def unsupported(name):
        award,scenario=demo_case(name)
        scenario["responses"][-1]["text"]=scenario["responses"][-1]["text"].replace("</feed>",
            '<link rel="next" href="https://www.fpds.gov/ezsearch/FEEDS/ATOM?VERSION=1.5&amp;start=10"/></feed>')
        return award,scenario
    monkeypatch.setattr(research,"demo_case",unsupported)
    report,code=run_pilot(tmp_path/"unsupported",config(target=1))
    assert code==2
    m=report["evaluation"]
    assert m["evaluated_award_slots"]==1 and m["processing_failures"]==1
    assert m["rates"]["source_http_response_success"]==rate(2,2)
    assert m["rates"]["source_retrieval_success"]==rate(1,2)
    assert m["rates"]["evidence_integrity_verified_entries"]["count"]<m["rates"]["evidence_integrity_verified_entries"]["denominator"]
    assert m["rates"]["exact_observed_agreement"]==rate(0,0)
    assert report["cases"][0]["evidence_exclusions"][0]["error_code"]=="unsupported_fpds_next_parameters"
    assert "FPDS VERSION" in report["recommendations"][0]


def test_unavailable_fpds_preserves_usa_and_does_not_escalate_money(tmp_path,monkeypatch):
    import src.research_pipeline as research
    from src.research_demo import demo_case
    def unavailable(name):
        award,scenario=demo_case(name)
        scenario["responses"][-1]["status"]=404
        return award,scenario
    monkeypatch.setattr(research,"demo_case",unavailable)
    report,code=run_pilot(tmp_path/"unavailable",config(target=1))
    assert code==1
    assert report["evaluation"]["rates"]["source_http_response_success"]==rate(1,2)
    assert report["evaluation"]["rates"]["source_retrieval_success"]==rate(1,2)
    assert report["evaluation"]["rates"]["financial_numeric_comparability"]==rate(0,1)
    assert all(r["lane"]!="financial_question" for r in report["cases"][0]["reasons"])


def test_mid_pilot_interrupt_and_retry_keeps_prior_award_and_starts_new_ones(tmp_path,monkeypatch):
    import src.pilot_pipeline as module
    original=module.execute_case
    once=True
    def interrupt(store,c,index,*args,**kwargs):
        nonlocal once
        if index==1 and once:
            once=False
            raise KeyboardInterrupt
        return original(store,c,index,*args,**kwargs)
    monkeypatch.setattr(module,"execute_case",interrupt)
    p=tmp_path/"interrupted"
    with pytest.raises(KeyboardInterrupt):
        run_pilot(p,config(target=2))
    before={f.relative_to(p).as_posix():f.read_bytes() for f in p.rglob("*") if f.is_file()}
    report,code=run_pilot(p,config(target=2),resume=True,retry_failed=True)
    assert code==1 and report["evaluation"]["rates"]["technical_completion"]==rate(2,2)
    assert all((p/f).read_bytes()==raw for f,raw in before.items())


def test_saved_evaluation_rejects_stale_stage_output_without_using_it(full_pilot,tmp_path):
    from src.evaluate_pilot import evaluate_saved
    p,a,_,_,_=full_pilot
    file=next((p/"a/award-000/research/artifacts/finance/attempt-000").rglob("finance.json"))
    original=file.read_bytes()
    try:
        file.write_bytes(original+b" ")
        report,code=evaluate_saved(p/"a",tmp_path/"stale")
        assert code==2 and report["evaluation"]["processing_failures"]==1
        assert report["cases"][0]["metrics"] is None
    finally:
        file.write_bytes(original)


def test_ordinary_modification_amounts_remain_separate_actions(full_pilot):
    p,a,_,_,_=full_pilot
    c=next(c for c in a["cases"] if "MODIFICATIONS" in c["generated_id"])
    file=next((p/"a"/f"award-{c['slot']:03d}/research/artifacts/finance/attempt-000").rglob("finance.json"))
    d=strict_json(file.read_bytes())
    assert {r["left_normalized"] for r in d["results"]}=={"100","-20","0"}
    assert all(r["difference_usa_minus_fpds"]=="0" for r in d["results"])


def test_no_unsupported_probabilities_or_real_world_ground_truth(full_pilot):
    _,a,_,_,_=full_pilot
    for c in a["cases"]:
        assert not {"fraud_score","fraud_probability","confirmed_fraud","confirmed_nonfraud","risk_score"} & set(c)
        assert {r["lane"] for r in c["reasons"]}<={"financial_question","identity_clarification","coverage_data_quality"}
    assert a["human_interpretation"].startswith("not supplied")


def test_pilot_storage_size_cap_preserves_existing_bytes(tmp_path):
    c=config(max_run_bytes=1024)
    with PilotStore(tmp_path/"small",frame_plan(c)) as store:
        before=store.read("pilot-plan.json")
        with pytest.raises(EvidenceError,match="size_limit"):
            store.write_bytes("large.json",b"x"*1024)
        assert store.read("pilot-plan.json")==before


def test_nested_research_and_pilot_outputs_refused(full_pilot):
    p,_,_,_,_=full_pilot
    with pytest.raises(EvidenceError,match="pilot_inside_managed_run"):
        run_pilot(p/"a/nested",config())


def test_readonly_evaluation_never_completes_unsent_frame_requests(tmp_path):
    from src.evaluate_pilot import evaluate_saved
    c=config("live")
    p=tmp_path/"uncertain"
    plan={"schema_type":"PilotPlan","schema_version":1,"config":c.to_dict(),"requests":frame_requests(c),
          "protocol":"docs/pilot-validation.md#predeclared-selection-and-measurement"}
    with PilotStore(p,plan) as store:
        store.write("sample.json",select_sample([],c))
    before={f.name:f.read_bytes() for f in p.iterdir()}
    report,code=evaluate_saved(p,tmp_path/"empty-evaluation")
    assert code==2 and report["evaluation"]["frame_status"]["reserved_queries"]==0
    assert before=={f.name:f.read_bytes() for f in p.iterdir()}


@pytest.mark.parametrize("change",[{"schema_version":2},{"schema_version":True},{"schema_type":"UnrecognizedPlan"}])
def test_saved_evaluation_rejects_unsupported_plan_envelope(tmp_path,change):
    from src.evaluate_pilot import evaluate_saved
    c=config("live")
    p=tmp_path/"unsupported-plan"
    plan={"schema_type":"PilotPlan","schema_version":1,"config":c.to_dict(),"requests":frame_requests(c),
          "protocol":"docs/pilot-validation.md#predeclared-selection-and-measurement",**change}
    with PilotStore(p,plan) as s:
        s.write("sample.json",select_sample([],c))
    with pytest.raises(EvidenceError,match="unsupported_pilot_plan"):
        evaluate_saved(p,tmp_path/"output")
    assert not (tmp_path/"output").exists()
