"""Frozen-sample recovery controls: authored old-validator observations only."""
from unittest.mock import Mock
from urllib.parse import urlencode
from xml.sax.saxutils import escape

import pytest
import requests

from src.collection_sources import FPDS, request_for
from src.evidence_io import EvidenceError, canonical, digest, strict_json
from src.pilot_pipeline import run_pilot
from src.pilot_sampling import PilotConfig
from src.recover_pilot import recover
from src.research_demo import demo_case
from src.research_models import implementation_digest


def files(path):
    return {p.relative_to(path).as_posix():p.read_bytes() for p in path.rglob("*") if p.is_file()}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session,"request",Mock(side_effect=AssertionError("offline recovery only")))


@pytest.fixture
def legacy(tmp_path,monkeypatch):
    import src.collection as collection
    import src.collection_sources as sources
    import src.research_pipeline as research
    old_make,real_safe=collection.make_plan,sources.safe_next
    def make_legacy(*args,**kwargs):
        kwargs.setdefault("collector_version",2)
        return old_make(*args,**kwargs)
    def old_safe(href,request):
        if "VERSION=" in href:
            raise EvidenceError("unsupported_fpds_next_parameters")
        return real_safe(href,request)
    def authored(name):
        award,scenario=demo_case(name)
        q=request_for("fpds",award.to_dict(),1,10)["parameters"]["q"]
        href=FPDS+"?"+urlencode({"q":q,"FEEDNAME":"PUBLIC","VERSION":"1.5.3","s":"FPDS","start":10})
        scenario["responses"][-1]["text"]=scenario["responses"][-1]["text"].replace("</feed>",'<link rel="next" href="'+escape(href,{'"':'&quot;'})+'"/></feed>')
        return award,scenario
    p=tmp_path/"original"
    config=PilotConfig(mode="synthetic",target=1,implementation_sha256=implementation_digest())
    with monkeypatch.context() as m:
        m.setattr(collection,"make_plan",make_legacy)
        m.setattr(sources,"safe_next",old_safe)
        m.setattr(research,"demo_case",authored)
        report,code=run_pilot(p,config)
        assert code==2 and report["evaluation"]["processing_failures"]==1
    baseline=p/"pilot-report-000.json"
    return p,baseline,report


def test_original_v2_bytes_recover_into_new_c7_without_collection(legacy,tmp_path,monkeypatch):
    import src.research_pipeline as research
    p,baseline,before=legacy
    snapshot=files(p)
    monkeypatch.setattr(research,"collect_selected",Mock(side_effect=AssertionError("no collection")))
    after,comparison,code=recover(p,tmp_path/"recovered",baseline)
    assert code==1 and files(p)==snapshot
    assert comparison["additional_http_requests"]==0 and comparison["same_frozen_sample"]
    assert before["sample"]==after["sample"]
    assert before["evaluation"]["rates"]["source_retrieval_success"]["count"]==1
    assert after["evaluation"]["rates"]["source_retrieval_success"]["count"]==2
    assert before["evaluation"]["rates"]["source_retrieval_success"]["denominator"]==after["evaluation"]["rates"]["source_retrieval_success"]["denominator"]==2
    assert before["evaluation"]["rates"]["evidence_integrity_verified_entries"]["denominator"]==after["evaluation"]["rates"]["evidence_integrity_verified_entries"]["denominator"]
    assert after["evaluation"]["packets_generated"]==3
    assert after["evaluation"]["rates"]["unknown_or_incomplete_history"]["count"]==1
    assert after["evaluation"]["resources"]["live_request_slots_reserved"]==0
    assert after["execution_mode"]=="offline_saved_evidence_recovery"


def test_recovery_resume_validates_and_preserves_original_and_prior_outputs(legacy,tmp_path):
    p,baseline,_=legacy
    out=tmp_path/"recovered"
    a,_,_=recover(p,out,baseline)
    original,outputs=files(p),files(out)
    b,_,_=recover(p,out,baseline,resume=True)
    assert digest(a)==digest(b) and files(p)==original
    assert all((out/n).read_bytes()==raw for n,raw in outputs.items())


@pytest.mark.parametrize("target",["sample","body","baseline"])
def test_recovery_rejects_changed_sample_evidence_or_baseline_before_outputs(legacy,tmp_path,target):
    p,baseline,_=legacy
    if target=="sample":
        doc=strict_json((p/"sample.json").read_bytes());doc["seed"]="changed"
        (p/"sample.json").write_text(canonical(doc))
    elif target=="body":
        next(p.rglob("c3_attempt_000001.body")).write_bytes(b"tampered")
    else:
        doc=strict_json(baseline.read_bytes());doc["report"]["sample"]["target"]=999
        baseline.write_text(canonical(doc))
    with pytest.raises(EvidenceError):
        recover(p,tmp_path/"bad",baseline)
    assert not (tmp_path/"bad").exists()


def test_recovery_missing_original_is_explicit_failure(tmp_path):
    with pytest.raises((EvidenceError,OSError)):
        recover(tmp_path/"missing",tmp_path/"out",tmp_path/"missing-baseline.json")
    assert not (tmp_path/"out").exists()


def test_c7_interruption_stops_recovery_before_later_awards(legacy,tmp_path,monkeypatch):
    import src.recover_pilot as module
    p,baseline,_=legacy
    call=Mock(return_value=(type('Interrupted',(),{'exit_code':130})(),None))
    monkeypatch.setattr(module,'run_research',call)
    with pytest.raises(KeyboardInterrupt):
        recover(p,tmp_path/'interrupted',baseline)
    assert call.call_count==1
    assert not list((tmp_path/'interrupted').glob('recovery-report-*'))
