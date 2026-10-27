"""C7 deterministic integration tests with authored fictional source records."""
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.collection import CollectionLimits
from src.evidence_io import EvidenceError, canonical, strict_json
from src.research_demo import CASES
from src.research_models import ResearchConfig, ResearchRun, StageState, STAGES
from src.research_pipeline import main, run_research
from src.review_packet_io import read_bundle


def config(cases=("agreement",),**kw):
    return ResearchConfig(mode="demo",demo_cases=cases,
        collection=CollectionLimits(max_awards=1,max_records_per_source_award=40,max_records_total=100,retries=1,pace_seconds=0.0,backoff_seconds=0.0),**kw)


def files(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_agreement_pipeline_has_narrow_success_not_complete_evidence(tmp_path,monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session,"request",Mock(side_effect=AssertionError("network forbidden")))
    run,path = run_research(tmp_path/"run",config())
    assert run.technical_success and not run.evidentiary_complete and run.exit_code==0
    assert tuple(s.stage for s in run.stages)==STAGES and all(s.state is StageState.COMPLETED for s in run.stages)
    metrics = strict_json(run.metrics_json.encode())
    assert metrics["selected_awards"]==1 and metrics["packets_generated"]==3
    assert metrics["observed_agreements"]==metrics["compatible_financial_comparisons"]==1
    assert ResearchRun.from_dict(strict_json(path.read_bytes())["run"])==run
    packet = next(a for s in run.stages for a in s.artifacts if a.name=="agreement/packets.json")
    manifest,events = read_bundle((tmp_path/"run"/packet.storage_path).parent)
    assert len(manifest.packets)==3 and not events


def test_full_demo_and_substantive_reproducibility_twice(tmp_path,monkeypatch):
    import requests
    monkeypatch.setattr(requests.Session,"request",Mock(side_effect=AssertionError("offline only")))
    a,_ = run_research(tmp_path/"a",config(CASES))
    b,_ = run_research(tmp_path/"b",config(CASES))
    assert a.technical_success and b.technical_success and a.exit_code==b.exit_code==1
    assert a.run_id==b.run_id and a.substantive_sha256==b.substantive_sha256
    assert a.to_dict(substantive=True)==b.to_dict(substantive=True)
    m = strict_json(a.metrics_json.encode())
    assert m["packets_generated"]==24 and m["selected_awards"]==6
    assert m["identity_counts"]["ambiguous_match"]>0
    assert m["observed_agreements"]==5 and m["differences_requiring_evidence"]==1
    assert m["source_diagnostic_count"]>=1 and m["field_compatible_candidates"]>m["compatible_financial_comparisons"]
    scan = strict_json((tmp_path/"a"/"artifacts/verify/attempt-000/duplicates/evidence.json").read_bytes())
    observations = [e["observation"] for e in scan["entries"] if e["observation"]]
    assert observations[0]["content_id"]==observations[1]["content_id"]
    assert observations[0]["observation_id"]!=observations[1]["observation_id"]


def test_resume_reuses_only_valid_commits_no_collection(tmp_path,monkeypatch):
    import src.research_pipeline as module
    root=tmp_path/"run"
    a,_ = run_research(root,config())
    before=files(root)
    monkeypatch.setattr(module,"execute_stage",Mock(side_effect=AssertionError("no stage rerun")))
    b,_ = run_research(root,config(),resume=True,execution_time=True)
    assert a.substantive_sha256==b.substantive_sha256
    assert b.executed_at_utc is not None
    assert all((root/n).read_bytes()==raw for n,raw in before.items())


@pytest.mark.parametrize("stage",["acquire","verify","identity","finance","packets","summary"])
def test_interrupt_before_commit_requires_explicit_retry(tmp_path,monkeypatch,stage):
    import src.research_pipeline as module
    root=tmp_path/"run"
    original=module.execute_stage
    once=True
    def interrupt(store,c,s,*args,**kw):
        nonlocal once
        if s==stage and once:
            once=False
            raise KeyboardInterrupt
        return original(store,c,s,*args,**kw)
    monkeypatch.setattr(module,"execute_stage",interrupt)
    report,_=run_research(root,config())
    assert report.exit_code==130 and not report.technical_success
    index=STAGES.index(stage)
    assert report.stages[index].state is StageState.FAILED
    assert all(s.state is StageState.BLOCKED for s in report.stages[index+1:])
    before=files(root)
    with pytest.raises(EvidenceError,match="explicit_retry"):
        run_research(root,config(),resume=True)
    assert files(root)==before
    resumed,_=run_research(root,config(),resume=True,retry_failed=True)
    fresh,_=run_research(tmp_path/"fresh",config())
    assert resumed.technical_success and resumed.substantive_sha256==fresh.substantive_sha256
    assert all((root/n).read_bytes()==raw for n,raw in before.items())


def test_interruption_after_durable_stage_commit_reuses_stage(tmp_path,monkeypatch):
    from src.research_store import ResearchStore
    original=ResearchStore.commit
    once=True
    def interrupt(self,stage,*args,**kw):
        nonlocal once
        result=original(self,stage,*args,**kw)
        if stage=="identity" and once:
            once=False
            raise KeyboardInterrupt
        return result
    monkeypatch.setattr(ResearchStore,"commit",interrupt)
    root=tmp_path/"run"
    report,_=run_research(root,config())
    assert report.exit_code==130
    identity=(root/"stage-identity.json").read_bytes()
    resumed,_=run_research(root,config(),resume=True)
    assert resumed.technical_success and (root/"stage-identity.json").read_bytes()==identity


@pytest.mark.parametrize("damage",["missing","tampered"])
def test_damaged_synthetic_copy_blocks_dependents_preserves_original(tmp_path,damage):
    root=tmp_path/"run"
    run,_=run_research(root,config(demo_damage=damage))
    assert run.exit_code==2 and not run.technical_success
    assert run.stages[1].state is StageState.FAILED
    assert all(s.state is StageState.BLOCKED for s in run.stages[2:])
    original=root/"evidence/agreement/c3_attempt_000000.body"
    assert b"federal_action_obligation" in original.read_bytes()
    assert not (root/"stage-identity.json").exists()


@pytest.mark.parametrize("target",["evidence/agreement/c3_attempt_000000.body","artifacts/identity/attempt-000/agreement/identity.json",
    "artifacts/finance/attempt-000/agreement/finance.json","artifacts/packets/attempt-000/agreement/review.html"])
def test_modified_input_or_output_rejected_before_reuse(tmp_path,target):
    root=tmp_path/"run"
    run_research(root,config())
    (root/target).write_bytes(b"changed")
    before=files(root)
    with pytest.raises((EvidenceError,ValueError)):
        run_research(root,config(),resume=True,retry_failed=True)
    assert files(root)==before


@pytest.mark.parametrize("change",[{"max_claims":99},{"max_output_bytes":2*1024*1024},{"max_attempts":3}])
def test_changed_configuration_rejected_without_mutation(tmp_path,change):
    root=tmp_path/"run"
    run_research(root,config())
    before=files(root)
    with pytest.raises(EvidenceError,match="incompatible_research_plan"):
        run_research(root,replace(config(),**change),resume=True)
    assert files(root)==before


@pytest.mark.parametrize("change",[{"schema_version":2},{"schema_version":True},{"pipeline_version":"future"},{"stage_order":tuple(reversed(STAGES))}])
def test_version_or_stage_order_rejected(change):
    with pytest.raises(ValueError):
        replace(config(),**change)


def test_existing_evidence_mode_is_readonly(tmp_path):
    generated,_=run_research(tmp_path/"generated",config())
    source=tmp_path/"generated/evidence/agreement"
    before=files(source)
    run,_=run_research(tmp_path/"existing",ResearchConfig(),evidence=(source,))
    assert run.technical_success and files(source)==before


def test_output_limits_fail_reporting_not_skip_required_stage(tmp_path):
    run,_=run_research(tmp_path/"run",config(max_output_bytes=1024))
    assert run.exit_code==2 and run.stages[4].state is StageState.FAILED
    assert run.stages[5].state is StageState.BLOCKED
    assert run.stages[4].diagnostic.category=="reporting"


def test_cli_modes_exit_codes_and_no_silent_limit_overrides(tmp_path,capsys):
    assert main(["--demo","--demo-case","agreement","--run-dir",str(tmp_path/"good")])==0
    assert strict_json(capsys.readouterr().out.encode())["technical_success"]
    assert main(["--demo","--demo-case","financial_gap","--run-dir",str(tmp_path/"gap")])==1
    capsys.readouterr()
    assert main(["--live","--run-dir",str(tmp_path/"bad")])==2
    assert not (tmp_path/"bad").exists()
    assert main(["--demo","--max-requests","1","--run-dir",str(tmp_path/"override")])==2
    assert not (tmp_path/"override").exists()
