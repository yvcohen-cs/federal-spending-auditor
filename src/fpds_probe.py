"""Explicit bounded public probe through C3, never a competing HTTP collector."""
import argparse
import sys

from .collect_evidence import load_input
from .collection import CollectionLimits, SelectedAward, collect_selected
from .evidence_io import EvidenceError, canonical, digest
from .pilot_store import PilotStore
from .research_models import implementation_digest


def probe(path,awards,*,live=False,max_pages=3,resume=False,transport=None,profile="live"):
    if not live or type(max_pages) is not int or not 1<=max_pages<=3 or not 1<=len(awards)<=3:
        raise EvidenceError("explicit_bounded_fpds_probe_required")
    if transport is not None and not profile.startswith("fixture:"):
        raise EvidenceError("explicit_synthetic_probe_profile_required")
    if transport is None and profile!="live":
        raise EvidenceError("fixture_transport_required")
    for a in awards:
        if a.piid is None or a.agency_id is None or (a.parent_piid is None)!=(a.parent_agency_id is None):
            raise EvidenceError("explicit_native_probe_identity_required")
    if len(set(awards))!=len(awards):
        raise EvidenceError("duplicate_probe_selection")
    limits=CollectionLimits(max_awards=1,max_pages=max_pages,max_records_per_source_award=30,
        max_records_total=30,max_requests=max_pages,page_size=10,retries=0,timeout_seconds=10.0,
        pace_seconds=0.5,max_response_bytes=1024*1024)
    plan={"schema_type":"FPDSProbePlan","schema_version":1,"config":{"max_run_bytes":32*1024*1024},
          "awards":[a.to_dict() for a in awards],"limits":limits.to_dict(),"profile":profile,
          "implementation_sha256":implementation_digest(),
          "maximum_requests":len(awards)*max_pages,"maximum_continuations_per_query":max_pages-1}
    with PilotStore(path,plan,resume) as store:
        results=[]
        for index,a in enumerate(awards):
            child=store.path/f"query-{index:03d}"
            summary=collect_selected(child,(a,),limits=limits,sources=("fpds",),profile=profile,
                transport=transport,resume=resume and child.exists(),stop_on_context_mismatch=True,**({"sleep":lambda _:None} if transport else {}))
            task=summary["tasks"][0]
            contexts=task["action_context_counts"]
            result={"query_index":index,"collection":f"query-{index:03d}","summary":summary,
                "records_within_selected_context":None if not task["returned_rows"] else set(contexts)=={"query_bound_candidate"},
                "historical_completeness":"unknown","freshness":"unknown"}
            results.append(result)
            # No further queries after unexpected protocol, native context or
            # transport errors. Empty feeds are inconclusive, not a bypass cue.
            expected_bound=task["error_code"] in ("page_limit","record_limit","request_limit","record_request_budget")
            if task["error_code"] and not expected_bound or contexts and set(contexts)!={"query_bound_candidate"}:
                break
        report={"schema_type":"FPDSProbeReport","schema_version":1,"plan_sha256":digest(plan),
            "profile":profile,"selected_queries":len(awards),"executed_queries":len(results),
            "request_slots_reserved":sum(r["summary"]["requests_reserved"] for r in results),
            "results":results,"limitations":["bounded_observation_not_universal_contract","query_scope_not_universally_verified","pagination_not_history"]}
        names=store.inventory()
        count=sum(n.startswith("probe-report-") and n.endswith(".json") for n in names)
        if count>=20:
            raise EvidenceError("probe_invocation_limit")
        store.write(f"probe-report-{count:03d}.json",{"report":report,"substantive_sha256":digest(report)})
        return report,1


def main(argv=None):
    parser=argparse.ArgumentParser(description="At most 3 public FPDS queries / 9 HTTP requests; no automatic retries.")
    parser.add_argument("--live",action="store_true",required=True)
    parser.add_argument("--selection",required=True)
    parser.add_argument("--run-dir",required=True)
    parser.add_argument("--max-pages",type=int,default=3)
    parser.add_argument("--resume",action="store_true")
    args=parser.parse_args(argv)
    try:
        doc=load_input(args.selection)
        if not isinstance(doc,dict) or set(doc)!={"awards"} or not isinstance(doc["awards"],list):
            raise EvidenceError("invalid_probe_selection")
        awards=tuple(SelectedAward.from_dict(a) if "schema_type" in a else SelectedAward(**a) for a in doc["awards"])
        report,code=probe(args.run_dir,awards,live=args.live,max_pages=args.max_pages,resume=args.resume)
        print(canonical({"substantive_sha256":digest(report),"executed_queries":report["executed_queries"],
            "request_slots_reserved":report["request_slots_reserved"],"exit_code":code}))
        return code
    except KeyboardInterrupt:
        return 130
    except (ValueError,TypeError,OSError,KeyError,IndexError):
        print(canonical({"error_code":"fpds_probe_failed_preserve_evidence","exit_code":2}),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
