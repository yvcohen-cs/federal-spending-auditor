"""Count-based evaluation and independent research lanes; no risk/probability model."""
from collections import Counter
from decimal import Decimal, ROUND_HALF_EVEN

from .evidence_io import canonical, digest


def rate(numerator, denominator):
    if type(numerator) is not int or type(denominator) is not int or not 0<=numerator<=denominator:
        raise ValueError("invalid metric denominator")
    return {"count":numerator,"denominator":denominator,"percent":None if denominator==0 else
            str((Decimal(numerator)*100/denominator).quantize(Decimal("0.01"),rounding=ROUND_HALF_EVEN))}


def reasons(identity, finance, coverage_unknown=True):
    result=[]
    if any(d.status.value=="ambiguous_match" for d in identity.decisions):
        result.append({"lane":"identity_clarification","code":"ambiguous_native_identity"})
    if any(d.status.value in ("insufficient_evidence","unresolved_discrepancy") for d in identity.decisions):
        result.append({"lane":"identity_clarification","code":"identity_evidence_unresolved"})
    if any(d.difference_usa_minus_fpds not in (None,"0") for d in finance.results):
        result.append({"lane":"financial_question","code":"unequal_compatible_saved_values"})
    if any(d.status.value=="insufficient_evidence" for d in finance.results):
        result.append({"lane":"coverage_data_quality","code":"insufficient_financial_evidence"})
    if coverage_unknown:
        result.append({"lane":"coverage_data_quality","code":"history_and_freshness_unknown"})
    return result


def evaluate(cases, selected_count, frame_status, resources):
    completed=[c for c in cases if c.get("metrics") is not None]
    m=Counter()
    counts={"award_association":Counter(),"action_equivalence":Counter(),"finance":Counter()}
    for c in completed:
        m.update(c["metrics"])
        for kind in counts:
            counts[kind].update(c["counts"][kind])
    comparisons=m["numeric_comparisons"]
    metrics={
        "awards_with_two_nonempty_sources":rate(m["two_nonempty_sources"],selected_count),
        "awards_with_two_http_responses":rate(m["two_http_responses"],selected_count),
        "source_retrieval_success":rate(m["successful_sources"],2*selected_count),
        "source_http_response_success":rate(m["http_success_sources"],2*selected_count),
        "row_provenance_sufficient":rate(m["provenance_rows"],m["row_occurrences"]),
        "evidence_integrity_verified_entries":rate(m["verified_entries"],m["evidence_entries"]),
        "award_identity_match":rate(counts["award_association"]["verified_match"],sum(counts["award_association"].values())),
        "action_identity_match":rate(counts["action_equivalence"]["verified_match"],sum(counts["action_equivalence"].values())),
        "financial_numeric_comparability":rate(comparisons,sum(counts["finance"].values())),
        "exact_observed_agreement":rate(counts["finance"]["verified_match"],comparisons),
        "unequal_comparable_observations":rate(m["unequal"],comparisons),
        "insufficient_financial_evidence":rate(counts["finance"]["insufficient_evidence"],sum(counts["finance"].values())),
        "unknown_or_incomplete_history":rate(selected_count,selected_count),
        "unknown_source_freshness":rate(selected_count,selected_count),
        "technical_completion":rate(sum(c["technical_success"] for c in completed),selected_count),
    }
    return {"selected_awards":selected_count,"evaluated_award_slots":len(completed),
            "processing_failures":sum(not c.get("technical_success",False) for c in cases),
            "frame_status":frame_status,"rates":metrics,
            "identity_and_financial_counts":{k:dict(sorted(v.items())) for k,v in counts.items()},
            "evidence_counts":dict(sorted(m.items())),"resources":resources,
            "packets_generated":m["packets"],"missing_processing_results":selected_count-len(completed)}


def audit_subset(cases):
    """At most three deterministic, outcome-diverse review candidates; no claims of human verification."""
    selected=[]
    seen=set()
    for case in cases:
        signature=tuple((r["lane"],r["code"]) for r in case.get("reasons",[]))
        if signature not in seen and len(selected)<3:
            selected.append(case)
            seen.add(signature)
    return selected


def report_text(report):
    out=["Phase 4A pilot — narrowly scoped saved observations", "",
         f"Mode: {report['mode']}; selected: {report['evaluation']['selected_awards']}; target: {report['sample']['target']}.",
         "Diversity sample; no population inference or misconduct classification.",
         "Source facts are in preserved C3 evidence; counts below are derived measurements.",
         "Interpretations/alternative explanations are research prompts, never source facts.", ""]
    for name,value in report["evaluation"]["rates"].items():
        percentage="undefined" if value["percent"] is None else value["percent"]+"%"
        out.append(f"{name}: {value['count']}/{value['denominator']} ({percentage})")
    out.extend(["", "Review candidates (generated summaries; human inspection is separate):"])
    for c in report["audit_candidates"]:
        out.extend([f"Slot {c['slot']}: {c['generated_id']}",
            f"Selection stratum: {canonical(c['stratum'])}; frame references: {canonical(c['frame_refs'])}",
            f"Records/context: {canonical(c.get('source_records',{}))}",
            f"Conclusions: {canonical(c.get('counts',{}))}; numeric comparisons: {(c.get('metrics') or {}).get('numeric_comparisons','unknown')}",
            "Identifiers: native PIID, agency, parent and modification/transaction context in C4/C6; no name-based joins.",
            f"C6 packets: {canonical(c.get('packet_refs',[]))}",
            "Cannot establish complete histories, current revision alignment or authenticity from hashes.",
            "Next: inspect C6 evidence links; verify parent/action context and incremental signed-date obligations; obtain missing revisions/history."])
    out.extend(["", "Alternative explanations: modifications, deobligations, FY/lifetime scope, signed/effective dates, reporting delays and source revisions.",
        "Phase 4B priorities: "+"; ".join(report["recommendations"]),
        "No live validation can establish synthetic control accuracy or population fraud prevalence."])
    return "\n".join(out)+"\n"


def wrap_report(report):
    return {"report":report,"substantive_sha256":digest(report)}
