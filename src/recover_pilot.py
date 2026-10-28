"""Offline replay of a frozen Phase 4A sample into NEW C7 outputs; zero collection."""
import argparse
from pathlib import Path

from .collect_evidence import load_input
from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, parts
from .pilot_evaluation import report_text, wrap_report
from .pilot_pipeline import analyze, collect_frame, compile_report, pilot_plan
from .pilot_sampling import PilotConfig, select_sample
from .pilot_store import PilotStore
from .research_models import ResearchConfig, implementation_digest
from .research_pipeline import run_research
from .review_packet_io import outside


def recover(source,destination,baseline_path,*,resume=False,retry_failed=False):
    source=Path(source).absolute()
    target=outside(destination,(source,Path(baseline_path).absolute().parent))
    original=load_input(source/"pilot-plan.json")
    config=PilotConfig.from_dict(original["config"])
    if digest(original)!=digest(pilot_plan(config)):
        raise EvidenceError("unsupported_recovery_source_plan")
    baseline=load_input(baseline_path)
    if set(baseline)!={"report","substantive_sha256"} or digest(baseline["report"])!=baseline["substantive_sha256"]:
        raise EvidenceError("invalid_recovery_baseline_digest")
    before=baseline["report"]
    if before["plan_sha256"]!=digest(original) or before["version"]!="pilot-v1":
        raise EvidenceError("incompatible_recovery_baseline")
    if retry_failed and not resume:
        raise EvidenceError("recovery_retry_requires_resume")
    with PilotStore(source,original,resume=True) as original_store:
        inventory=original_store.inventory()
        substantive={p:h for p,h in inventory.items() if not p.startswith("pilot-report-") and "/research-run-" not in p}
        if substantive!=before["evidence_inventory"]:
            raise EvidenceError("recovery_source_changed_since_baseline")
        def forbidden(*args):
            raise EvidenceError("recovery_network_forbidden")
        rows,frame_status=collect_frame(original_store,config,transport=forbidden,read_only=True)
        sample=select_sample(rows,config)
        if digest(sample)!=digest(original_store.json("sample.json")) or digest(sample)!=digest(before["sample"]):
            raise EvidenceError("recovery_frozen_sample_conflict")
        plan={"schema_type":"PilotRecoveryPlan","schema_version":1,"config":config.to_dict(),
              "source_plan_sha256":digest(original),"baseline_sha256":baseline["substantive_sha256"],
              "implementation_sha256":implementation_digest(),"execution_mode":"offline_saved_evidence_recovery"}
        with PilotStore(target,plan,resume) as store:
            if "sample.json" in store.inventory():
                if digest(store.json("sample.json"))!=digest(sample):
                    raise EvidenceError("recovery_sample_changed")
            else:
                store.write("sample.json",sample)
            cases=[]
            for index,row in enumerate(sample["selected"]):
                folder=f"award-{index:03d}"
                old=load_input(source/folder/"research/research-plan.json")
                if len(old["sources"])!=1:
                    raise EvidenceError("recovery_requires_single_source_collection")
                descriptor=old["sources"][0]
                if descriptor["managed"]:
                    evidence=source/folder/"research"/Path(*parts(descriptor["path"]))
                else:
                    evidence=Path(descriptor["path"])
                    if evidence!=source/folder/"discovery":
                        raise EvidenceError("recovery_external_source_outside_slot")
                with EvidenceRoot(evidence) as root:
                    from .evidence_io import strict_json
                    collection= strict_json(root.read("c3_plan.json").data)
                if len(collection["awards"])!=1 or collection["awards"][0]["generated_id"]!=row["generated_id"]:
                    raise EvidenceError("recovery_award_selection_conflict")
                store.mkdir(folder)
                child=store.path/folder/"research"
                child_resume=resume and child.exists()
                try:
                    run,_=run_research(child,ResearchConfig(mode="existing"),evidence=(evidence,),
                        resume=child_resume,retry_failed=retry_failed and child_resume)
                    if run.exit_code==130:
                        raise KeyboardInterrupt
                    cases.append(analyze(store,index,row,run,evidence))
                except (ValueError,TypeError,OSError,KeyError,IndexError):
                    cases.append({"slot":index,"generated_id":row["generated_id"],"stratum":row["stratum"],"frame_refs":row["frame_refs"],
                        "technical_success":False,"metrics":None,"reasons":[{"lane":"coverage_data_quality","code":"recovery_processing_failed"}]})
            after=compile_report(store,config,sample,cases,frame_status,output_prefixes=("pilot-report-","recovery-report-","comparison-"))
            after["execution_mode"]="offline_saved_evidence_recovery"
            after["source_evidence_inventory"]=substantive
            after["evaluation"]["resources"]["maximum_live_request_slots"]=0
            comparison={"schema_type":"PilotRecoveryComparison","schema_version":1,"baseline_sha256":baseline["substantive_sha256"],
                "before":before["evaluation"],"after":after["evaluation"],"same_frozen_sample":True,
                "additional_http_requests":0,"history":"unknown","freshness":"unknown"}
            # Original collection summaries stay as historical facts. Current
            # parsed-source counts come from C2 observations with unchanged definitions.
            names=store.inventory()
            count=sum(n.startswith("recovery-report-") and n.endswith(".json") for n in names)
            if count>=20:
                raise EvidenceError("recovery_invocation_limit")
            prefix=f"recovery-report-{count:03d}"
            if original_store.inventory()!=inventory:
                raise EvidenceError("recovery_original_evidence_changed")
            if implementation_digest()!=plan["implementation_sha256"]:
                raise EvidenceError("recovery_implementation_changed")
            store.write_bytes(prefix+".txt",report_text(after).encode())
            store.write(prefix+".json",wrap_report(after))
            store.write(f"comparison-{count:03d}.json",comparison)
            return after,comparison,2 if not cases or any(not c["technical_success"] for c in cases) else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description="Offline frozen pilot recovery; no collection, no mutation of the source pilot.")
    parser.add_argument("--source",required=True)
    parser.add_argument("--baseline-report",required=True)
    parser.add_argument("--run-dir",required=True)
    parser.add_argument("--resume",action="store_true")
    parser.add_argument("--retry-failed",action="store_true")
    args=parser.parse_args(argv)
    try:
        report,comparison,code=recover(args.source,args.run_dir,args.baseline_report,resume=args.resume,retry_failed=args.retry_failed)
        print(canonical({"substantive_sha256":digest(report),"additional_http_requests":0,"selected":report["evaluation"]["selected_awards"],"exit_code":code}))
        return code
    except KeyboardInterrupt:
        return 130
    except (ValueError,TypeError,OSError,KeyError,IndexError):
        print(canonical({"error_code":"pilot_recovery_failed_preserve_artifacts","exit_code":2}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
