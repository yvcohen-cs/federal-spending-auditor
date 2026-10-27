"""C7 stale-output, storage, recovery and live-boundary adversarial coverage."""
import hashlib
import shutil
from dataclasses import replace
from unittest.mock import Mock

import pytest

from src.collection import CollectionLimits, collect_selected as original_collect
from src.collection_sources import FixtureTransport
from src.evidence_io import EvidenceError, canonical, strict_json
from src.financial_models import FinancialLimits
from src.research_demo import demo_case
from src.research_models import ResearchConfig, StageState
from src.research_pipeline import run_research
from src.review_packet_builder import project_packets
from src.review_packet_html import render_html
from src.review_packet_io import read_bundle, write_bundle
from src.review_packet_models import ReviewPacketManifest
from tests.test_research_pipeline import config, files


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    root=tmp_path_factory.mktemp("c7-synthetic")/"template"
    run_research(root,config())
    return root


def copied(template,tmp_path):
    root=tmp_path/"run"
    shutil.copytree(template,root)
    return root


def repair_receipt(root,stage):
    p=root/f"stage-{stage}.json"
    doc=strict_json(p.read_bytes())
    for a in doc["result"]["artifacts"]:
        raw=(root/a["storage_path"]).read_bytes()
        a["sha256"]=hashlib.sha256(raw).hexdigest(); a["byte_count"]=len(raw)
    p.write_text(canonical(doc))


def test_copied_run_resolves_managed_inputs_without_inventing_new_observations(template,tmp_path):
    root=copied(template,tmp_path)
    a=strict_json((root/"research-run-000000.json").read_bytes())
    b,_=run_research(root,config(),resume=True)
    assert a["substantive_sha256"]==b.substantive_sha256
    assert all(str(root) in i.location for i in b.inputs)


def test_stale_c4_even_with_repaired_byte_hash_rejected(template,tmp_path):
    root=copied(template,tmp_path)
    p=root/"artifacts/identity/attempt-000/agreement/identity.json"
    doc=strict_json(p.read_bytes()); doc["input_manifest_sha256"]="f"*64
    p.write_text(canonical(doc)); repair_receipt(root,"identity")
    before=files(root)
    with pytest.raises(EvidenceError,match="stale_research_identity"):
        run_research(root,config(),resume=True)
    assert files(root)==before


def test_stale_c5_even_with_repaired_byte_hash_rejected(template,tmp_path):
    root=copied(template,tmp_path)
    p=root/"artifacts/finance/attempt-000/agreement/finance.json"
    doc=strict_json(p.read_bytes()); doc["identity_run"]["input_manifest_sha256"]="f"*64
    p.write_text(canonical(doc)); repair_receipt(root,"finance")
    with pytest.raises(EvidenceError,match="stale_research_financial"):
        run_research(root,config(),resume=True)


def test_stale_c6_valid_alternate_projection_rejected(template,tmp_path):
    root=copied(template,tmp_path)
    bundle=root/"artifacts/packets/attempt-000/agreement"
    old,_=read_bundle(bundle)
    other=replace(old.financial_run,limits=FinancialLimits(max_observations=4999))
    packets,total=project_packets(other,old.selected_claim_ids)
    manifest=ReviewPacketManifest(financial_run=other,selected_claim_ids=old.selected_claim_ids,packets=packets,total_available_claims=total)
    temp=tmp_path/"alternate"
    write_bundle(temp,manifest,render_html(manifest))
    for p in temp.iterdir():
        (bundle/p.name).write_bytes(p.read_bytes())
    repair_receipt(root,"packets")
    with pytest.raises(EvidenceError,match="stale_research_packet"):
        run_research(root,config(),resume=True)


@pytest.mark.parametrize("target",["research-plan.json","stage-identity.json","research-run-000000.json"])
def test_corrupted_control_files_rejected_without_new_writes(template,tmp_path,target):
    root=copied(template,tmp_path)
    (root/target).write_text("{}")
    before=files(root)
    with pytest.raises((EvidenceError,ValueError,KeyError)):
        run_research(root,config(),resume=True)
    assert files(root)==before


def test_gap_in_committed_dependency_order_is_not_filled_silently(template,tmp_path):
    root=copied(template,tmp_path)
    (root/"stage-identity.json").unlink()
    before=files(root)
    with pytest.raises(EvidenceError,match="stage_commit_order"):
        run_research(root,config(),resume=True,retry_failed=True)
    assert files(root)==before


def test_partial_output_and_extra_committed_artifact_refused(template,tmp_path):
    root=copied(template,tmp_path)
    (root/"artifacts/identity/attempt-000/agreement/unexpected.partial").write_text("partial")
    with pytest.raises(EvidenceError,match="incomplete_research_stage_outputs"):
        run_research(root,config(),resume=True)


def test_bool_cannot_forge_successful_run_exit_code(template,tmp_path):
    root=copied(template,tmp_path)
    path=root/"research-run-000000.json"
    doc=strict_json(path.read_bytes()); doc["exit_code"]=False
    path.write_text(canonical(doc))
    with pytest.raises(EvidenceError,match="manifest_conflict"):
        run_research(root,config(),resume=True)


def test_symlink_input_output_and_nested_run_refused(template,tmp_path):
    link=tmp_path/"link"; link.symlink_to(template,target_is_directory=True)
    with pytest.raises((EvidenceError,OSError)):
        run_research(link,config(),resume=True)
    with pytest.raises(EvidenceError):
        run_research(template/"nested",config())
    with pytest.raises(EvidenceError):
        run_research(template/"evidence/agreement/out",ResearchConfig(),evidence=(template/"evidence/agreement",))
    assert not (template/"nested").exists()


def test_hardlinked_stage_output_not_trusted(template,tmp_path):
    import os
    root=copied(template,tmp_path)
    p=root/"artifacts/identity/attempt-000/agreement/identity.json"
    os.link(p,tmp_path/"extra")
    with pytest.raises(EvidenceError):
        run_research(root,config(),resume=True)


def test_explicit_retry_keeps_failure_and_sanitizes_diagnostics(tmp_path,monkeypatch):
    import src.research_pipeline as module
    original=module.execute_stage
    once=True
    def fail(store,c,stage,*args,**kw):
        nonlocal once
        if stage=="packets" and once:
            once=False
            raise OSError("SECRET_RAW_RESPONSE_body_and_credentials")
        return original(store,c,stage,*args,**kw)
    monkeypatch.setattr(module,"execute_stage",fail)
    root=tmp_path/"run"
    report,_=run_research(root,config())
    assert report.exit_code==2 and report.stages[4].diagnostic.category=="storage"
    before=files(root)
    assert not any(b"SECRET_RAW" in raw for raw in before.values())
    repaired,_=run_research(root,config(),resume=True,retry_failed=True)
    assert repaired.technical_success
    assert all((root/n).read_bytes()==raw for n,raw in before.items())


def test_schema_invalid_stage_output_cannot_receive_commit(tmp_path,monkeypatch):
    import src.research_pipeline as module
    original=module.execute_stage
    def invalid(store,c,stage,attempt,*args,**kw):
        result=original(store,c,stage,attempt,*args,**kw)
        if stage=="identity":
            (store.path/attempt/"agreement/identity.json").write_text("{}")
        return result
    monkeypatch.setattr(module,"execute_stage",invalid)
    root=tmp_path/"run"
    report,_=run_research(root,config())
    assert report.exit_code==2 and not (root/"stage-identity.json").exists()


def test_live_policy_no_network_without_explicit_complete_selection(tmp_path,monkeypatch):
    import requests
    request=Mock(side_effect=AssertionError("no network"))
    monkeypatch.setattr(requests.Session,"request",request)
    with pytest.raises(ValueError): ResearchConfig(mode="live")
    selected,_=demo_case("agreement")
    with pytest.raises(ValueError):
        ResearchConfig(mode="live",selected_awards=(replace(selected,agency_id=None),))
    with pytest.raises(ValueError):
        ResearchConfig(mode="live",selected_awards=(selected,),collection=CollectionLimits(max_requests=31))
    assert not request.called


def test_live_boundary_delegates_uncertain_reservation_to_c3(tmp_path,monkeypatch):
    import src.research_pipeline as module
    import requests
    monkeypatch.setattr(requests.Session,"request",Mock(side_effect=AssertionError("no real network")))
    selected,scenario=demo_case("agreement")
    c=ResearchConfig(mode="live",selected_awards=(selected,),collection=CollectionLimits(max_requests=2,retries=0))
    transports=[]
    once=True
    def simulated(path,awards,**kw):
        nonlocal once
        kw["profile"]="fixture:explicit-live-boundary-test"
        kw["sleep"]=lambda _:None
        kw["transport"]=Mock(side_effect=KeyboardInterrupt) if once else FixtureTransport(scenario)
        transports.append(kw["resume"])
        once=False
        return original_collect(path,awards,**kw)
    monkeypatch.setattr(module,"collect_selected",simulated)
    root=tmp_path/"run"
    first,_=run_research(root,c)
    assert first.exit_code==130
    cp=root/"evidence/selected/c3_checkpoint.json"
    assert strict_json(cp.read_bytes())["pending"]
    second,_=run_research(root,c,resume=True,retry_failed=True)
    assert second.technical_success and second.exit_code==1
    assert transports==[False,True]
    assert strict_json(cp.read_bytes())["pending"] is None
    unknown=strict_json((root/"evidence/selected/c3_attempt_000000.json").read_bytes())
    assert unknown["error_code"]=="interrupted_request_outcome_unknown"
    assert strict_json(second.metrics_json.encode())["source_diagnostic_count"]>=1


def test_live_capture_budget_is_checked_before_any_request(tmp_path,monkeypatch):
    import src.research_pipeline as module
    collect=Mock(side_effect=AssertionError("capture must not start"))
    monkeypatch.setattr(module,"collect_selected",collect)
    selected,_=demo_case("agreement")
    c=ResearchConfig(mode="live",selected_awards=(selected,),max_run_bytes=1024*1024)
    report,_=run_research(tmp_path/"run",c)
    assert report.exit_code==2 and not collect.called
    assert report.stages[0].diagnostic.code=="research_live_capture_budget_exceeds_run_limit"


def test_implementation_fingerprint_change_rejected_before_storage(tmp_path):
    c=replace(config(),implementation_sha256="f"*64)
    with pytest.raises(EvidenceError,match="implementation_changed"):
        run_research(tmp_path/"run",c)
    assert not (tmp_path/"run").exists()


def test_extra_stage_output_cannot_receive_commit(tmp_path,monkeypatch):
    import src.research_pipeline as module
    original=module.execute_stage
    def extra(store,c,stage,attempt,*args,**kw):
        result=original(store,c,stage,attempt,*args,**kw)
        if stage=="identity":
            store.write(attempt+"/unexpected.json",{"unexpected":True})
        return result
    monkeypatch.setattr(module,"execute_stage",extra)
    root=tmp_path/"run"
    run,_=run_research(root,config())
    assert run.exit_code==2 and not (root/"stage-identity.json").exists()


def test_missing_timestamp_cannot_become_known_provenance(template,tmp_path):
    source=tmp_path/"source"
    shutil.copytree(template/"evidence/agreement",source)
    metadata=source/"c3_attempt_000000.json"
    doc=strict_json(metadata.read_bytes()); doc["retrieved_at_utc"]=None
    metadata.write_text(canonical(doc))
    from src.evidence_io import digest
    checkpoint=source/"c3_checkpoint.json"
    cp=strict_json(checkpoint.read_bytes()); cp["events"][0]["metadata_sha256"]=digest(doc)
    checkpoint.write_text(canonical(cp))
    before=files(source)
    run,_=run_research(tmp_path/"run",ResearchConfig(),evidence=(source,))
    assert run.exit_code==2 and run.stages[1].state is StageState.FAILED
    assert files(source)==before


def test_duplicate_claim_selection_counts_actual_packet_sections(template,tmp_path):
    sources=[]
    for name in ("one","two"):
        source=tmp_path/name
        shutil.copytree(template/"evidence/agreement",source); sources.append(source)
    finance=strict_json((template/"artifacts/finance/attempt-000/agreement/finance.json").read_bytes())
    selected=finance["results"][0]["claim_id"]
    run,_=run_research(tmp_path/"run",ResearchConfig(claim_ids=(selected,),max_claims=1),evidence=tuple(sources))
    assert run.exit_code==2 and run.stages[4].diagnostic.code=="research_claim_limit"
    metrics=strict_json(run.metrics_json.encode())
    assert metrics["response_observation_entries"]==4 and metrics["response_observations"]==2


def test_conflicting_retrieval_identity_across_collections_is_not_a_new_event(template,tmp_path):
    from src.evidence_io import digest
    a,b=tmp_path/"one",tmp_path/"two"
    shutil.copytree(template/"evidence/agreement",a); shutil.copytree(a,b)
    body=b/"c3_attempt_000000.body"
    doc=strict_json(body.read_bytes()); doc["results"][0]["federal_action_obligation"]=101
    raw=canonical(doc).encode(); body.write_bytes(raw)
    meta_path=b/"c3_attempt_000000.json"
    meta=strict_json(meta_path.read_bytes()); meta["body_sha256"]=hashlib.sha256(raw).hexdigest()
    meta_path.write_text(canonical(meta))
    checkpoint=b/"c3_checkpoint.json"
    cp=strict_json(checkpoint.read_bytes()); cp["events"][0]["metadata_sha256"]=digest(meta); cp["events"][0]["body_sha256"]=meta["body_sha256"]
    checkpoint.write_text(canonical(cp))
    run,_=run_research(tmp_path/"run",ResearchConfig(),evidence=(a,b))
    assert run.exit_code==2 and run.stages[1].diagnostic.code=="research_conflicting_observation_context"
    assert not (tmp_path/"run/stage-identity.json").exists()


def test_partial_c6_bundle_retries_to_new_attempt_preserving_orphan(tmp_path,monkeypatch):
    import src.review_packet_io as module
    original=module.atomic_create
    once=True
    def interrupt(fd,name,raw):
        nonlocal once
        if name=="review.html" and once:
            once=False
            raise KeyboardInterrupt
        return original(fd,name,raw)
    monkeypatch.setattr(module,"atomic_create",interrupt)
    root=tmp_path/"run"
    first,_=run_research(root,config())
    assert first.exit_code==130
    partial=root/"artifacts/packets/attempt-000/agreement/packets.json"
    raw=partial.read_bytes()
    repaired,_=run_research(root,config(),resume=True,retry_failed=True)
    assert repaired.technical_success and partial.read_bytes()==raw
    assert (root/"artifacts/packets/attempt-001/agreement/output-manifest.json").exists()
