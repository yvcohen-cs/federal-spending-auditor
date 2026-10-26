"""Phase 3C1 contracts only: no collection, matching or financial calculations.

Schema v1 uses strict, JSON-compatible wire types. See docs/evidence-schemas.md.
Evidence assertions describe narrowly scoped claims, never misconduct.
"""
from __future__ import annotations

import hashlib
import json
import re
import types
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Union, get_args, get_origin, get_type_hints
from urllib.parse import urlsplit


SCHEMA_VERSION = 1


class Representation(str, Enum):
    PARSED_JSON = "parsed_json"
    DECODED_XML = "decoded_xml"
    RESPONSE_BYTES = "response_bytes"
    DOCUMENT_BYTES = "document_bytes"


class Completeness(str, Enum):
    UNKNOWN = "unknown"
    PARTIAL = "partial"
    COMPLETE = "complete"
    NOT_APPLICABLE = "not_applicable"


class Dimension(str, Enum):
    IDENTITY = "identity"
    AMOUNT = "amount"
    DATE = "date"
    COVERAGE = "coverage"
    FRESHNESS = "freshness"


class ComparisonStatus(str, Enum):
    VERIFIED_MATCH = "verified_match"
    EXPLAINABLE_DIFFERENCE = "explainable_difference"
    UNRESOLVED_DISCREPANCY = "unresolved_discrepancy"
    AMBIGUOUS_MATCH = "ambiguous_match"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ReviewState(str, Enum):
    NOT_REVIEWED = "not_reviewed"
    IN_REVIEW = "in_review"
    AWAITING_EVIDENCE = "awaiting_evidence"
    REVIEW_COMPLETE = "review_complete"


class Support(str, Enum):
    UNKNOWN = "unknown"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"


class ValueKind(str, Enum):
    STRING = "string"
    DECIMAL = "decimal"
    DATE = "date"


class ParseStatus(str, Enum):
    VALID = "valid"
    MISSING = "missing"
    INVALID = "invalid"


def _text(value: str, name: str) -> None:
    if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name} must be nonblank text without control characters")


def _timestamp(value: str | None) -> None:
    if value is not None:
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("invalid UTC timestamp") from exc
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds() != 0:
            raise ValueError("timestamp must have UTC offset")


def _url(value: str | None) -> None:
    if value is not None:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or any(c.isspace() for c in value)):
            raise ValueError("source URLs must be HTTPS without credentials or whitespace")


def _hash(value: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("expected lowercase SHA-256 hex digest")


def _decode(annotation: Any, value: Any) -> Any:
    """Validate runtime types as well as decode wire types; never coerce IDs."""
    origin, args = get_origin(annotation), get_args(annotation)
    if origin in (Union, types.UnionType):
        for option in args:
            try:
                return _decode(option, value)
            except (ValueError, TypeError):
                pass
        raise ValueError("value does not satisfy declared optional/union type")
    if annotation is type(None):
        if value is not None:
            raise ValueError("expected null")
        return None
    if origin is tuple:
        if not isinstance(value, (tuple, list)):
            raise ValueError("expected array")
        return tuple(_decode(args[0], item) for item in value)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return annotation(value)
    if isinstance(annotation, type) and issubclass(annotation, Schema):
        return value if type(value) is annotation else annotation.from_dict(value)
    if type(value) is not annotation:
        raise ValueError(f"expected {annotation.__name__}")
    return value


def _wire(value: Any, substantive: bool) -> Any:
    if isinstance(value, Schema):
        return value.to_dict(substantive=substantive)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_wire(item, substantive) for item in value]
    return value


@dataclass(frozen=True, kw_only=True)
class Schema:
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        hints = get_type_hints(type(self))
        for item in fields(self):
            value = getattr(self, item.name)
            decoded = _decode(hints[item.name], value)
            # Constructors require enum/schema instances and immutable tuples;
            # from_dict performs wire conversion before construction.
            if type(decoded) is not type(value) or decoded != value:
                raise ValueError(f"{item.name}: use declared types (or from_dict)")
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported schema_version; no automatic migration")
        self.validate()

    def validate(self) -> None:
        pass

    def to_dict(self, *, substantive: bool = False) -> dict[str, Any]:
        return {"schema_type": type(self).__name__, **{
            item.name: _wire(getattr(self, item.name), substantive)
            for item in fields(self)
            if not (substantive and item.metadata.get("execution"))
        }}

    def to_json(self, *, substantive: bool = False) -> str:
        return json.dumps(self.to_dict(substantive=substantive), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True, allow_nan=False)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Any:
        if not isinstance(value, dict):
            raise ValueError("expected schema object")
        expected = {item.name for item in fields(cls)} | {"schema_type"}
        if set(value) - expected or value.get("schema_type") != cls.__name__:
            raise ValueError("unknown fields or wrong schema_type")
        if value.get("schema_version") != SCHEMA_VERSION or type(value.get("schema_version")) is not int:
            raise ValueError("explicit supported schema_version required")
        hints = get_type_hints(cls)
        try:
            return cls(**{key: _decode(hints[key], item) for key, item in value.items()
                          if key != "schema_type"})
        except TypeError as exc:
            raise ValueError("missing required schema fields") from exc

    @classmethod
    def from_json(cls, value: str) -> Any:
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = item
            return result
        return cls.from_dict(json.loads(value, object_pairs_hook=unique))


@dataclass(frozen=True, kw_only=True)
class SourceIdentifier(Schema):
    """A native source value, never a constructed hash or inferred identity."""
    source: str
    namespace: str
    value: str

    def validate(self) -> None:
        for name in ("source", "namespace", "value"):
            _text(getattr(self, name), name)


@dataclass(frozen=True, kw_only=True)
class EvidenceArtifact(Schema):
    source: str
    relative_path: str
    sha256: str
    representation: Representation
    hash_basis: str
    endpoint: str | None = None
    method: str | None = None
    request_json: str | None = None
    retrieved_at_utc: str | None = None
    source_updated_at_utc: str | None = None
    http_status: int | None = None
    limitations: tuple[str, ...] = ()

    @property
    def artifact_id(self) -> str:
        return "artifact:sha256:" + self.sha256

    def validate(self) -> None:
        _text(self.source, "source")
        _text(self.relative_path, "relative_path")
        if (self.relative_path.startswith(("/", "\\")) or "\\" in self.relative_path
                or ":" in self.relative_path or any(p in ("", ".", "..") for p in self.relative_path.split("/"))):
            raise ValueError("relative_path must stay within the evidence root")
        _hash(self.sha256)
        expected = {Representation.PARSED_JSON: "canonical_json",
                    Representation.DECODED_XML: "utf8_text",
                    Representation.RESPONSE_BYTES: "original_bytes",
                    Representation.DOCUMENT_BYTES: "original_bytes"}
        if self.hash_basis != expected[self.representation]:
            raise ValueError("hash_basis contradicts evidence representation")
        _url(self.endpoint)
        if self.method not in (None, "GET", "POST", "HEAD"):
            raise ValueError("unsupported request method")
        if self.request_json is not None:
            parsed = json.loads(self.request_json)
            if not isinstance(parsed, dict):
                raise ValueError("request_json must encode an object")
            if json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) != self.request_json:
                raise ValueError("request_json must be canonical JSON")
        _timestamp(self.retrieved_at_utc)
        _timestamp(self.source_updated_at_utc)
        if (self.endpoint is None or self.method is None or self.retrieved_at_utc is None) and not self.limitations:
            raise ValueError("unknown collection provenance requires an explicit limitation")
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise ValueError("invalid HTTP status")
        for item in self.limitations:
            _text(item, "limitation")


@dataclass(frozen=True, kw_only=True)
class EvidenceRecordRef(Schema):
    artifact_id: str
    locator: str
    source: str
    native_id: SourceIdentifier | None = None
    source_record_url: str | None = None
    query_url: str | None = None
    record_url_constructed: bool = False

    def validate(self) -> None:
        if not self.artifact_id.startswith("artifact:sha256:"):
            raise ValueError("constructed artifact ID required")
        _hash(self.artifact_id.removeprefix("artifact:sha256:"))
        _text(self.locator, "locator")
        _text(self.source, "source")
        if self.native_id is not None and self.native_id.source != self.source:
            raise ValueError("native identifier source conflicts with record source")
        _url(self.source_record_url)
        _url(self.query_url)
        if self.record_url_constructed and self.source_record_url is None:
            raise ValueError("constructed URL marker requires a URL")


@dataclass(frozen=True, kw_only=True)
class AwardIdentity(Schema):
    identifiers: tuple[SourceIdentifier, ...]
    evidence: tuple[EvidenceRecordRef, ...]
    parent_identifiers: tuple[SourceIdentifier, ...] = ()
    award_category: str | None = None

    def validate(self) -> None:
        if not self.identifiers or not self.evidence:
            raise ValueError("award identity needs native identifiers and provenance")
        if len(set(self.identifiers)) != len(self.identifiers):
            raise ValueError("duplicate identity components")
        keys = [(item.source, item.namespace) for item in self.identifiers]
        if len(set(keys)) != len(keys):
            raise ValueError("conflicting identifiers in one source namespace")
        sources = {ref.source for ref in self.evidence}
        if any(item.source not in sources for item in self.identifiers + self.parent_identifiers):
            raise ValueError("identity component has no source provenance")
        if self.award_category is not None:
            _text(self.award_category, "award_category")


@dataclass(frozen=True, kw_only=True)
class ActionIdentity(Schema):
    award: AwardIdentity
    identifiers: tuple[SourceIdentifier, ...]
    evidence: tuple[EvidenceRecordRef, ...]
    modification: SourceIdentifier | None = None
    transaction: SourceIdentifier | None = None
    revision: SourceIdentifier | None = None

    def validate(self) -> None:
        if not self.identifiers or not self.evidence:
            raise ValueError("action identity needs native identifiers and provenance")
        keys = [(item.source, item.namespace) for item in self.identifiers]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate/conflicting action identity components")
        sources = {ref.source for ref in self.evidence}
        components = self.identifiers + tuple(x for x in (self.modification, self.transaction, self.revision) if x is not None)
        if any(item.source not in sources for item in components):
            raise ValueError("action component has no source provenance")


@dataclass(frozen=True, kw_only=True)
class TypedValue(Schema):
    evidence: EvidenceRecordRef
    field_path: str
    definition: str
    kind: ValueKind
    parse_status: ParseStatus
    original_json: str
    parsed: str | None = None
    currency: str | None = None
    date_basis: str | None = None
    period: str | None = None

    def validate(self) -> None:
        _text(self.field_path, "field_path")
        _text(self.definition, "definition")
        original = json.loads(self.original_json)
        if json.dumps(original, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) != self.original_json:
            raise ValueError("original_json must be canonical JSON")
        if self.parse_status is ParseStatus.MISSING and original is not None:
            raise ValueError("missing values require original null")
        if self.parse_status is not ParseStatus.VALID and self.parsed is not None:
            raise ValueError("missing/invalid values cannot have parsed values")
        if self.parse_status is ParseStatus.VALID:
            if self.parsed is None or original is None:
                raise ValueError("valid value needs original and parsed values")
            if self.kind is ValueKind.DECIMAL:
                try:
                    if not Decimal(self.parsed).is_finite():
                        raise ValueError("nonfinite decimal")
                    if type(original) not in (str, int, float) or Decimal(str(original)) != Decimal(self.parsed):
                        raise ValueError("parsed decimal contradicts original value")
                except InvalidOperation as exc:
                    raise ValueError("invalid decimal") from exc
            elif self.kind is ValueKind.DATE:
                from datetime import date
                if date.fromisoformat(self.parsed).isoformat() != self.parsed:
                    raise ValueError("date must use YYYY-MM-DD")
                if not isinstance(original, str) or date.fromisoformat(original) != date.fromisoformat(self.parsed):
                    raise ValueError("parsed date contradicts original value")
            elif not isinstance(original, str) or original != self.parsed:
                raise ValueError("parsed string contradicts original value")
        if self.currency is not None and (self.kind is not ValueKind.DECIMAL or not re.fullmatch(r"[A-Z]{3}", self.currency)):
            raise ValueError("currency requires decimal value and three-letter code")
        for name in ("date_basis", "period"):
            if getattr(self, name) is not None:
                _text(getattr(self, name), name)


@dataclass(frozen=True, kw_only=True)
class CoverageAssessment(Schema):
    scope: str
    pagination: Completeness = Completeness.UNKNOWN
    transaction_history: Completeness = Completeness.UNKNOWN
    source_wide: Completeness = Completeness.UNKNOWN
    evidence: tuple[EvidenceRecordRef, ...] = ()
    rationale: tuple[str, ...] = ()
    limited: bool = False
    retrieval_failed: bool = False

    def validate(self) -> None:
        _text(self.scope, "scope")
        if any(x is not Completeness.UNKNOWN for x in (self.pagination, self.transaction_history, self.source_wide)):
            if not self.evidence or not self.rationale:
                raise ValueError("completeness assertions require evidence and rationale")
        if (self.limited or self.retrieval_failed) and self.pagination is Completeness.COMPLETE:
            raise ValueError("limited/failed retrieval cannot have complete pagination")
        for item in self.rationale:
            _text(item, "coverage rationale")


@dataclass(frozen=True, kw_only=True)
class ComparisonResult(Schema):
    claim_type: str
    subject: SourceIdentifier
    scope: str
    dimension: Dimension
    status: ComparisonStatus
    evidence: tuple[EvidenceRecordRef, ...]
    rationale: str
    coverage: CoverageAssessment
    candidates: tuple[EvidenceRecordRef, ...] = ()
    identity_support: Support = Support.UNKNOWN
    comparability_support: Support = Support.UNKNOWN
    sufficiency_support: Support = Support.UNKNOWN
    explanation_evidence: tuple[EvidenceRecordRef, ...] = ()
    requires_complete_history: bool = False
    limitations: tuple[str, ...] = ()

    @property
    def claim_id(self) -> str:
        # Deliberately excludes outcome, candidates, evidence and execution time.
        claim = {"schema_version": self.schema_version, "claim_type": self.claim_type,
                 "subject": self.subject.to_dict(), "scope": self.scope,
                 "dimension": self.dimension.value,
                 "requires_complete_history": self.requires_complete_history}
        raw = json.dumps(claim, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return "claim:v1:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def validate(self) -> None:
        for name in ("claim_type", "scope", "rationale"):
            _text(getattr(self, name), name)
        if self.scope != self.coverage.scope:
            raise ValueError("claim and coverage scope must agree")
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("duplicate candidates are not ambiguity")
        if any(ref not in self.evidence for ref in self.candidates + self.explanation_evidence):
            raise ValueError("candidate/explanation references must be included in evidence")
        decisive = self.status in (ComparisonStatus.VERIFIED_MATCH,
                                   ComparisonStatus.EXPLAINABLE_DIFFERENCE,
                                   ComparisonStatus.UNRESOLVED_DISCREPANCY)
        if decisive:
            if (self.identity_support is not Support.SUPPORTED
                    or self.comparability_support is not Support.SUPPORTED
                    or self.sufficiency_support is not Support.SUPPORTED):
                raise ValueError("decisive outcomes require explicit supported prerequisites")
            if len(set(self.evidence)) < 2 or len({ref.source for ref in self.evidence}) < 2:
                raise ValueError("cross-source outcomes require evidence from two sources")
            if len(self.candidates) > 1:
                raise ValueError("unresolved candidates block decisive outcomes")
            if self.requires_complete_history and self.coverage.transaction_history is not Completeness.COMPLETE:
                raise ValueError("claim requires complete transaction history")
        if self.status is ComparisonStatus.AMBIGUOUS_MATCH:
            if len(self.candidates) < 2 or self.identity_support is Support.SUPPORTED:
                raise ValueError("ambiguous match needs distinct unresolved candidates")
        if self.status is ComparisonStatus.INSUFFICIENT_EVIDENCE and all(
            x is Support.SUPPORTED for x in (self.identity_support, self.comparability_support, self.sufficiency_support)
        ):
            raise ValueError("insufficient evidence contradicts fully supported prerequisites")
        if self.status is ComparisonStatus.EXPLAINABLE_DIFFERENCE and not self.explanation_evidence:
            raise ValueError("explainable difference needs supporting explanation evidence")
        for item in self.limitations:
            _text(item, "limitation")


@dataclass(frozen=True, kw_only=True)
class ReviewEvent(Schema):
    claim_id: str
    state: ReviewState
    reviewer: str
    rationale: str
    reviewed_at_utc: str
    evidence: tuple[EvidenceRecordRef, ...] = ()
    supersedes_event_id: str | None = None

    def validate(self) -> None:
        if not re.fullmatch(r"claim:v1:[0-9a-f]{64}", self.claim_id):
            raise ValueError("invalid claim ID")
        for name in ("reviewer", "rationale"):
            _text(getattr(self, name), name)
        _timestamp(self.reviewed_at_utc)
        if self.supersedes_event_id is not None:
            _text(self.supersedes_event_id, "supersedes_event_id")
        if self.state is ReviewState.REVIEW_COMPLETE and not self.evidence:
            raise ValueError("completed review requires cited evidence")


@dataclass(frozen=True, kw_only=True)
class VerificationRun(Schema):
    code_revision: str
    rule_version: str
    parser_version: str
    config_sha256: str
    artifacts: tuple[EvidenceArtifact, ...]
    results: tuple[ComparisonResult, ...]
    executed_at_utc: str | None = field(default=None, metadata={"execution": True})

    def validate(self) -> None:
        for name in ("code_revision", "rule_version", "parser_version"):
            _text(getattr(self, name), name)
        _hash(self.config_sha256)
        _timestamp(self.executed_at_utc)
        manifest = {item.artifact_id: item for item in self.artifacts}
        if len(manifest) != len(self.artifacts):
            raise ValueError("duplicate artifact IDs; retain observations in separate runs")
        if len({item.claim_id for item in self.results}) != len(self.results):
            raise ValueError("duplicate claims within run")
        for result in self.results:
            refs = result.evidence + result.coverage.evidence
            for ref in refs:
                if ref.artifact_id not in manifest or manifest[ref.artifact_id].source != ref.source:
                    raise ValueError("record reference missing from manifest or source conflicts")

    @property
    def substantive_sha256(self) -> str:
        return hashlib.sha256(self.to_json(substantive=True).encode("utf-8")).hexdigest()
