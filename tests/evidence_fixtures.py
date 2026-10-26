"""Authored synthetic evidence only. No source downloads or production fallback."""
from src.evidence import (
    ActionIdentity, AwardIdentity, ComparisonResult, ComparisonStatus,
    Completeness, CoverageAssessment, Dimension, EvidenceArtifact,
    EvidenceRecordRef, ParseStatus, Representation, ReviewEvent, ReviewState,
    SourceIdentifier, Support, TypedValue, ValueKind, VerificationRun,
)


def native(source="usaspending", namespace="generated_internal_id", value="SYNTHETIC_00001-A/0"):
    return SourceIdentifier(source=source, namespace=namespace, value=value)


def artifacts():
    return (
        EvidenceArtifact(source="usaspending", relative_path="synthetic/award.json",
                         sha256="1" * 64, representation=Representation.PARSED_JSON,
                         hash_basis="canonical_json", endpoint="https://example.invalid/awards",
                         method="POST", request_json='{"page":1}',
                         retrieved_at_utc="2025-10-01T00:00:00Z"),
        EvidenceArtifact(source="fpds", relative_path="synthetic/feed.xml",
                         sha256="2" * 64, representation=Representation.DECODED_XML,
                         hash_basis="utf8_text", endpoint="https://example.invalid/feed",
                         method="GET", retrieved_at_utc="2025-10-01T00:01:00Z"),
    )


def refs():
    usa, fpds = artifacts()
    return (
        EvidenceRecordRef(artifact_id=usa.artifact_id, locator="/results/0",
                          source="usaspending", native_id=native()),
        EvidenceRecordRef(artifact_id=fpds.artifact_id, locator="/feed/entry[1]",
                          source="fpds", native_id=native("fpds", "entry_id", "00001.A/0")),
    )


def coverage(complete=False):
    return CoverageAssessment(scope="synthetic-award-observation", evidence=refs(),
                              transaction_history=Completeness.COMPLETE if complete else Completeness.UNKNOWN,
                              rationale=("Synthetic completeness assertion for contract tests.",) if complete else ())


def comparison():
    return ComparisonResult(claim_type="source_award_identity_agreement", subject=native(),
                            scope=coverage().scope, dimension=Dimension.IDENTITY,
                            status=ComparisonStatus.VERIFIED_MATCH, evidence=refs(),
                            rationale="Synthetic assertion; no matching algorithm executed.",
                            coverage=coverage(), identity_support=Support.SUPPORTED,
                            comparability_support=Support.SUPPORTED,
                            sufficiency_support=Support.SUPPORTED)


def contracts():
    award = AwardIdentity(identifiers=(native(),), evidence=(refs()[0],))
    action = ActionIdentity(award=award, identifiers=(native(namespace="transaction_id", value="0002-A"),),
                            evidence=(refs()[0],),
                            modification=native(namespace="modification_number", value="P00001"))
    value = TypedValue(evidence=refs()[0], field_path="/Award Amount",
                       definition="Synthetic award-level value; no cross-source equivalence asserted.",
                       kind=ValueKind.DECIMAL, parse_status=ParseStatus.VALID,
                       original_json='"100.00"', parsed="100.00", currency="USD")
    review = ReviewEvent(claim_id=comparison().claim_id, state=ReviewState.REVIEW_COMPLETE,
                         reviewer="synthetic-reviewer", rationale="Contract fixture only.",
                         reviewed_at_utc="2025-10-02T00:00:00Z", evidence=refs())
    run = VerificationRun(code_revision="synthetic-revision", rule_version="synthetic-v1",
                          parser_version="synthetic-v1", config_sha256="3" * 64,
                          artifacts=artifacts(), results=(comparison(),),
                          executed_at_utc="2025-10-02T00:01:00Z")
    return (artifacts()[0], refs()[0], award, action, value, coverage(), comparison(), review, run)
