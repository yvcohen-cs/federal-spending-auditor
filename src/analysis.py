"""Explainable missingness, robust outlier, and recipient-pattern analysis."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from .federal_spending_auditor import flag_awards


CORE_FIELDS = [
    "award_id",
    "generated_internal_id",
    "recipient_uei",
    "recipient_duns",
    "awarding_agency_code",
    "awarding_sub_agency_code",
    "start_date",
    "end_date",
    "award_amount",
]
COVERAGE_FIELDS = CORE_FIELDS + ["naics_code", "psc_code", "award_type"]
RULE_IDS = [
    "AWARD_AMOUNT_SCREEN",
    "MISSING_AWARD_IDENTIFIER",
    "MISSING_RECIPIENT_IDENTIFIERS",
    "EXACT_RECORD_SIGNATURE_REPEAT",
    "MISSING_AGENCY_IDENTIFIER",
    "INVALID_AWARD_AMOUNT",
    "NEGATIVE_AWARD_AMOUNT",
    "ROBUST_AMOUNT_OUTLIER",
]


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() else None


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires data")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _agency(record: dict[str, Any]) -> str:
    return str(record.get("awarding_agency_code") or record.get("awarding_agency") or "unknown agency")


def _procurement_category(record: dict[str, Any]) -> str | None:
    naics = record.get("naics_code")
    if not _missing(naics):
        return f"NAICS {str(naics).strip()[:2]}xx"
    psc = record.get("psc_code")
    if not _missing(psc):
        return f"PSC {str(psc).strip()[:2]}xx"
    return None


def missingness_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = len(records)
    result = []
    for field in COVERAGE_FIELDS:
        count = sum(_missing(record.get(field)) for record in records)
        result.append(
            {
                "field": field,
                "missing_count": count,
                "record_count": total,
                "missing_percent": round(100 * count / total, 2) if total else 0.0,
            }
        )
    return result


def _finding(
    record: dict[str, Any],
    rule_id: str,
    description: str,
    input_values: dict[str, Any],
    calculation: dict[str, Any],
    benign_explanations: str,
    **extra: Any,
) -> dict[str, Any]:
    stable_id = record.get("generated_internal_id") or record.get("internal_id") or record.get("award_id") or "unknown"
    return {
        "finding_id": f"{stable_id}:{rule_id}",
        "rule_id": rule_id,
        "detection_rule": description,
        "internal_id": record.get("internal_id"),
        "award_id": record.get("award_id"),
        "generated_internal_id": record.get("generated_internal_id"),
        "recipient_uei": record.get("recipient_uei"),
        "recipient_duns": record.get("recipient_duns"),
        "awarding_agency": record.get("awarding_agency"),
        "awarding_agency_code": record.get("awarding_agency_code"),
        "awarding_sub_agency_code": record.get("awarding_sub_agency_code"),
        "award_type": record.get("award_type"),
        "naics_code": record.get("naics_code"),
        "psc_code": record.get("psc_code"),
        "award_amount": record.get("award_amount"),
        "source_record_url": record.get("source_record_url"),
        "source_api_url": "https://api.usaspending.gov/api/v2/search/spending_by_award/",
        "input_values": json.dumps(input_values, sort_keys=True, default=str),
        "calculation": json.dumps(calculation, sort_keys=True, default=str),
        "possible_benign_explanations": benign_explanations,
        "verification_status": "unverified",
        "comparison_group": extra.pop("comparison_group", ""),
        "percentile": extra.pop("percentile", None),
        "robust_z": extra.pop("robust_z", None),
        "flag_reasons": description,
        "duplicate_of": extra.pop("duplicate_of", ""),
        **extra,
    }


def _legacy_findings(
    records: list[dict[str, Any]], amount_threshold: float
) -> list[dict[str, Any]]:
    findings = []
    for flagged in flag_awards(records, amount_threshold=amount_threshold):
        reasons = flagged["flag_reasons"].split("; ")
        for reason in reasons:
            if "screening threshold" in reason:
                rule_id = "AWARD_AMOUNT_SCREEN"
                calculation = {
                    "formula": "award_amount > configured_threshold",
                    "award_amount": flagged.get("award_amount"),
                    "configured_threshold": amount_threshold,
                    "result": True,
                }
                benign = "Award Amount may be a lifetime/cumulative award value, not FY2025 obligations. Large size can be expected for multi-year awards."
            elif "exact award-record signature" in reason:
                rule_id = "EXACT_RECORD_SIGNATURE_REPEAT"
                calculation = {
                    "formula": "exact equality across award ID, generated ID, recipient, dates, agencies, and amount",
                    "duplicate_of": flagged.get("duplicate_of"),
                }
                benign = "A repeated record can be a reporting artifact; verify transaction IDs and source records before drawing conclusions."
            elif "Recipient UEI" in reason:
                rule_id = "MISSING_RECIPIENT_IDENTIFIERS"
                calculation = {"formula": "UEI is blank AND DUNS is blank"}
                benign = "Legacy records, UEI transition, or source reporting gaps can leave recipient identifiers blank."
            else:
                rule_id = "MISSING_AWARD_IDENTIFIER"
                calculation = {"formula": "required award identifier is blank"}
                benign = "An unlinked or incomplete source record may lack the identifier; inspect the source and related submissions."
            findings.append(
                _finding(
                    flagged,
                    rule_id,
                    reason,
                    {field: flagged.get(field) for field in ("award_id", "generated_internal_id", "recipient_uei", "recipient_duns", "award_amount")},
                    calculation,
                    benign,
                    duplicate_of=flagged.get("duplicate_of", ""),
                )
            )
    for record in records:
        missing = [field for field in ("awarding_agency_code", "awarding_sub_agency_code") if _missing(record.get(field))]
        if missing:
            findings.append(
                _finding(
                    record,
                    "MISSING_AGENCY_IDENTIFIER",
                    "One or more agency identifier fields are missing",
                    {field: record.get(field) for field in missing},
                    {"formula": "agency identifier is blank", "missing_fields": missing},
                    "Agency reorganization, an unlinked record, or reporting gaps may explain missing codes.",
                )
            )
        amount = _decimal(record.get("award_amount"))
        if not _missing(record.get("award_amount")) and amount is None:
            findings.append(
                _finding(
                    record,
                    "INVALID_AWARD_AMOUNT",
                    "Award Amount is not a finite numeric value",
                    {"award_amount": record.get("award_amount")},
                    {"formula": "Decimal(award_amount) is finite", "result": False},
                    "Malformed or placeholder source values may result from publication or schema issues.",
                )
            )
        elif amount is not None and amount < 0:
            findings.append(
                _finding(
                    record,
                    "NEGATIVE_AWARD_AMOUNT",
                    "Award Amount is negative and requires source-context review",
                    {"award_amount": str(amount)},
                    {"formula": "award_amount < 0", "result": True},
                    "Deobligations, corrections, or unusual accounting treatment may produce negative values.",
                )
            )
    return findings


def _group_statistics(
    records: list[dict[str, Any]], min_group_size: int
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    amount_records = []
    for record in records:
        amount = _decimal(record.get("award_amount"))
        if amount is not None and amount >= 0:
            amount_records.append((record, float(math.log1p(float(amount)))))

    candidate_keys: dict[str, dict[tuple[str, ...], list[int]]] = {
        "agency_award_type_category": defaultdict(list),
        "agency_award_type": defaultdict(list),
        "agency": defaultdict(list),
    }
    for index, (record, _) in enumerate(amount_records):
        agency = _agency(record)
        award_type = str(record.get("award_type") or "not reported")
        category = _procurement_category(record)
        if category:
            candidate_keys["agency_award_type_category"][(agency, award_type, category)].append(index)
        candidate_keys["agency_award_type"][(agency, award_type)].append(index)
        candidate_keys["agency"][(agency,)].append(index)

    findings = []
    per_award_statistics = []
    compared = 0
    insufficient = 0
    for index, (record, log_amount) in enumerate(amount_records):
        selected = None
        for level, groups in candidate_keys.items():
            matching_key = next((key for key, members in groups.items() if index in members), None)
            if matching_key is not None and len(groups[matching_key]) >= min_group_size:
                selected = (level, matching_key, groups[matching_key])
                break
        if selected is None:
            insufficient += 1
            per_award_statistics.append(
                {
                    "internal_id": record.get("internal_id"),
                    "generated_internal_id": record.get("generated_internal_id"),
                    "award_id": record.get("award_id"),
                    "comparison_group": "",
                    "comparison_group_size": 0,
                    "amount_percentile": None,
                    "robust_z": None,
                    "comparison_method": "insufficient comparison group",
                    "statistical_status": "insufficient_group_size",
                }
            )
            continue

        level, key, member_indexes = selected
        group_values = [amount_records[i][1] for i in member_indexes]
        median = statistics.median(group_values)
        absolute_deviations = [abs(value - median) for value in group_values]
        mad = statistics.median(absolute_deviations)
        amount = _decimal(record.get("award_amount"))
        percentile = 100 * sum(value <= log_amount for value in group_values) / len(group_values)
        robust_z = None
        outlier = False
        comparison: dict[str, Any]
        if mad > 0:
            robust_z = (log_amount - median) / (1.4826 * mad)
            outlier = robust_z >= 3.5
            comparison = {
                "method": "upper modified z-score on log1p(Award Amount)",
                "formula": "(log1p(amount) - group_median) / (1.4826 * MAD)",
                "threshold": 3.5,
                "robust_z": round(robust_z, 4),
                "group_median_log1p": round(median, 6),
                "group_mad_log1p": round(mad, 6),
            }
        else:
            q1 = _quantile(group_values, 0.25)
            q3 = _quantile(group_values, 0.75)
            iqr = q3 - q1
            upper_fence = q3 + 3 * iqr
            outlier = log_amount > upper_fence
            comparison = {
                "method": "upper Tukey fence on log1p(Award Amount); group MAD is zero",
                "formula": "log1p(amount) > Q3 + 3 * IQR",
                "threshold": round(upper_fence, 6),
                "q1_log1p": round(q1, 6),
                "q3_log1p": round(q3, 6),
                "iqr_log1p": round(iqr, 6),
            }
        compared += 1
        group_label = f"{level}: {' | '.join(key)} (n={len(member_indexes)})"
        per_award_statistics.append(
            {
                "internal_id": record.get("internal_id"),
                "generated_internal_id": record.get("generated_internal_id"),
                "award_id": record.get("award_id"),
                "comparison_group": group_label,
                "comparison_group_size": len(member_indexes),
                "amount_percentile": round(percentile, 2),
                "robust_z": round(robust_z, 4) if robust_z is not None else None,
                "comparison_method": comparison["method"],
                "statistical_status": "outlier" if outlier else "within_comparison_rule",
            }
        )
        if outlier:
            calculation = {
                **comparison,
                "award_amount": str(amount),
                "log1p_award_amount": round(log_amount, 6),
                "group_size": len(member_indexes),
                "empirical_percentile": round(percentile, 2),
            }
            findings.append(
                _finding(
                    record,
                    "ROBUST_AMOUNT_OUTLIER",
                    "Award Amount is unusually high relative to a sufficiently sized comparison group",
                    {
                        "award_amount": str(amount),
                        "comparison_group": group_label,
                        "empirical_percentile": round(percentile, 2),
                        "group_median_log1p": round(median, 6),
                        "group_mad_log1p": round(mad, 6),
                    },
                    calculation,
                    "A large award may reflect a multi-year scope, acquisition strategy, option value, or a legitimate difference in contract size; compare like-for-like records and transaction actions.",
                    comparison_group=group_label,
                    percentile=round(percentile, 2),
                    robust_z=round(robust_z, 4) if robust_z is not None else None,
                )
            )
    metrics = {
        "amount_records": len(amount_records),
        "records_with_sufficient_comparison_group": compared,
        "records_without_sufficient_comparison_group": insufficient,
        "minimum_group_size": min_group_size,
        "method": "log1p amount; modified z-score with median/MAD and 3.5 threshold; if MAD=0, upper Tukey fence Q3+3*IQR",
    }
    metrics["records_without_valid_nonnegative_amount"] = len(records) - len(amount_records)
    return findings, metrics, per_award_statistics


def recipient_concentration(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_agency: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    seen_awards: set[tuple[str, str]] = set()
    for record in records:
        recipient_id = record.get("recipient_uei") or record.get("recipient_duns")
        amount = _decimal(record.get("award_amount"))
        if _missing(recipient_id) or amount is None or amount <= 0:
            continue
        agency = _agency(record)
        award_key = str(record.get("generated_internal_id") or record.get("internal_id") or record.get("award_id") or "")
        if award_key and (agency, award_key) in seen_awards:
            continue
        if award_key:
            seen_awards.add((agency, award_key))
        recipient_id = str(recipient_id)
        entry = by_agency[agency].setdefault(
            recipient_id,
            {"recipient_id": recipient_id, "recipient_name": record.get("recipient_name"), "award_count": 0, "award_amount_sum": Decimal("0")},
        )
        entry["award_count"] += 1
        entry["award_amount_sum"] += amount

    results = []
    for agency, recipients in by_agency.items():
        total = sum((entry["award_amount_sum"] for entry in recipients.values()), Decimal("0"))
        ranked = sorted(recipients.values(), key=lambda entry: (-entry["award_amount_sum"], entry["recipient_id"]))
        shares = [entry["award_amount_sum"] / total for entry in recipients.values()] if total else []
        hhi = sum((share * share for share in shares), Decimal("0"))
        for entry in ranked[:10]:
            results.append(
                {
                    "agency": agency,
                    "recipient_id": entry["recipient_id"],
                    "recipient_name": entry["recipient_name"],
                    "award_count": entry["award_count"],
                    "award_amount_sum": str(entry["award_amount_sum"]),
                    "share_of_positive_award_amount": str(entry["award_amount_sum"] / total) if total else "0",
                    "agency_hhi": str(hhi),
                    "recipient_count": len(recipients),
                    "source_basis": "positive award-level Award Amount; not FY obligations",
                }
            )
    return sorted(results, key=lambda row: (row["agency"], -Decimal(row["award_amount_sum"]), row["recipient_id"]))


def repeated_awards(records: list[dict[str, Any]], minimum_awards: int = 3) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        recipient_id = record.get("recipient_uei") or record.get("recipient_duns")
        if _missing(recipient_id):
            continue
        agency = _agency(record)
        key = (agency, str(recipient_id))
        group = groups.setdefault(key, {"agency": agency, "recipient_id": str(recipient_id), "recipient_name": record.get("recipient_name"), "award_ids": set()})
        identifier = record.get("generated_internal_id") or record.get("award_id")
        if not _missing(identifier):
            group["award_ids"].add(str(identifier))
    results = []
    for group in groups.values():
        if len(group["award_ids"]) >= minimum_awards:
            results.append(
                {
                    "agency": group["agency"],
                    "recipient_id": group["recipient_id"],
                    "recipient_name": group["recipient_name"],
                    "distinct_award_count": len(group["award_ids"]),
                    "award_identifiers": " | ".join(sorted(group["award_ids"])),
                    "interpretation": "Repeated awards are descriptive only; not evidence of duplication or wrongdoing.",
                }
            )
    return sorted(results, key=lambda row: (row["agency"], row["recipient_id"]))


def analyze_awards(
    records: list[dict[str, Any]],
    amount_threshold: float = 1_000_000_000,
    min_group_size: int = 20,
) -> dict[str, Any]:
    if min_group_size < 5:
        raise ValueError("min_group_size must be at least 5")
    findings = _legacy_findings(records, amount_threshold)
    statistical_findings, statistics_metrics, amount_statistics = _group_statistics(
        records, min_group_size
    )
    findings.extend(statistical_findings)
    findings.sort(key=lambda item: (item["rule_id"], str(item.get("award_id") or ""), str(item.get("internal_id") or "")))
    rule_counts: dict[str, int] = defaultdict(int)
    for finding in findings:
        rule_counts[finding["rule_id"]] += 1
    return {
        "findings": findings,
        "rule_counts": {
            rule: rule_counts.get(rule, 0)
            for rule in sorted(set(RULE_IDS) | set(rule_counts))
        },
        "missingness": missingness_summary(records),
        "statistics": statistics_metrics,
        "amount_statistics": amount_statistics,
        "recipient_concentration": recipient_concentration(records),
        "repeated_awards": repeated_awards(records),
        "amount_screen_threshold": amount_threshold,
    }
