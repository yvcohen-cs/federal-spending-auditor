"""Machine-checkable narrow-claim gates, separate from broad assurance."""
from __future__ import annotations

from .research_models import QualityGate, StageState


def quality_gates(stages,metrics):
    complete = all(s.state is StageState.COMPLETED for s in stages)
    verified = next((s.state is StageState.COMPLETED for s in stages if s.stage=="verify"),False)
    identity = metrics.get("identity_counts")
    finance = metrics.get("financial_counts")
    identity_good = bool(identity) and sum(v for k,v in identity.items() if k!="verified_match")==0 and identity.get("verified_match",0)>0 and metrics.get("records_without_identity_claim")==0
    finance_good = bool(finance) and sum(v for k,v in finance.items() if k!="verified_match")==0 and finance.get("verified_match",0)>0
    return (
        QualityGate(name="required_stages",state="passed" if complete else "failed",detail="Every required stage needs a durable validated commit; no skipped dependencies."),
        QualityGate(name="evidence_integrity",state="passed" if verified else "failed",detail="Saved bytes and declared provenance must pass C2/C3 validation."),
        QualityGate(name="committed_outputs",state="passed" if complete else "failed",detail="All required output hashes and stage dependencies must be checked."),
        QualityGate(name="critical_provenance",state="passed" if verified and metrics.get("excluded_artifacts")==0 and metrics.get("source_observation_gaps")==0 and metrics.get("usable_observations",0)>0 else "failed",detail="Missing/partial source observations cannot establish a complete research result."),
        QualityGate(name="identity_prerequisites",state="passed" if identity_good else "failed",detail="Ambiguous, unresolved and insufficient identity claims stay visible."),
        QualityGate(name="observed_financial_claims",state="passed" if finance_good else "failed",detail="This gate concerns compatible saved action values only, not current award finances."),
        QualityGate(name="historical_completeness",state="unknown",detail="Terminal pagination does not establish a complete action history or source-wide census."),
        QualityGate(name="source_freshness",state="unknown",detail="Source revision and refresh alignment are not established by retrieval timestamps."),
        QualityGate(name="source_authenticity",state="unknown",detail="Hashes are integrity references, not authenticity signatures."),
    )


def readable_summary(metrics):
    lines = ["Federal spending research summary — saved observations only.",
             "Stage results require their commit records; final technical status is in research-run-*.json.",
             "No fraud/misconduct inference, complete-history assurance or source authentication."]
    for key in ("selected_awards","selected_award_selection_rows","unknown_selection_scopes","response_observation_entries","response_observations","usable_observations","source_observation_gaps","retrieval_rows","distinct_retrieval_contents","records_without_identity_claim",
                "identity_counts","financial_counts","compatible_financial_comparisons","observed_agreements","differences_requiring_evidence","insufficient_financial_claims","packets_generated","excluded_artifacts"):
        lines.append(f"{key}: {metrics.get(key,'not computed')}")
    lines.extend(["Next checks: inspect the C6 packets, verify action/agency/parent context and obtain current official revision/refresh evidence.",
                  "Counts describe saved retrievals and narrow claims, not unique real-world contracts/payments. Selected awards count unique exact configuration rows only.",
                  "Review HTML: artifacts/packets/attempt-NNN/<input-label>/review.html; stage-packets.json identifies the committed attempt.",
                  "Coverage: history, source-wide completeness and freshness remain unknown; no history totals are inferred."])
    return "\n".join(lines)+"\n"
