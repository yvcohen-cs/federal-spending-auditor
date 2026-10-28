"""Opt-in bounded C1–C6 orchestration with immutable stage commits."""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .collection import CollectionLimits, SelectedAward, collect_selected
from .collection_sources import FixtureTransport
from .evidence import ComparisonStatus
from .evidence_ingestion import IngestionManifest, ValidationStatus, inspect_directory
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .financial_ingestion import reconcile_collection
from .financial_models import FinancialRun
from .matching_ingestion import match_collection
from .matching_models import MatchRunSummary
from .research_demo import CASES, demo_case
from .research_models import (PIPELINE_VERSION, RULES, STAGES, ResearchConfig, ResearchDiagnostic,
                              ResearchInput, ResearchRun, ResearchStage, StageState, implementation_digest)
from .research_store import ResearchStore
from .research_summary import quality_gates, readable_summary
from .review_packet_builder import build_packets
from .review_packet_html import render_html
from .review_packet_io import outside, read_bundle, write_bundle


def source_scan(label,path):
    scan = inspect_directory(path)
    plan_entry = next((e for e in scan.entries if e.relative_path=="c3_plan.json" and e.status is ValidationStatus.VERIFIED),None)
    selected,scope,plan_sha,profile = (),{},None,"unknown"
    if plan_entry:
        with EvidenceRoot(path) as root:
            snap = root.read("c3_plan.json")
        if snap.byte_sha256 != plan_entry.byte_sha256:
            raise EvidenceError("research_evidence_changed")
        plan = strict_json(snap.data)
        selected = tuple(SelectedAward.from_dict(a) for a in plan["awards"])
        scope = {"sources":plan["sources"],"limits":plan["limits"],"collector_version":plan["collector_version"],
                 "identity_basis":"explicit_collection_selection_not_authoritative_cross_source_identity"}
        plan_sha = digest(plan)
        profile = "live" if plan["profile"]=="live" else "synthetic" if isinstance(plan["profile"],str) and plan["profile"].startswith("fixture:") else "unknown"
    return ResearchInput(label=label,evidence_sha256=scan.substantive_sha256,collection_plan_sha256=plan_sha,
        selected_awards=selected,query_scope_json=canonical(scope),profile=profile,location=str(Path(path).absolute())),scan


def artifact_path(result,label,name):
    logical = label+"/"+name
    found = [a.storage_path for a in result.artifacts if a.name==logical]
    if len(found)!=1:
        raise EvidenceError("missing_research_result_reference")
    return found[0]


def typed_artifact(store,result,label,name,model):
    return model.from_dict(store.json(artifact_path(result,label,name)))


def input_digest(config,stage,inputs,completed):
    return digest({"pipeline":PIPELINE_VERSION,"rules":RULES,"config":config.to_dict(),"stage":stage,
                   "inputs":[i.to_dict(substantive=True) for i in inputs],
                   "dependencies":[s.to_dict(substantive=True) for s in completed]})


def metrics_from(store,config,inputs,completed):
    stages = {s.stage:s for s in completed}
    metrics = {"selected_awards":len({a for i in inputs for a in i.selected_awards}),
               "selected_award_selection_rows":sum(len(i.selected_awards) for i in inputs),
               "unknown_selection_scopes":sum(i.collection_plan_sha256 is None for i in inputs)}
    if "verify" in stages:
        scans = [typed_artifact(store,stages["verify"],i.label,"evidence.json",IngestionManifest) for i in inputs]
        metrics["response_observation_entries"] = sum(bool(e.observation) for s in scans for e in s.entries)
        metrics["response_observations"] = len({e.observation.observation_id for s in scans for e in s.entries if e.observation and e.observation.observation_id})
        metrics["usable_observations"] = sum(e.status is ValidationStatus.VERIFIED and bool(e.observation) for s in scans for e in s.entries)
        metrics["retrieval_rows"] = sum(len(e.observation.records) for s in scans for e in s.entries if e.observation)
        metrics["evidence_validation"] = {v.value:sum(s.summary[v.value] for s in scans) for v in ValidationStatus}
        metrics["source_observation_gaps"] = sum(source not in {e.observation.artifact.source for e in scan.entries if e.status is ValidationStatus.VERIFIED and e.observation}
            for i,scan in zip(inputs,scans) for source in strict_json(i.query_scope_json.encode()).get("sources",[]))
        diagnostics = [ResearchDiagnostic(stage="acquire",category="network",code=f"http_{e.observation.artifact.http_status}").to_dict()
            for s in scans for e in s.entries if e.observation and e.observation.artifact.http_status is not None and not 200<=e.observation.artifact.http_status<300]
        metrics["source_diagnostic_count"] = len(diagnostics)
        metrics["source_diagnostics"] = diagnostics[:100]
        metrics["source_diagnostics_omitted"] = max(0,len(diagnostics)-100)
    if "identity" in stages:
        runs = [typed_artifact(store,stages["identity"],i.label,"identity.json",MatchRunSummary) for i in inputs]
        metrics["identity_counts"] = {v.value:sum(d.status is v for r in runs for d in r.decisions) for v in ComparisonStatus}
        metrics["distinct_retrieval_contents"] = sum(len(r.records) for r in runs)
        metrics["records_without_identity_claim"] = sum(r.record_id not in {rid for d in run.decisions for c in d.award_candidates+d.action_candidates for rid in c.record_ids}
            for run in runs for r in run.records if r.source=="fpds")
        metrics["excluded_artifacts"] = sum(len(r.excluded_artifacts) for r in runs)
        missing = [ResearchDiagnostic(stage="acquire",category="network",code="preserved_source_response_unavailable").to_dict()
                   for r in runs for e in r.excluded_artifacts if e.reason=="no_response_body"]
        diagnostics = metrics.get("source_diagnostics",[])+missing
        metrics["source_diagnostic_count"] = metrics.get("source_diagnostic_count",0)+len(missing)
        metrics["source_diagnostics"] = diagnostics[:100]
        metrics["source_diagnostics_omitted"] = max(0,metrics["source_diagnostic_count"]-100)
    if "finance" in stages:
        runs = [typed_artifact(store,stages["finance"],i.label,"finance.json",FinancialRun) for i in inputs]
        metrics["financial_counts"] = {v.value:sum(r.counts[v.value] for r in runs) for v in ComparisonStatus}
        metrics["compatible_financial_comparisons"] = sum(d.compatibility.value=="compatible" and d.difference_usa_minus_fpds is not None for r in runs for d in r.results)
        metrics["field_compatible_candidates"] = sum(d.compatibility.value=="compatible" for r in runs for d in r.results)
        metrics["observed_agreements"] = sum(d.status is ComparisonStatus.VERIFIED_MATCH for r in runs for d in r.results)
        metrics["differences_requiring_evidence"] = sum(d.difference_usa_minus_fpds not in (None,"0") for r in runs for d in r.results)
        metrics["insufficient_financial_claims"] = sum(d.status is ComparisonStatus.INSUFFICIENT_EVIDENCE for r in runs for d in r.results)
    if "packets" in stages:
        metrics["packets_generated"] = sum(len(read_bundle(store.path/Path(artifact_path(stages["packets"],i.label,"packets.json")).parent)[0].packets) for i in inputs)
    return metrics


def register_observations(scan,seen):
    for entry in scan.entries:
        o=entry.observation
        if o and o.observation_id:
            if o.observation_id in seen and seen[o.observation_id]!=o.content_id:
                raise EvidenceError("research_conflicting_observation_context")
            seen[o.observation_id]=o.content_id


def verify_stage_semantics(store,result,config,inputs,completed):
    prior = {s.stage:s for s in completed}
    stage = result.stage
    leaf = {"verify":"evidence.json","identity":"identity.json","finance":"finance.json"}
    expected_names = ({"acquire.json"} if stage=="acquire" else {"summary.json","summary.txt"} if stage=="summary"
                      else {i.label+"/"+n for i in inputs for n in ("packets.json","review.html","review-events.json","output-manifest.json")} if stage=="packets"
                      else {i.label+"/"+leaf[stage] for i in inputs})
    if {a.name for a in result.artifacts}!=expected_names:
        raise EvidenceError("research_stage_contract_output_conflict")
    if stage=="acquire":
        actual = store.json(result.artifacts[0].storage_path)
        if digest(actual)!=digest({"inputs":[i.to_dict(substantive=True) for i in inputs]}):
            raise EvidenceError("research_acquisition_contract_conflict")
        return
    seen_observations={}
    for i in inputs:
        if stage=="verify":
            scan = typed_artifact(store,result,i.label,"evidence.json",IngestionManifest)
            if scan.substantive_sha256 != i.evidence_sha256 or not scan.complete or any(e.status in (ValidationStatus.INVALID,ValidationStatus.UNSUPPORTED) for e in scan.entries):
                raise EvidenceError("stale_research_evidence_report")
            register_observations(scan,seen_observations)
        elif stage=="identity":
            run = typed_artifact(store,result,i.label,"identity.json",MatchRunSummary)
            if run.input_manifest_sha256 != i.evidence_sha256 or run.limits != config.matching:
                raise EvidenceError("stale_research_identity_report")
        elif stage=="finance":
            run = typed_artifact(store,result,i.label,"finance.json",FinancialRun)
            identity = typed_artifact(store,prior["identity"],i.label,"identity.json",MatchRunSummary)
            if run.identity_run.substantive_sha256 != identity.substantive_sha256 or run.limits != config.financial:
                raise EvidenceError("stale_research_financial_report")
        elif stage=="packets":
            bundle = store.path/Path(artifact_path(result,i.label,"packets.json")).parent
            manifest,events = read_bundle(bundle)
            finance = typed_artifact(store,prior["finance"],i.label,"finance.json",FinancialRun)
            expected = tuple(sorted({d.claim_id for d in finance.identity_run.decisions}|{d.claim_id for d in finance.results}))
            if config.claim_ids:
                expected = tuple(c for c in expected if c in config.claim_ids)
            if events or manifest.financial_run.substantive_sha256 != finance.substantive_sha256 or manifest.selected_claim_ids != expected:
                raise EvidenceError("stale_research_packet_report")
    if stage=="summary":
        expected = metrics_from(store,config,inputs,completed)
        if store.json(next(a.storage_path for a in result.artifacts if a.name=="summary.json")) != expected:
            raise EvidenceError("stale_research_summary")


def execute_stage(store,config,stage,attempt,inputs,completed,sources):
    prior = {s.stage:s for s in completed}
    if stage=="acquire":
        if config.mode!="existing":
            if config.mode=="live" and store.used_bytes()+config.collection.max_requests*(2*config.collection.max_response_bytes+8192)+65536 > config.max_run_bytes:
                raise EvidenceError("research_live_capture_budget_exceeds_run_limit")
            store.mkdir("evidence")
            for source in sources:
                label,path = source["label"],store.path/source["path"]
                if label=="damaged":
                    # Publish a NEW explicitly synthetic damaged copy. Originals
                    # remain byte-for-byte intact; no live evidence is rewritten.
                    if path.exists():
                        continue
                    store.mkdir(source["path"])
                    with EvidenceRoot(store.path/"evidence/agreement") as root:
                        for name in root.discover():
                            if name=="c3_attempt_000000.body" and config.demo_damage=="missing":
                                continue
                            raw = root.read(name).data
                            if name=="c3_attempt_000000.body" and config.demo_damage=="tampered":
                                raw = b"explicitly synthetic damaged copy"
                            store.write_bytes(source["path"]+"/"+name,raw)
                    continue
                if config.mode=="demo":
                    selected,scenario = demo_case(label)
                    profile,transport = "fixture:"+digest(scenario),FixtureTransport(scenario)
                    awards = (selected,)
                else:
                    profile,transport,awards = "live",None,config.selected_awards
                collect_selected(path,awards,limits=config.collection,profile=profile,transport=transport,
                    resume=path.exists(),**({"sleep":lambda _:None} if config.mode=="demo" else {}))
        inputs = tuple(source_scan(s["label"],store.path/s["path"] if s["managed"] else s["path"])[0] for s in sources)
        store.write(attempt+"/acquire.json",{"inputs":[i.to_dict(substantive=True) for i in inputs]})
        return inputs
    finance_by_label={}
    if stage=="packets":
        finance_by_label={i.label:typed_artifact(store,prior["finance"],i.label,"finance.json",FinancialRun) for i in inputs}
        all_finance=list(finance_by_label.values())
        available={d.claim_id for r in all_finance for d in r.identity_run.decisions}|{d.claim_id for r in all_finance for d in r.results}
        if any(c not in available for c in config.claim_ids):
            raise EvidenceError("unknown_research_claim_selection")
        required=(sum(sum(c in ({d.claim_id for d in r.identity_run.decisions}|{d.claim_id for d in r.results}) for c in config.claim_ids) for r in all_finance)
                  if config.claim_ids else sum(len(r.identity_run.decisions)+len(r.results) for r in all_finance))
        if required>config.max_claims:
            raise EvidenceError("research_claim_limit")
    seen_observations={}
    for i in inputs:
        if stage=="summary":
            break
        base = attempt+"/"+i.label
        if stage!="packets":
            store.mkdir(base)
        if stage=="verify":
            scan = inspect_directory(i.location)
            store.write(base+"/evidence.json",scan.to_dict())
            if scan.substantive_sha256 != i.evidence_sha256 or not scan.complete or any(e.status in (ValidationStatus.INVALID,ValidationStatus.UNSUPPORTED) for e in scan.entries):
                if any(e.error_code and any(s in e.error_code for s in ("json","xml","schema")) for e in scan.entries):
                    raise EvidenceError("research_evidence_parse_failed")
                raise EvidenceError("research_evidence_integrity_failed")
            names = {e.relative_path for e in scan.entries}
            if not {"c3_plan.json","c3_checkpoint.json"} <= names or any(n not in ("c3_plan.json","c3_checkpoint.json","c3_summary.json") and re.fullmatch(r"c3_attempt_[0-9]{6}\.(json|body)",n) is None for n in names):
                raise EvidenceError("research_requires_flat_c3_collection")
            register_observations(scan,seen_observations)
        elif stage=="identity":
            store.write(base+"/identity.json",match_collection(i.location,limits=config.matching).to_dict())
        elif stage=="finance":
            identity_path = store.path/artifact_path(prior["identity"],i.label,"identity.json")
            store.write(base+"/finance.json",reconcile_collection(i.location,identity_report_path=identity_path,limits=config.financial).to_dict())
        elif stage=="packets":
            finance = finance_by_label[i.label]
            local = {d.claim_id for d in finance.identity_run.decisions}|{d.claim_id for d in finance.results}
            selected = [c for c in config.claim_ids if c in local] if config.claim_ids else None
            manifest = build_packets(i.location,identity_report=store.path/artifact_path(prior["identity"],i.label,"identity.json"),
                financial_report=store.path/artifact_path(prior["finance"],i.label,"finance.json"),claim_ids=selected,max_claims=config.max_claims)
            budget = min(config.max_output_bytes,config.max_run_bytes-store.used_bytes()-65536)
            if budget<1024: raise EvidenceError("research_run_size_limit")
            write_bundle(store.path/base,manifest,render_html(manifest,max_bytes=budget),
                protected=tuple(j.location for j in inputs),max_output_bytes=budget)
    if stage=="summary":
        metrics = metrics_from(store,config,inputs,completed)
        store.write(attempt+"/summary.json",metrics)
        store.write_bytes(attempt+"/summary.txt",readable_summary(metrics).encode())
    return inputs


def check_sources(inputs):
    if any(source_scan(i.label,i.location)[0].to_dict(substantive=True) != i.to_dict(substantive=True) for i in inputs):
        raise EvidenceError("research_input_evidence_changed_start_new_run")


def classify(stage,exc):
    if isinstance(exc,KeyboardInterrupt):
        return ResearchDiagnostic(stage=stage,category="interrupted",code="research_interrupted")
    code = exc.code if isinstance(exc,EvidenceError) and re.fullmatch(r"[a-z0-9_]{1,100}",exc.code) else "research_stage_failed"
    category = {"acquire":"collection","verify":"integrity","identity":"identity","finance":"financial","packets":"reporting","summary":"reporting"}[stage]
    if isinstance(exc,OSError): category = "storage"
    if any(s in code for s in ("hash","integrity","evidence_changed","stale")): category = "integrity"
    if any(s in code for s in ("json","xml","parse")): category = "parsing"
    if any(s in code for s in ("timeout","connection","http_","tls")): category = "network"
    return ResearchDiagnostic(stage=stage,category=category,code=code)


def run_research(path,config,*,evidence=(),resume=False,retry_failed=False,execution_time=False,progress=None):
    if config.implementation_sha256!=implementation_digest():
        raise EvidenceError("research_implementation_changed_start_new_run")
    path = Path(path).absolute()
    if config.mode=="existing":
        if not evidence or len(evidence)>10: raise EvidenceError("bounded_existing_evidence_required")
        sources = [{"label":f"input-{n:03d}","managed":False,"path":str(Path(p).absolute())} for n,p in enumerate(evidence)]
        if len({s["path"] for s in sources})!=len(sources): raise EvidenceError("duplicate_research_evidence_path")
        outside(path,tuple(s["path"] for s in sources))
    elif config.mode=="demo":
        if evidence or not config.demo_cases or any(c not in CASES for c in config.demo_cases) or len(set(config.demo_cases))!=len(config.demo_cases):
            raise EvidenceError("invalid_synthetic_case_selection")
        if config.demo_damage and "agreement" not in config.demo_cases: raise EvidenceError("synthetic_damage_requires_agreement_case")
        sources = [{"label":c,"managed":True,"path":"evidence/"+c} for c in config.demo_cases]
        if config.demo_damage: sources.append({"label":"damaged","managed":True,"path":"evidence/damaged"})
    else:
        if evidence: raise EvidenceError("live_mode_cannot_use_existing_evidence")
        sources = [{"label":"selected","managed":True,"path":"evidence/selected"}]
    plan = {"schema_type":"ResearchPlan","schema_version":1,"pipeline_version":PIPELINE_VERSION,"rules":list(RULES),
            "config":config.to_dict(),"sources":sources,"demo_version":1 if config.mode=="demo" else None}
    if retry_failed and not resume: raise EvidenceError("research_retry_requires_resume")
    with ResearchStore(path,plan,resume=resume) as store:
        completed,inputs = [],()
        if "stage-acquire.json" in store.audit():
            acquire = store.receipt("acquire",input_digest(config,"acquire",(),()))
            data = store.json(next(a.storage_path for a in acquire.artifacts if a.name=="acquire.json"))
            locations = {s["label"]:str(store.path/s["path"] if s["managed"] else s["path"]) for s in sources}
            if not isinstance(data,dict) or set(data)!={"inputs"} or [i["label"] for i in data["inputs"]]!=[s["label"] for s in sources]:
                raise EvidenceError("research_acquisition_contract_conflict")
            inputs = tuple(ResearchInput.from_dict({**i,"location":locations[i["label"]]}) for i in data["inputs"])
            check_sources(inputs)
        for stage in STAGES:
            sha = input_digest(config,stage,() if stage=="acquire" else inputs,completed)
            result = store.receipt(stage,sha)
            if result:
                verify_stage_semantics(store,result,config,inputs,completed)
                completed.append(result)
                if progress: progress({"stage":stage,"status":"reused_after_validation"})
                continue
            # Validate all committed ancestors before any new filesystem/network work.
            if inputs: check_sources(inputs)
            attempt,index = store.attempt(stage,retry=retry_failed)
            if progress: progress({"stage":stage,"status":"started"})
            try:
                inputs = execute_stage(store,config,stage,attempt,inputs,completed,sources)
                if stage!="acquire": check_sources(inputs)
                result = store.commit(stage,sha,attempt,validate=lambda r:verify_stage_semantics(store,r,config,inputs,completed))
                verify_stage_semantics(store,result,config,inputs,completed)
                completed.append(result)
                if progress: progress({"stage":stage,"status":"completed"})
            except (Exception,KeyboardInterrupt) as exc:
                diagnostic = classify(stage,exc)
                store.mkdir("failures")
                store.write(f"failures/{stage}-{index:03d}.json",diagnostic.to_dict())
                completed.append(ResearchStage(stage=stage,state=StageState.FAILED,input_sha256=sha,diagnostic=diagnostic))
                if progress: progress({"stage":stage,"status":"failed","category":diagnostic.category,"code":diagnostic.code})
                break
        states = list(completed)
        for stage in STAGES[len(states):]:
            states.append(ResearchStage(stage=stage,state=StageState.BLOCKED,input_sha256=digest({"blocked":stage})))
        metrics = metrics_from(store,config,inputs,[s for s in completed if s.state is StageState.COMPLETED])
        report = ResearchRun(config=config,inputs=inputs,stages=tuple(states),metrics_json=canonical(metrics),
                            quality_gates=quality_gates(states,metrics),executed_at_utc=datetime.now(timezone.utc).isoformat() if execution_time else None)
        if inputs: check_sources(inputs)
        if config.implementation_sha256!=implementation_digest():
            raise EvidenceError("research_implementation_changed_start_new_run")
        store.audit()
        previous = [p for p in store.audit() if re.fullmatch(r"research-run-[0-9]{6}\.json",p)]
        if len(previous)>=100: raise EvidenceError("research_invocation_limit")
        name = f"research-run-{len(previous):06d}.json"
        store.write(name,{"run":report.to_dict(),"substantive_sha256":report.substantive_sha256,
                          "technical_success":report.technical_success,"evidentiary_complete":report.evidentiary_complete,"exit_code":report.exit_code})
        return report,path/name


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded opt-in C1–C6 research; no publication or misconduct inference.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--evidence",action="append",help="Existing flat C3 collection; repeat up to 10")
    mode.add_argument("--demo",action="store_true",help="Entirely synthetic offline demonstration")
    mode.add_argument("--live",action="store_true",help="Explicitly authorize bounded public C3 collection")
    parser.add_argument("--run-dir",required=True)
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--retry-failed",action="store_true")
    parser.add_argument("--selection",help="Explicit C3 awards JSON, required only for live mode")
    parser.add_argument("--demo-case",action="append",choices=CASES)
    parser.add_argument("--demo-damage",choices=("missing","tampered"))
    parser.add_argument("--max-claims",type=int,default=100)
    parser.add_argument("--claim-id",action="append")
    parser.add_argument("--max-output-bytes",type=int,default=8*1024*1024)
    parser.add_argument("--max-run-bytes",type=int,default=256*1024*1024)
    parser.add_argument("--max-pages",type=int)
    parser.add_argument("--max-records-total",type=int)
    parser.add_argument("--max-requests",type=int)
    parser.add_argument("--retries",type=int)
    parser.add_argument("--execution-time",action="store_true")
    args = parser.parse_args(argv)
    try:
        selected = ()
        if args.selection:
            if not args.live: raise EvidenceError("selection_requires_explicit_live_mode")
            from .collect_evidence import load_input
            doc = load_input(args.selection)
            if not isinstance(doc,dict) or set(doc)!={"awards"} or not isinstance(doc["awards"],list): raise EvidenceError("invalid_research_selection")
            selected = tuple(SelectedAward(**a) for a in doc["awards"])
        overrides = {name:getattr(args,name) for name in ("max_pages","max_records_total","max_requests","retries") if getattr(args,name) is not None}
        if overrides and not args.live:
            raise EvidenceError("collection_limit_overrides_require_live_mode")
        collection = CollectionLimits(**overrides)
        if args.demo:
            collection = replace(collection,max_awards=1,max_records_per_source_award=40,max_records_total=100,retries=1,pace_seconds=0.0,backoff_seconds=0.0)
        config = ResearchConfig(mode="demo" if args.demo else "live" if args.live else "existing",collection=collection,
            selected_awards=selected,demo_cases=tuple(args.demo_case or CASES) if args.demo else (),demo_damage=args.demo_damage,
            claim_ids=tuple(sorted(args.claim_id or ())),max_claims=args.max_claims,max_output_bytes=args.max_output_bytes,max_run_bytes=args.max_run_bytes)
        if args.demo_case and not args.demo: raise EvidenceError("synthetic_cases_require_demo_mode")
        report,location = run_research(args.run_dir,config,evidence=args.evidence or (),resume=args.resume,retry_failed=args.retry_failed,
            execution_time=args.execution_time,progress=lambda e:print(canonical(e),file=sys.stderr))
        print(canonical({"run_id":report.run_id,"substantive_sha256":report.substantive_sha256,"technical_success":report.technical_success,
                         "evidentiary_complete":report.evidentiary_complete,"manifest":location.name,"exit_code":report.exit_code}))
        print(f"Technical completion: {report.technical_success}; evidentiary completeness: {report.evidentiary_complete}. Inspect quality gates and review packets.",file=sys.stderr)
        return report.exit_code
    except KeyboardInterrupt:
        print(canonical({"error_code":"research_interrupted","exit_code":130})); return 130
    except (OSError,ValueError,TypeError,KeyError,IndexError,RecursionError) as exc:
        code = exc.code if isinstance(exc,EvidenceError) and re.fullmatch(r"[a-z0-9_]{1,100}",exc.code) else "invalid_research_input_or_storage"
        print(canonical({"error_code":code,"exit_code":2}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
