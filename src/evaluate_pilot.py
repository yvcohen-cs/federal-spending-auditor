"""Read-only re-evaluation of preserved pilot evidence; never collect or resume C7.

This validates existing C7 commits with unchanged C1-C7 contracts. It records the
current evaluator fingerprint separately from the original execution fingerprint.
"""
import argparse
from pathlib import Path

from .evidence_io import EvidenceError, EvidenceRoot, canonical, digest, strict_json
from .pilot_evaluation import report_text, wrap_report
from .pilot_pipeline import analyze, collect_frame, compile_report, pilot_plan
from .pilot_sampling import PilotConfig, select_sample
from .pilot_store import PilotStore
from .research_models import ResearchRun, StageState, implementation_digest
from .research_pipeline import check_sources, input_digest, verify_stage_semantics
from .research_store import ResearchStore
from .review_packet_io import outside


def validated_run(path, slot_root):
    with EvidenceRoot(path) as root:
        plan=strict_json(root.read("research-plan.json").data)
    with ResearchStore(path,plan,resume=True) as store:
        names=sorted(n for n in store.audit() if n.startswith("research-run-") and n.endswith(".json"))
        if not names:
            raise EvidenceError("pilot_missing_research_manifest")
        run=ResearchRun.from_dict(store.json(names[-1])["run"])
        if run.config.to_dict()!=plan["config"]:
            raise EvidenceError("pilot_research_config_conflict")
        expected=[]
        for source in plan["sources"]:
            location=Path(path)/source["path"] if source["managed"] else Path(source["path"])
            if ".." in location.parts or not location.is_relative_to(slot_root):
                raise EvidenceError("pilot_research_input_outside_slot")
            expected.append(str(location))
        if [i.location for i in run.inputs]!=expected:
            raise EvidenceError("pilot_research_input_location_conflict")
        check_sources(run.inputs)
        completed=[]
        for stage in run.stages:
            if stage.state is not StageState.COMPLETED:
                break
            sha=input_digest(run.config,stage.stage,() if stage.stage=="acquire" else run.inputs,completed)
            result=store.receipt(stage.stage,sha)
            if result!=stage:
                raise EvidenceError("pilot_research_commit_conflict")
            verify_stage_semantics(store,result,run.config,run.inputs,completed)
            completed.append(result)
        if len([n for n in store.audit() if n.startswith("stage-")])!=len(completed):
            raise EvidenceError("pilot_unreported_research_commits")
        return run


def evaluate_saved(source, destination):
    source=Path(source).absolute()
    target=outside(destination,(source,))
    with EvidenceRoot(source) as root:
        original=strict_json(root.read("pilot-plan.json").data)
    config=PilotConfig.from_dict(original["config"])
    if digest(original)!=digest(pilot_plan(config)):
        raise EvidenceError("unsupported_pilot_plan")
    with PilotStore(source,original,resume=True) as store:
        before=store.inventory()
        def forbidden(*args):
            raise EvidenceError("offline_evaluation_cannot_collect")
        rows,frame_status=collect_frame(store,config,transport=forbidden,read_only=True)
        sample=select_sample(rows,config)
        if digest(sample)!=digest(store.json("sample.json")):
            raise EvidenceError("pilot_sample_changed")
        cases=[]
        for index,row in enumerate(sample["selected"]):
            slot=source/f"award-{index:03d}"
            try:
                run=validated_run(slot/"research",slot)
                if len(run.inputs)!=1:
                    raise EvidenceError("pilot_requires_single_case_input")
                cases.append(analyze(store,index,row,run,run.inputs[0].location))
            except (ValueError,TypeError,OSError,KeyError,IndexError):
                cases.append({"slot":index,"generated_id":row["generated_id"],"stratum":row["stratum"],"frame_refs":row["frame_refs"],
                    "technical_success":False,"metrics":None,"reasons":[{"lane":"coverage_data_quality","code":"preserved_case_validation_failed"}]})
        report=compile_report(store,config,sample,cases,frame_status)
        if store.inventory()!=before:
            raise EvidenceError("pilot_source_changed_during_evaluation")
    plan={"schema_type":"PilotEvaluationPlan","schema_version":1,"config":config.to_dict(),
          "source_plan_sha256":digest(original),"evaluation_implementation_sha256":implementation_digest()}
    with PilotStore(target,plan) as output:
        # Operational location is separate from the deterministic report.
        output.write("evaluation-source.json",{"source_root":str(source)})
        output.write_bytes("pilot-report-000.txt",report_text(report).encode())
        output.write("pilot-report-000.json",wrap_report(report))
    return report,2 if not cases or any(not c["technical_success"] for c in cases) else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description="Offline evaluation only; C7 execution remains untouched.")
    parser.add_argument("--source",required=True)
    parser.add_argument("--run-dir",required=True)
    args=parser.parse_args(argv)
    try:
        report,code=evaluate_saved(args.source,args.run_dir)
        print(canonical({"substantive_sha256":digest(report),"exit_code":code,"mode":report["mode"]}))
        return code
    except KeyboardInterrupt:
        return 130
    except (ValueError,TypeError,OSError,KeyError,IndexError,RecursionError):
        print(canonical({"error_code":"saved_pilot_evaluation_failed","exit_code":2}))
        return 2


if __name__=="__main__":
    raise SystemExit(main())
