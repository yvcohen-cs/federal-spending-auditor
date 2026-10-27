"""C5 version-1 companion schemas; observed financial claims, never misconduct."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .evidence import ComparisonStatus, Schema, _hash, _text, _timestamp
from .evidence_io import digest
from .financial_values import MonetaryValue
from .matching_models import MatchEvidenceReference, MatchRunSummary, _ComputedIdentity, ordered


FINANCIAL_RULE_VERSION = "financial-v1"
SEMANTICS_VERSION = "field-semantics-v1"
USA_ACTION = "federal_action_obligation"
FPDS_ACTION = "dollarValues/obligatedAmount"


class Measure(str, Enum):
    OBLIGATION = "federal_obligation"
    CONTRACT_VALUE = "contract_value"
    CURRENT_CONTRACT_VALUE = "current_exercised_contract_value"
    POTENTIAL_CONTRACT_VALUE = "potential_contract_value_with_options"
    OUTLAY = "outlay"
    UNKNOWN = "unknown"


class AmountBasis(str, Enum):
    INCREMENTAL = "incremental"
    CUMULATIVE = "cumulative"
    UNKNOWN = "unknown"


class FinancialScope(str, Enum):
    ACTION = "action"
    AWARD = "award"
    FISCAL_YEAR = "fiscal_year"
    LIFETIME = "lifetime"
    UNKNOWN = "unknown"


class DateBasis(str, Enum):
    SIGNED = "signed_action_date"
    EFFECTIVE = "effective_date"
    PUBLICATION = "publication_date"
    RETRIEVAL = "retrieval_date"
    UNKNOWN = "unknown"


class Compatibility(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass(frozen=True, kw_only=True)
class FieldSemantics(Schema):
    measure: Measure = Measure.UNKNOWN
    basis: AmountBasis = AmountBasis.UNKNOWN
    scope: FinancialScope = FinancialScope.UNKNOWN
    currency: str | None = None
    documented: bool = False
    version: str = SEMANTICS_VERSION

    def validate(self):
        if self.version != SEMANTICS_VERSION or self.currency not in (None, "USD"):
            raise ValueError("unsupported semantics version or currency conversion")
        if self.documented and any(x.value == "unknown" for x in (self.measure, self.basis, self.scope)):
            raise ValueError("documented monetary semantics must be explicit")


def field_semantics(source, name):
    if (source, name) in (("usaspending", USA_ACTION), ("fpds", FPDS_ACTION)):
        return FieldSemantics(measure=Measure.OBLIGATION, basis=AmountBasis.INCREMENTAL,
                              scope=FinancialScope.ACTION, currency="USD", documented=True)
    if source == "fpds" and name == "totalDollarValues/obligatedAmount":
        return FieldSemantics(measure=Measure.OBLIGATION, basis=AmountBasis.CUMULATIVE,
                              scope=FinancialScope.AWARD, currency="USD", documented=True)
    if source == "fpds" and name in ("totalDollarValues/totalBaseAndExercisedOptionsValue", "totalDollarValues/totalBaseAndAllOptionsValue"):
        measure = Measure.CURRENT_CONTRACT_VALUE if name.endswith("totalBaseAndExercisedOptionsValue") else Measure.POTENTIAL_CONTRACT_VALUE
        return FieldSemantics(measure=measure, basis=AmountBasis.CUMULATIVE,
                              scope=FinancialScope.AWARD, currency="USD", documented=True)
    return FieldSemantics()


def signed_date(raw):
    # A bounded representation subset; never substitute effective/publication
    # dates or drop arbitrary time zones/times from a financial temporal scope.
    if not isinstance(raw, str) or len(raw) not in (10, 19):
        return None
    if len(raw) == 19 and raw[10:] != " 00:00:00":
        return None
    try:
        parsed = date.fromisoformat(raw[:10])
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == raw[:10] else None


@dataclass(frozen=True, kw_only=True)
class FinancialObservation(_ComputedIdentity):
    _computed_name = "financial_observation_id"
    record_id: str
    source: str
    original_field: str
    value: MonetaryValue
    semantics: FieldSemantics
    evidence: MatchEvidenceReference
    action_date_raw: str | None
    action_date: str | None
    date_basis: DateBasis = DateBasis.SIGNED
    declared_currency_raw: str | None = None

    @property
    def financial_observation_id(self):
        return "money-observation:v1:" + digest({"record": self.record_id,
                "artifact": self.evidence.artifact.sha256, "observation": self.evidence.observation_id,
                "locator": self.evidence.reference.locator, "path": self.evidence.artifact.relative_path,
                "field": self.original_field})

    @property
    def currency(self):
        # Field-defined USD is distinguishable from explicit record metadata.
        return self.semantics.currency if self.declared_currency_raw in (None, "USD") else None

    @property
    def action_fiscal_year(self):
        if self.action_date is None:
            return None
        d = date.fromisoformat(self.action_date)
        if d < date(1976, 10, 1):
            return None  # Earlier calendars/transition periods need separate rules.
        return d.year + (d.month >= 10)

    def to_dict(self, *, substantive=False):
        return {**super().to_dict(substantive=substantive), "effective_currency": self.currency,
                "currency_basis": "documented_field_unit" if self.currency is not None else "unknown_or_conflicting",
                "action_fiscal_year": self.action_fiscal_year}

    @classmethod
    def from_dict(cls, value):
        computed = {"effective_currency", "currency_basis", "action_fiscal_year"}
        if not isinstance(value, dict) or not computed <= set(value):
            raise ValueError("explicit financial unit/date interpretations required")
        result = super().from_dict({k: v for k, v in value.items() if k not in computed})
        if digest({k: value[k] for k in computed}) != digest({k: result.to_dict()[k] for k in computed}):
            raise ValueError("financial interpretation contradicts original metadata")
        return result

    def validate(self):
        if not self.record_id.startswith("record:v1:"):
            raise ValueError("C4 record reference required")
        _hash(self.record_id.removeprefix("record:v1:"))
        if self.source != self.evidence.reference.source or self.source not in ("usaspending", "fpds"):
            raise ValueError("financial source/provenance conflict")
        _text(self.original_field, "field")
        if self.semantics != field_semantics(self.source, self.original_field):
            raise ValueError("monetary semantics contradict versioned field registry")
        expected = signed_date(self.action_date_raw) if self.date_basis is DateBasis.SIGNED else None
        if self.action_date != expected:
            raise ValueError("action date contradicts supported original/basis")


@dataclass(frozen=True, kw_only=True)
class ExplanationCheck(Schema):
    code: str
    assessment: str

    def validate(self):
        if self.code not in ("identity_context", "incremental_vs_cumulative", "signed_vs_effective_or_publication",
                             "fiscal_year_scope", "rounding_precision", "duplicate_retrievals",
                             "missing_modifications_or_corrections", "source_refresh_or_reporting_lag"):
            raise ValueError("unsupported explanation check")
        if self.assessment not in ("checked", "unknown", "possible", "not_applicable"):
            raise ValueError("unsupported explanation assessment")


@dataclass(frozen=True, kw_only=True)
class FinancialComparison(_ComputedIdentity):
    _computed_name = "claim_id"
    identity_claim_id: str
    subject_record_id: str
    status: ComparisonStatus
    compatibility: Compatibility
    reasons: tuple[str, ...]
    left_observation_ids: tuple[str, ...]
    right_observation_ids: tuple[str, ...]
    evidence: tuple[MatchEvidenceReference, ...]
    explanations: tuple[ExplanationCheck, ...]
    next_step: str
    left_normalized: str | None = None
    right_normalized: str | None = None
    difference_usa_minus_fpds: str | None = None
    tolerance: str = "0"
    tolerance_basis: str = "exact_decimal_no_rounding_no_source_justified_nonzero_tolerance"
    rule_version: str = FINANCIAL_RULE_VERSION
    claim_scope: str = "observed_same_action_obligation_values"

    @property
    def claim_id(self):
        return "financial-claim:v1:" + digest({"identity_claim": self.identity_claim_id,
                  "scope": self.claim_scope, "rules": self.rule_version})

    def validate(self):
        if self.rule_version != FINANCIAL_RULE_VERSION or self.claim_scope != "observed_same_action_obligation_values":
            raise ValueError("unsupported financial rule/scope")
        for value, prefix in ((self.identity_claim_id, "identity-claim:v1:"), (self.subject_record_id, "record:v1:")):
            if not value.startswith(prefix):
                raise ValueError("constructed C4 identity reference required")
            _hash(value.removeprefix(prefix))
        if self.tolerance != "0" or self.tolerance_basis != "exact_decimal_no_rounding_no_source_justified_nonzero_tolerance":
            raise ValueError("unsupported tolerance")
        if not self.reasons or not self.evidence or not self.next_step:
            raise ValueError("financial rationale, evidence and next action required")
        if self.evidence != ordered(self.evidence) or self.explanations != ordered(self.explanations):
            raise ValueError("canonical financial evidence/checks required")
        for ids in (self.left_observation_ids, self.right_observation_ids):
            if ids != tuple(sorted(set(ids))):
                raise ValueError("canonical observation references required")
            for value in ids:
                if not value.startswith("money-observation:v1:"):
                    raise ValueError("constructed monetary observation reference required")
                _hash(value.removeprefix("money-observation:v1:"))
        values = (self.left_normalized, self.right_normalized, self.difference_usa_minus_fpds)
        if any(v is not None for v in values):
            if any(v is None for v in values) or self.compatibility is not Compatibility.COMPATIBLE or not self.left_observation_ids or not self.right_observation_ids:
                raise ValueError("numeric difference requires complete compatible values")
            from .financial_values import exact_difference, monetary_value, NumericState, RawKind
            for v in values:
                parsed = monetary_value(RawKind.XML_TEXT, v)
                if parsed.state is not NumericState.VALID or parsed.normalized != v:
                    raise ValueError("canonical exact Decimal required")
            if exact_difference(self.left_normalized, self.right_normalized) != self.difference_usa_minus_fpds:
                raise ValueError("incorrect exact difference")
        if self.status is ComparisonStatus.VERIFIED_MATCH and self.difference_usa_minus_fpds != "0":
            raise ValueError("verified observed value equality requires zero difference")
        if self.status is ComparisonStatus.VERIFIED_MATCH and {e.reference.source for e in self.evidence} != {"usaspending", "fpds"}:
            raise ValueError("verified cross-source values require both sources")
        if self.status in (ComparisonStatus.UNRESOLVED_DISCREPANCY, ComparisonStatus.EXPLAINABLE_DIFFERENCE):
            raise ValueError("v1 cannot certify source-version alignment or an explanatory adjustment")


@dataclass(frozen=True, kw_only=True)
class FinancialLimits(Schema):
    max_observations: int = 5000
    max_comparison_work: int = 20000

    def validate(self):
        if not 1 <= self.max_observations <= 20000 or not 1 <= self.max_comparison_work <= 100000:
            raise ValueError("unsupported financial resource limits")


@dataclass(frozen=True, kw_only=True)
class FinancialRun(Schema):
    identity_run: MatchRunSummary
    observations: tuple[FinancialObservation, ...]
    results: tuple[FinancialComparison, ...]
    limits: FinancialLimits = field(default_factory=FinancialLimits)
    rule_version: str = FINANCIAL_RULE_VERSION
    limitations: tuple[str, ...] = ("observed_values_only_not_complete_award_finances",
                                   "source_revision_alignment_and_refresh_unknown",
                                   "no_history_totals_or_currency_conversions")
    executed_at_utc: str | None = field(default=None, metadata={"execution": True})

    def validate(self):
        _timestamp(self.executed_at_utc)
        if self.rule_version != FINANCIAL_RULE_VERSION:
            raise ValueError("unsupported financial rules")
        if self.limitations != ("observed_values_only_not_complete_award_finances",
                                "source_revision_alignment_and_refresh_unknown",
                                "no_history_totals_or_currency_conversions"):
            raise ValueError("required financial limitations cannot be removed")
        if self.observations != ordered(self.observations) or self.results != ordered(self.results):
            raise ValueError("canonical financial members required")
        if len({o.financial_observation_id for o in self.observations}) != len(self.observations):
            raise ValueError("conflicting financial observation declarations")
        records = {r.record_id: r for r in self.identity_run.records}
        for o in self.observations:
            if o.record_id not in records or o.evidence not in records[o.record_id].evidence:
                raise ValueError("unregistered financial evidence/identity")
        from .financial_reconciliation import evaluate_finances
        if self.results != evaluate_finances(self.identity_run, self.observations, self.limits):
            raise ValueError("financial outcomes contradict deterministic rules")

    @property
    def substantive_sha256(self):
        return digest(self.to_dict(substantive=True))

    @property
    def counts(self):
        return {s.value: sum(r.status is s for r in self.results) for s in ComparisonStatus}

    @property
    def exit_code(self):
        return 0 if self.results and not self.identity_run.excluded_artifacts and all(r.status is ComparisonStatus.VERIFIED_MATCH for r in self.results) else 1
