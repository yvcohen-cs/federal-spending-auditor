"""Read-only, deterministic projections of revalidated C4/C5 observations."""
from __future__ import annotations

from pathlib import Path

from .evidence import ComparisonStatus
from .evidence_io import EvidenceError, EvidenceRoot, digest, strict_json
from .financial_ingestion import reconcile_collection
from .financial_models import FinancialRun
from .evidence_ingestion import inspect_directory
from .matching_models import ordered
from .review_packet_models import (AlternativeExplanation, CATALOG, ComparisonExplanation,
    EvidenceCitation, EvidenceLimitation, ExplanationState, RecommendedVerificationAction,
    ReviewedClaim, ReviewPacket, ReviewPacketManifest, SourceObservationSummary)


def read_financial_report(path):
    target = Path(path).absolute()
    with EvidenceRoot(target.parent, max_bytes=16*1024*1024, max_total_bytes=16*1024*1024) as root:
        before = root.read(target.name)
        doc = strict_json(before.data)
        run = FinancialRun.from_dict(doc["report"] if isinstance(doc, dict) and "report" in doc else doc)
        if isinstance(doc, dict) and "report" in doc:
            expected = {"report": run.to_dict(), "counts": run.counts, "substantive_sha256": run.substantive_sha256, "exit_code": run.exit_code}
            if digest(doc) != digest(expected):
                raise EvidenceError("invalid_financial_report_wrapper")
        after = root.read(target.name, recheck=True)
        if before.stamp != after.stamp or before.byte_sha256 != after.byte_sha256:
            raise EvidenceError("financial_report_changed")
    return run


def project_packets(run, selected):
    if len(selected) > 1000:
        raise EvidenceError("review_claim_limit")
    if len(run.to_json(substantive=True).encode()) > 16*1024*1024:
        raise EvidenceError("review_input_report_size_limit")
    input_hash = run.substantive_sha256
    projection_bytes = 0
    results = {d.claim_id: d for d in run.identity_run.decisions}
    results.update({d.claim_id: d for d in run.results})
    if any(c not in results for c in selected):
        raise EvidenceError("unknown_selected_claim")
    packets = []
    for claim_id in selected:
        result = results[claim_id]
        financial = claim_id.startswith("financial-claim:")
        claim = ReviewedClaim(claim_id=claim_id, status=result.status,
            **({"financial_result": result} if financial else {"identity_result": result}))
        records = [r for r in run.identity_run.records if any(e in result.evidence for e in r.evidence)]
        citations = ordered(EvidenceCitation(evidence=e) for r in records for e in r.evidence)
        # Preserve countervailing evidence even if a future result cites no row summary.
        citations = ordered(citations + tuple(EvidenceCitation(evidence=e) for e in result.evidence))
        citation_ids = tuple(sorted(c.citation_id for c in citations))
        summaries = ordered(SourceObservationSummary(identity=r,
            monetary_observations=ordered(o for o in run.observations if o.record_id == r.record_id),
            citation_ids=tuple(sorted(EvidenceCitation(evidence=e).citation_id for e in r.evidence))) for r in records)
        explanation = ComparisonExplanation(
            scope=result.claim_scope if financial else result.claim,
            compatibility=result.compatibility.value if financial else "identity_only_not_financial_comparison",
            reasoning=result.reasons,
            agreement=("Agreement established only for this saved, narrowly defined claim."
                       if result.status is ComparisonStatus.VERIFIED_MATCH else
                       "Available evidence does not establish agreement for this claim; this is not a misconduct finding."),
            difference_usa_minus_fpds=result.difference_usa_minus_fpds if financial else None,
            tolerance=result.tolerance if financial else None)
        alternatives = []
        for code in CATALOG:
            state = ExplanationState.UNRESOLVED
            rationale = "A possible ordinary explanation; available evidence does not establish or exclude its cause."
            refs = ()
            if financial and result.compatibility.value == "compatible" and code in ("incremental_cumulative_fields", "fiscal_year_lifetime_scope"):
                state, refs = ExplanationState.RULED_OUT, citation_ids
                rationale = "Ruled out only as a field-scope mismatch for this selected, documented action-value pair; no broader history assertion."
            if financial and result.difference_usa_minus_fpds is not None and code == "rounding_precision":
                state, refs = ExplanationState.NOT_APPLICABLE, citation_ids
                rationale = "This calculation uses exact Decimal values with zero tolerance; upstream rounding behavior remains unknown."
            alternatives.append(AlternativeExplanation(code=code, state=state, rationale=rationale, citation_ids=refs))
        limitations = [EvidenceLimitation(code="claim_scope", detail="Saved observations only; identity agreement is not financial assurance, and a numerical difference is not evidence of misconduct."),
            EvidenceLimitation(code="source_authenticity", detail="Hashes verify preserved content integrity, not source authenticity or an atomic upstream snapshot."),
            EvidenceLimitation(code="review_separation", detail="Automated findings are separate from unauthenticated reviewer-entered assertions.")]
        for c in run.identity_run.coverage:
            refs = tuple(sorted(x.citation_id for x in citations if x.evidence.artifact == c.artifact))
            limitations.append(EvidenceLimitation(code="coverage:" + c.artifact.source + ":" + c.artifact.sha256,
                detail=f"pagination={c.pagination.value}; history={c.transaction_history.value}; source-wide={c.source_wide.value}; freshness={c.freshness.value}; query scope={c.query_scope.value}", citation_ids=refs))
        for c in citations:
            for code in c.evidence.artifact.limitations:
                limitations.append(EvidenceLimitation(code=code, detail="Preserved source limitation: " + code, citation_ids=(c.citation_id,)))
        for excluded in run.identity_run.excluded_artifacts:
            limitations.append(EvidenceLimitation(code="excluded_response:" + excluded.relative_path, detail=excluded.reason))
        questions = ("Are the current source action/revision and publication states aligned?",
                     "What additional primary evidence establishes missing identifiers or historical coverage?",
                     "Does any observed difference persist after verifying scope and ordinary explanations?")
        next_step = result.next_step if financial else "Inspect the cited native identifiers and all candidates; obtain missing agency, parent or action context before asserting equivalence."
        packet = ReviewPacket(input_financial_sha256=input_hash, claim=claim,
            sources=summaries, citations=citations, comparison=explanation, alternatives=ordered(alternatives),
            limitations=ordered(limitations), unresolved_questions=questions,
            recommended_actions=(RecommendedVerificationAction(instruction=next_step, citation_ids=citation_ids),))
        projection_bytes += len(packet.to_json().encode())
        if projection_bytes > 32*1024*1024:
            raise EvidenceError("review_projection_size_limit")
        packets.append(packet)
    return ordered(packets), len(results)


def build_packets(root, *, identity_report=None, financial_report=None, claim_ids=None, max_claims=100):
    if type(max_claims) is not int or not 1 <= max_claims <= 1000:
        raise EvidenceError("invalid_review_claim_limit")
    prior = read_financial_report(financial_report) if financial_report else None
    run = reconcile_collection(root, identity_report_path=identity_report, **({"limits": prior.limits} if prior else {}))
    if prior and prior.substantive_sha256 != run.substantive_sha256:
        raise EvidenceError("stale_or_conflicting_financial_report")
    available = tuple(sorted({d.claim_id for d in run.identity_run.decisions} | {d.claim_id for d in run.results}))
    selected = available if claim_ids is None else tuple(claim_ids)
    if len(selected) > max_claims:
        raise EvidenceError("review_claim_limit_select_explicit_subset")
    if len(selected) != len(set(selected)):
        raise EvidenceError("duplicate_review_claim_selection")
    selected = tuple(sorted(selected))
    packets, total = project_packets(run, selected)
    manifest = ReviewPacketManifest(financial_run=run, selected_claim_ids=selected, packets=packets, total_available_claims=total)
    validate_packet_sources(root, manifest)
    return manifest


def validate_packet_sources(root, manifest):
    if inspect_directory(root).substantive_sha256 != manifest.financial_run.identity_run.input_manifest_sha256:
        raise EvidenceError("review_source_evidence_changed")
