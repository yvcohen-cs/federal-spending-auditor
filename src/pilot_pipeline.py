"""Opt-in Phase 4A pilot. Uses C3/C4/C7; no new joins, financial rules or HTML."""
from __future__ import annotations

import argparse
import re
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from .collection import CollectionLimits, SelectedAward, collect_selected
from .collection_sources import HTTPTransport
from .evidence_ingestion import ValidationStatus, inspect_directory
from .evidence_io import EvidenceError, canonical, digest, strict_json
from .financial_models import FinancialRun
from .matching_ingestion import match_collection
from .matching_models import MatchRunSummary, IdentifierState
from .pilot_evaluation import audit_subset, evaluate, reasons, report_text, wrap_report
from .pilot_sampling import PilotConfig, VERSION, amount_band, frame_requests, select_sample, text
from .pilot_store import PilotStore
from .research_demo import CASES, demo_case
from .research_models import ResearchConfig, StageState, implementation_digest
from .research_pipeline import run_research
from .review_packet_io import read_bundle


def limits(requests=1):
    return CollectionLimits(max_awards=1,max_pages=1,max_records_total=10*requests,
        max_records_per_source_award=10,max_requests=requests,retries=0,
        max_response_bytes=1024*1024,timeout_seconds=10.0,pace_seconds=0.5)


def pilot_plan(config):
    return {"schema_type":"PilotPlan","schema_version":1,"config":config.to_dict(),
        "requests":frame_requests(config) if config.mode=="live" else [],
        "protocol":"docs/pilot-validation.md#predeclared-selection-and-measurement"}


def synthetic_rows():
    rows=[]
    for n,case in enumerate(CASES):
        award,_=demo_case(case)
        source={"generated_internal_id":award.generated_id,"synthetic_case":case}
        rows.append({"generated_id":award.generated_id,"agency":f"SYNTH-AGENCY-{n%3}",
            "kind":("A","B","C","D")[n%4],"period":str(2024+n%2),
            "value_band":("under_100k","100k_to_1m","1m_plus")[n%3],
            "modifications":"known_multiple" if case=="modifications" else "unknown",
            "source_row":source,"frame_ref":f"synthetic-authored:{case}","case":case})
    return rows


def collect_frame(store, config, *, transport=None, sleep=time.sleep, read_only=False):
    if config.mode=="synthetic":
        return synthetic_rows(),{"planned_queries":0,"reserved_queries":0,"successful_queries":0,"profile":"synthetic"}
    transport=transport or HTTPTransport(replace(limits(),max_response_bytes=config.max_response_bytes).to_dict())
    rows=[]
    status={"planned_queries":8,"reserved_queries":0,"successful_queries":0,"profile":"live","observations":[]}
    stop=False
    for n,request in enumerate(frame_requests(config)):
        prefix=f"frame-{n:03d}"
        names=store.inventory()
        if prefix+".request.json" in names:
            if digest(store.json(prefix+".request.json"))!=digest(request):
                raise EvidenceError("pilot_frame_query_changed")
        elif stop or read_only:
            continue
        else:
            store.write(prefix+".request.json",request)  # Durable attempt reservation.
        status["reserved_queries"]+=1
        if prefix+".response.json" in names:
            meta=store.json(prefix+".response.json")
            raw=store.read(prefix+".body") if meta["body_sha256"] is not None else None
            if raw is not None and digest_bytes(raw)!=meta["body_sha256"]:
                raise EvidenceError("pilot_frame_hash_conflict")
        elif prefix+".request.json" in names:
            # A reserved, uncertain request is never automatically replayed.
            meta={"status":None,"body_complete":False,"error_code":"uncertain_reserved_request",
                  "retrieved_at_utc":None,"body_sha256":None}
            raw=None
        else:
            sleep(0.5)
            meta,raw=transport(request,n)
            if raw is not None and len(raw)>config.max_response_bytes:
                raw=raw[:config.max_response_bytes]
                meta={**meta,"body_complete":False,"error_code":"response_size_limit"}
            if raw is not None:
                store.write_bytes(prefix+".body",raw)
            meta={**meta,"body_sha256":digest_bytes(raw) if raw is not None else None,
                  "representation":"application_response_bytes_not_http_wire_capture"}
            store.write(prefix+".response.json",meta)
        stop=stop or meta["status"] in (401,403,429) or meta["error_code"] in ("tls_error","connection_error","timeout","request_error","uncertain_reserved_request")
        observation={"reference":prefix+".response.json","status":meta["status"],"error_code":meta["error_code"],"rows":0}
        status["observations"].append(observation)
        if meta["error_code"] or meta["status"] is None or not 200<=meta["status"]<300 or not meta["body_complete"]:
            continue
        from .evidence import _timestamp
        try:
            if meta["retrieved_at_utc"] is None:
                raise ValueError("missing timestamp")
            _timestamp(meta["retrieved_at_utc"])
        except (ValueError,TypeError):
            observation["error_code"]="missing_or_invalid_frame_provenance"
            continue
        try:
            body=strict_json(raw)
            found=body["results"]
            if not isinstance(found,list) or len(found)>config.frame_limit or any(not isinstance(r,dict) for r in found):
                raise ValueError("bounded frame rows required")
            page=body["page_metadata"]
            if not isinstance(page,dict) or type(page.get("hasNext")) is not bool:
                raise ValueError("supported pagination metadata required")
        except (ValueError,TypeError,KeyError):
            observation["error_code"]="unsupported_frame_response"
            continue
        status["successful_queries"]+=1
        observation["rows"]=len(found)
        observation["has_next"]=page["hasNext"]
        filters=request["parameters"]["filters"]
        for index,row in enumerate(found):
            rows.append({"generated_id":row.get("generated_internal_id"),
                "agency":text(row.get("Awarding Agency")) or "unknown",
                "kind":filters["award_type_codes"][0],"period":filters["time_period"][0]["end_date"][:4],
                "value_band":amount_band(row.get("Award Amount")),"modifications":"unknown",
                "source_row":row,"frame_ref":prefix+f".body#/results/{index}"})
    return rows,status


def digest_bytes(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def bridge_selection(path, generated_id):
    run=match_collection(path)
    contexts=set()
    references=[]
    for record in run.records:
        if record.source!="usaspending":
            continue
        components=(record.piid,record.agency,record.parent_piid,record.parent_agency)
        if any(c.state is not IdentifierState.VALID for c in components[:2]):
            return None,run.substantive_sha256,[]
        if any(c.state not in (IdentifierState.VALID,IdentifierState.ABSENT) for c in components[2:]):
            return None,run.substantive_sha256,[]
        context=tuple(c.value for c in components)
        if (context[2] is None)!=(context[3] is None):
            return None,run.substantive_sha256,[]
        contexts.add(context)
        references.append(record.record_id)
    if len(contexts)!=1:
        return None,run.substantive_sha256,references
    piid,agency,parent,parent_agency=next(iter(contexts))
    return SelectedAward(generated_id=generated_id,piid=piid,agency_id=agency,
        parent_piid=parent,parent_agency_id=parent_agency),run.substantive_sha256,sorted(references)


def analyze(store, index, row, run, evidence_path):
    stages={s.stage:s for s in run.stages if s.state is StageState.COMPLETED}
    def document(stage,leaf,model):
        if stage not in stages:
            return None
        refs=[a for a in stages[stage].artifacts if a.name.endswith("/"+leaf)]
        if len(refs)!=1:
            raise EvidenceError("pilot_requires_one_collection_per_slot")
        with store.reader() as root:
            raw=root.read(f"award-{index:03d}/research/"+refs[0].storage_path).data
        return model.from_dict(strict_json(raw))
    identity=document("identity","identity.json",MatchRunSummary)
    finance=document("finance","finance.json",FinancialRun)
    scan=inspect_directory(evidence_path)
    if not scan.complete:
        raise EvidenceError("pilot_invalid_case_evidence")
    # Unsupported response parsing must not hide successful collection or make
    # the integrity denominator look perfect by dropping the failed slots.
    summary_entry=next((e for e in scan.entries if e.relative_path=="c3_summary.json" and e.status is ValidationStatus.VERIFIED),None)
    if summary_entry is None:
        raise EvidenceError("pilot_unvalidated_collection_summary")
    with store.reader() as root:
        rel=Path(evidence_path).relative_to(store.path).as_posix()+"/c3_summary.json"
        snap=root.read(rel)
        if snap.byte_sha256!=summary_entry.byte_sha256:
            raise EvidenceError("pilot_collection_summary_changed")
        summary=strict_json(snap.data)
        http_sources=set()
        for entry in scan.entries:
            if re.fullmatch(r"c3_attempt_[0-9]{6}\.json",entry.relative_path) and entry.status is ValidationStatus.VERIFIED:
                raw=root.read(Path(evidence_path).relative_to(store.path).as_posix()+"/"+entry.relative_path)
                if raw.byte_sha256!=entry.byte_sha256:
                    raise EvidenceError("pilot_source_metadata_changed")
                meta=strict_json(raw.data)
                if meta["status"] is not None and 200<=meta["status"]<300 and meta["body_complete"]:
                    http_sources.add(meta["request"]["source"])
    observed=[e for e in scan.entries if e.observation]
    metrics={"successful_sources":sum(t["pages"]>0 for t in summary["tasks"]),"http_success_sources":len(http_sources),
        "two_http_responses":int(http_sources=={"usaspending","fpds"}),
        "two_nonempty_sources":int({t["source"] for t in summary["tasks"] if t["returned_rows"]>0}=={"usaspending","fpds"}),
        "row_occurrences":sum(len(e.observation.records) for e in observed),
        "provenance_rows":sum(len(e.observation.records) for e in observed if e.status is ValidationStatus.VERIFIED),
        "verified_entries":sum(e.status is ValidationStatus.VERIFIED for e in scan.entries),
        "evidence_entries":len(scan.entries),
        **{"validation_"+v.value:sum(e.status is v for e in scan.entries) for v in ValidationStatus},
        "distinct_record_contents":len(identity.records) if identity else 0,
        "observation_contexts":len({e.observation.observation_id for e in observed if e.observation.observation_id}),
        "numeric_comparisons":sum(d.difference_usa_minus_fpds is not None for d in finance.results) if finance else 0,
        "unequal":sum(d.difference_usa_minus_fpds not in (None,"0") for d in finance.results) if finance else 0,
        "packets":0}
    refs=[]
    if "packets" in stages:
        for a in stages["packets"].artifacts:
            if a.name.endswith("/packets.json"):
                folder=Path(f"award-{index:03d}/research")/Path(a.storage_path).parent
                packets,_=read_bundle(store.path/folder)
                metrics["packets"]+=len(packets.packets)
                refs.append((folder/"review.html").as_posix())
    counts={k:dict(Counter(d.status.value for d in identity.decisions if d.claim==k)) if identity else {} for k in ("award_association","action_equivalence")}
    counts["finance"]=dict(Counter(d.status.value for d in finance.results)) if finance else {}
    prompts=reasons(identity or SimpleNamespace(decisions=()),finance or SimpleNamespace(results=()))
    if not run.technical_success:
        prompts.append({"lane":"coverage_data_quality","code":"processing_incomplete"})
    return {"slot":index,"generated_id":row["generated_id"],"stratum":row["stratum"],"frame_refs":row["frame_refs"],
        "technical_success":run.technical_success,"research_digest":run.substantive_sha256,
        "metrics":metrics,"counts":counts,"reasons":prompts,"packet_refs":refs,
        "diagnostics":[s.diagnostic.to_dict() for s in run.stages if s.diagnostic],
        "evidence_exclusions":[{"path":e.relative_path,"status":e.status.value,"error_code":e.error_code} for e in scan.entries if e.status is not ValidationStatus.VERIFIED],
        "source_records":{t["source"]:{"rows":t["returned_rows"],"status":t["status"],"query_scope":t["query_scope"]} for t in summary["tasks"]}}


def execute_case(store,config,index,row,*,resume=False,retry_failed=False):
    folder=f"award-{index:03d}"
    store.mkdir(folder)
    research=store.path/folder/"research"
    if config.mode=="synthetic":
        child=ResearchConfig(mode="demo",demo_cases=(row["case"],),collection=replace(limits(10),
            max_pages=2,max_records_per_source_award=40,retries=1,pace_seconds=0.0,backoff_seconds=0.0))
        child_resume=research.exists() and resume
        run,_=run_research(research,child,resume=child_resume,retry_failed=retry_failed and child_resume)
        evidence_path=research/"evidence"/row["case"]
    else:
        discovery=store.path/folder/"discovery"
        time.sleep(0.5)
        collect_selected(discovery,(SelectedAward(generated_id=row["generated_id"]),),limits=limits(),
            sources=("usaspending",),resume=discovery.exists() and resume)
        award,sha,refs=bridge_selection(discovery,row["generated_id"])
        bridge={"schema_version":1,"input_matching_sha256":sha,"record_refs":refs,
            "selection":award.to_dict() if award else None,"basis":"supported_C4_transaction_identifier_components_not_award_ID_splitting"}
        if folder+"/bridge.json" in store.inventory():
            if digest(store.json(folder+"/bridge.json"))!=digest(bridge):
                raise EvidenceError("pilot_discovery_bridge_changed")
        else:
            store.write(folder+"/bridge.json",bridge)
        child=ResearchConfig(mode="live",selected_awards=(award,),collection=limits(2)) if award else ResearchConfig(mode="existing")
        if award:
            time.sleep(0.5)
        child_resume=research.exists() and resume
        run,_=run_research(research,child,evidence=() if award else (discovery,),
            resume=child_resume,retry_failed=retry_failed and child_resume)
        evidence_path=research/"evidence/selected" if award else discovery
    return analyze(store,index,row,run,evidence_path)


def run_pilot(path,config,*,resume=False,retry_failed=False,frame_transport=None,sleep=time.sleep):
    if config.implementation_sha256!=implementation_digest():
        raise EvidenceError("pilot_implementation_changed")
    if retry_failed and not resume:
        raise EvidenceError("pilot_retry_requires_resume")
    plan=pilot_plan(config)
    with PilotStore(path,plan,resume) as store:
        for name in store.inventory():
            if not (name in ("pilot-plan.json","sample.json") or re.fullmatch(r"frame-00[0-7]\.(?:request\.json|response\.json|body)",name)
                    or re.fullmatch(r"pilot-report-[0-9]{3}\.(?:json|txt)",name) or re.fullmatch(r"award-[0-9]{3}/.+",name)):
                raise EvidenceError("unexpected_pilot_artifact")
        rows,frame_status=collect_frame(store,config,transport=frame_transport,sleep=sleep)
        sample=select_sample(rows,config)
        if "sample.json" in store.inventory():
            if digest(store.json("sample.json"))!=digest(sample):
                raise EvidenceError("pilot_sample_changed")
        else:
            store.write("sample.json",sample)
        cases=[]
        for index,row in enumerate(sample["selected"]):
            try:
                case=execute_case(store,config,index,row,resume=resume,retry_failed=retry_failed)
            except (EvidenceError,OSError,ValueError,TypeError,KeyError,IndexError):
                case={"slot":index,"generated_id":row["generated_id"],"stratum":row["stratum"],
                    "frame_refs":row["frame_refs"],"technical_success":False,"metrics":None,
                    "reasons":[{"lane":"coverage_data_quality","code":"processing_failed_inspect_preserved_artifacts"}]}
            cases.append(case)
        report=compile_report(store,config,sample,cases,frame_status)
        if config.implementation_sha256!=implementation_digest():
            raise EvidenceError("pilot_implementation_changed")
        names=store.inventory()
        count=sum(p.startswith("pilot-report-") and p.endswith(".json") for p in names)
        if count>=20:
            raise EvidenceError("pilot_invocation_limit")
        prefix=f"pilot-report-{count:03d}"
        store.write_bytes(prefix+".txt",report_text(report).encode())
        store.write(prefix+".json",wrap_report(report))
        exit_code=2 if not cases or any(not c["technical_success"] for c in cases) else 1
        return report,exit_code


def compile_report(store,config,sample,cases,frame_status):
    # All durable non-report bytes bind the evaluation; invocation reports
    # are operational append-only outputs, excluded for resume determinism.
    inventory={p:h for p,h in store.inventory().items() if not p.startswith("pilot-report-") and "/research-run-" not in p}
    bytes_used=sum(len(store.read(p)) for p in inventory)
    reserved=sum(1 for p in inventory if p.endswith(".request.json") and p.startswith("frame-"))
    reserved+=sum(len(store.json(p)["events"])+int(store.json(p)["pending"] is not None) for p in inventory if p.endswith("/c3_checkpoint.json"))
    resources={"reserved_collection_and_frame_slots":reserved,"managed_bytes_excluding_invocation_reports":bytes_used,
               "live_request_slots_reserved":reserved if config.mode=="live" else 0,
               "maximum_live_request_slots":0 if config.mode=="synthetic" else 8+3*config.target}
    evaluation=evaluate(cases,len(sample["selected"]),frame_status,resources)
    recommendations=[]
    if any(e.get("error_code")=="unsupported_fpds_next_parameters" for c in cases for e in c.get("evidence_exclusions",[])):
        recommendations.append("Validate documented FPDS VERSION pagination semantics and scoped allowlisting before expanding comparisons")
    if any(c.get("counts",{}).get("award_association",{}).get("ambiguous_match",0) for c in cases):
        recommendations.append("Validate authoritative absent-parent and repeated-modification identity semantics; preserve conservative refusal meanwhile")
    if frame_status["successful_queries"]<frame_status["planned_queries"]:
        recommendations.append("Validate official source availability and supported search responses before expanding the pilot")
    if evaluation["rates"]["source_retrieval_success"]["count"]<2*len(cases):
        recommendations.append("Improve source/identifier availability before financial interpretation")
    recommendations.extend(["Obtain authoritative modification/revision histories and refresh alignment", "Broaden the verified sampling frame before claiming wider coverage"])
    report={"schema_type":"PilotReport","schema_version":1,"version":VERSION,"mode":config.mode,
        "plan_sha256":digest(store.plan),"evaluation_implementation_sha256":implementation_digest(),"sample":sample,"evaluation":evaluation,"cases":cases,
        "audit_candidates":audit_subset(cases),"evidence_inventory":inventory,
        "assumptions":["C3 request context is selection context, not authoritative cross-source identity", "No complete histories, freshness alignment or source authenticity established"],
        "human_interpretation":"not supplied; generated review candidates require human inspection",
        "recommendations":recommendations}
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description="Explicit bounded diversity pilot; no misconduct inference or publication.")
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--live",action="store_true")
    modes.add_argument("--synthetic",action="store_true")
    parser.add_argument("--run-dir",required=True)
    parser.add_argument("--target",type=int,default=24)
    parser.add_argument("--seed",default="phase4a-v1")
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--retry-failed",action="store_true")
    args=parser.parse_args(argv)
    try:
        config=PilotConfig(mode="live" if args.live else "synthetic",target=args.target,seed=args.seed,
                           implementation_sha256=implementation_digest())
        report,code=run_pilot(args.run_dir,config,resume=args.resume,retry_failed=args.retry_failed)
        print(canonical({"substantive_sha256":digest(report),"selected":report["evaluation"]["selected_awards"],"mode":config.mode,"exit_code":code}))
        return code
    except KeyboardInterrupt:
        print(canonical({"error_code":"pilot_interrupted","exit_code":130}))
        return 130
    except (ValueError,TypeError,OSError,KeyError,IndexError,RecursionError):
        print(canonical({"error_code":"pilot_failed_inspect_preserved_artifacts","exit_code":2}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
