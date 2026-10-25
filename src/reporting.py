"""CSV, chart, and evidence-oriented Markdown outputs for Phase 2."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


FINDING_FIELDS = [
    "finding_id",
    "rule_id",
    "detection_rule",
    "internal_id",
    "award_id",
    "generated_internal_id",
    "recipient_uei",
    "recipient_duns",
    "awarding_agency",
    "awarding_agency_code",
    "awarding_sub_agency_code",
    "award_type",
    "naics_code",
    "psc_code",
    "award_amount",
    "source_record_url",
    "source_api_url",
    "input_values",
    "calculation",
    "possible_benign_explanations",
    "verification_status",
    "comparison_group",
    "percentile",
    "robust_z",
    "flag_reasons",
    "duplicate_of",
]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _amount_plot(records: list[dict[str, Any]], path: Path) -> None:
    values = []
    for record in records:
        try:
            amount = float(record.get("award_amount"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(amount) and amount >= 0:
            values.append(math.log10(amount + 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(9, 4.5), constrained_layout=True)
    if values:
        axis.hist(values, bins=min(40, max(8, int(math.sqrt(len(values))))), color="#286c73", edgecolor="white")
        axis.set_ylabel("Award records")
    else:
        axis.text(0.5, 0.5, "No valid nonnegative Award Amount values", ha="center", va="center", transform=axis.transAxes)
        axis.set_yticks([])
    axis.set_title("Award Amount distribution in the bounded sample")
    axis.set_xlabel("log10(Award Amount in USD + 1)")
    axis.text(
        0.01,
        -0.23,
        "Award-level amounts; this chart is not FY2025 action obligations.",
        transform=axis.transAxes,
        fontsize=9,
    )
    figure.savefig(path, dpi=140)
    plt.close(figure)


def _agency_counts(records: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counts = Counter(
        str(record.get("awarding_agency") or record.get("awarding_agency_code") or "Unknown")
        for record in records
    )
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _money(value: Any) -> str:
    try:
        return f"${Decimal(str(value)):,.2f}"
    except Exception:
        return "not available"


def _manual_review_selection(findings: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    return sorted(
        findings,
        key=lambda row: (str(row.get("rule_id") or ""), str(row.get("award_id") or ""), str(row.get("internal_id") or "")),
    )[:limit]


def write_phase2_outputs(
    root: Path,
    fiscal_year: int,
    records: list[dict[str, Any]],
    analysis: dict[str, Any],
    transactions: list[dict[str, Any]],
    lifecycle_summaries: list[dict[str, Any]],
    reconciliation: list[dict[str, Any]],
    run_id: str,
    target_records: int,
    page_size: int,
    lifecycle_award_limit: int,
    reconciliation_sample_size: int,
    sampling_mode: str = "legacy",
) -> dict[str, Path]:
    data_dir = root / "data" / "cleaned"
    reports_dir = root / "reports"
    clean_path = data_dir / f"fy{fiscal_year}_contracts.csv"
    stats_path = data_dir / f"fy{fiscal_year}_amount_statistics.csv"
    findings_path = reports_dir / f"fy{fiscal_year}_flagged_records.csv"
    transactions_path = data_dir / f"fy{fiscal_year}_transactions.csv"
    lifecycle_path = data_dir / f"fy{fiscal_year}_lifecycle_summary.csv"
    concentration_path = reports_dir / f"fy{fiscal_year}_recipient_concentration.csv"
    repeated_path = reports_dir / f"fy{fiscal_year}_repeated_awards.csv"
    reconciliation_path = reports_dir / f"fy{fiscal_year}_cross_source_reconciliation.csv"
    chart_path = reports_dir / f"fy{fiscal_year}_amount_distribution.png"
    report_path = reports_dir / f"fy{fiscal_year}_summary.md"

    statistics_by_internal_id = {
        str(item.get("internal_id")): item for item in analysis["amount_statistics"]
    }
    cleaned_rows = []
    for record in records:
        stats = statistics_by_internal_id.get(str(record.get("internal_id")), {})
        cleaned_rows.append({**record, **stats})
    _write_csv(clean_path, cleaned_rows)
    _write_csv(stats_path, analysis["amount_statistics"])
    _write_csv(findings_path, analysis["findings"], FINDING_FIELDS)
    _write_csv(transactions_path, transactions)
    _write_csv(lifecycle_path, lifecycle_summaries)
    _write_csv(concentration_path, analysis["recipient_concentration"])
    _write_csv(repeated_path, analysis["repeated_awards"])
    _write_csv(reconciliation_path, reconciliation)
    _amount_plot(records, chart_path)

    agencies = _agency_counts(records)
    coverage = {item["field"]: item for item in analysis["missingness"]}
    statuses = Counter(row.get("fpds_status", "unknown") for row in reconciliation)
    amount_comparison_statuses = Counter(
        row.get("amount_comparison_status", "unknown") for row in reconciliation
    )
    lifecycle_statuses = Counter(row.get("status", "unknown") for row in lifecycle_summaries)
    rule_counts = analysis["rule_counts"]
    manual_review = _manual_review_selection(analysis["findings"])
    lines = [
        f"# FY{fiscal_year} Federal Spending Evidence Review",
        "",
        f"- Run ID (UTC): `{run_id}`",
        f"- Records retrieved: {len(records)} of target {target_records}",
        f"- Request page size: {page_size}; records sorted by Award ID ascending.",
        f"- USAspending source: [Advanced Award Search API](https://api.usaspending.gov/api/v2/search/spending_by_award/)",
        f"- USAspending documentation: [API endpoint docs](https://api.usaspending.gov/docs/endpoints)",
        f"- Fiscal-year filter: {fiscal_year - 1}-10-01 through {fiscal_year}-09-30; contract award codes A-D.",
        f"- Sampling mode: {sampling_mode}; deterministic sorted prefixes. Not a census or probability sample. See the companion sampling coverage report for stratified runs.",
        "",
        "## Data coverage",
        "",
        f"- Award records: {len(records)}; agencies represented: {len(agencies)}.",
    ]
    lines.extend(f"- {agency}: {count} record(s)" for agency, count in agencies)
    lines.extend(["", "| Field | Missing | Records | Missing % |", "|---|---:|---:|---:|"])
    lines.extend(
        f"| {row['field']} | {row['missing_count']} | {row['record_count']} | {row['missing_percent']:.2f}% |"
        for row in analysis["missingness"]
    )
    lines.extend(
        [
            "",
            "## Rule-level findings",
            "",
            f"Total finding rows: {len(analysis['findings'])}. These are screening cues, not accusations or conclusions.",
            f"- Award-level absolute review threshold: {_money(analysis['amount_screen_threshold'])}; this is configurable and is not an FY obligation threshold or risk score.",
            "",
        ]
    )
    if rule_counts:
        lines.extend(f"- `{rule}`: {count}" for rule, count in sorted(rule_counts.items()))
    else:
        lines.append("No records met an implemented finding rule in this sample.")
    lines.extend(
        [
            "",
            "### Statistical method",
            "",
            f"- Comparison groups require at least {analysis['statistics']['minimum_group_size']} valid amounts. Group hierarchy is agency + award type + 2-digit NAICS/PSC category, then agency + award type, then agency. Records without a sufficiently sized within-agency group are left unranked.",
            f"- Amounts use log1p transformation. Outliers use modified z-score `(log amount - median) / (1.4826 × MAD)` with threshold 3.5; zero MAD falls back to the upper Tukey fence `Q3 + 3 × IQR`.",
            f"- Records with a sufficient comparison group: {analysis['statistics']['records_with_sufficient_comparison_group']}; without one: {analysis['statistics']['records_without_sufficient_comparison_group']}. Percentiles and group status are in `{stats_path.relative_to(root)}` and the cleaned CSV.",
            "- Statistical thresholds identify unusual values relative to this sample; they are not risk scores and do not determine whether an award is improper.",
            "",
            "## Amount distribution",
            "",
            f"![Award amount distribution]({chart_path.name})",
            "Award Amount is an award-level value, not necessarily the amount obligated during the fiscal year.",
            "",
            "## Recipient concentration and repeated awards",
            "",
            "Concentration uses positive award-level Award Amounts grouped by exact UEI or, when UEI is absent, exact DUNS. UEI/DUNS and names are not fuzzy-merged. Shares and HHI describe this sample only and are not findings.",
        ]
    )
    if analysis["recipient_concentration"]:
        concentration_top = sorted(
            analysis["recipient_concentration"],
            key=lambda row: (-Decimal(row["share_of_positive_award_amount"]), row["agency"], row["recipient_id"]),
        )[:10]
        lines.extend(
            f"- {row['agency']}: recipient ID `{row['recipient_id']}` ({row.get('recipient_name') or 'name missing'}), {row['award_count']} awards; share {Decimal(row['share_of_positive_award_amount']) * 100:.2f}%; agency HHI {Decimal(row['agency_hhi']):.4f}."
            for row in concentration_top
        )
    else:
        lines.append("No positive award amounts with stable UEI/DUNS values were available for concentration calculations.")
    lines.extend(
        [
            f"- Repeated-award groups meeting the descriptive minimum: {len(analysis['repeated_awards'])}. See `{repeated_path.relative_to(root)}`; repeated awards are not duplicate-payment findings.",
            "",
            "## Contract lifecycle",
            "",
            f"- Lifecycle target: up to {lifecycle_award_limit} awards in deterministic Award ID order; fetched transaction records: {len(transactions)}; award status counts: `{dict(lifecycle_statuses)}`.",
            f"- Transaction data is in `{transactions_path.relative_to(root)}` and per-award totals in `{lifecycle_path.relative_to(root)}`.",
            f"- FY action obligations sum `federal_action_obligation` only for transaction action dates in FY{fiscal_year}. These figures cover only the lifecycle subset and are not substituted for award-level Award Amount.",
            "- Transaction modification numbers and IDs identify reported actions; repeated modification/award identifiers are not treated as duplicate payments.",
            "",
            "## Cross-source reconciliation",
            "",
            f"- Source: [FPDS public ATOM feed](https://www.fpds.gov/ezsearch/FEEDS/ATOM); sample target {reconciliation_sample_size}; identifier-match status counts: `{dict(statuses)}`.",
            f"- Amount comparison status counts: `{dict(amount_comparison_statuses)}`.",
            f"- Reconciliation rows: `{reconciliation_path.relative_to(root)}`. The rule is exact trimmed PIID + contracting-agency identifier; record links and modification/transaction IDs are retained.",
            "- Amounts are compared only when FPDS returns one uniquely latest-dated modification record (effective date); ambiguous multi-modification histories are explicitly withheld from amount comparison. Where comparable values exist, the award amount and FPDS total obligated amount are shown side by side with their difference. Their reporting timing and accounting definitions may differ; differences are not automatically flagged as errors.",
            "- FPDS and USAspending may differ in coverage, reporting period, identifier mapping, and refresh timing. FPDS records reflect agency submissions and are not a fully independent audit source. No exact match is not evidence of misconduct.",
            "",
            "## Manual verification queue",
            "",
            "At most five findings are selected deterministically by rule ID and Award ID for convenient review. This ordering is not a ranking of likelihood or severity.",
        ]
    )
    if manual_review:
        for index, finding in enumerate(manual_review, start=1):
            lines.extend(
                [
                    f"### {index}. `{finding['rule_id']}`: Award `{finding.get('award_id') or 'missing'}`",
                    "",
                    f"- Rule: {finding['detection_rule']}",
                    f"- Source identifiers: internal ID `{finding.get('internal_id') or 'missing'}`, generated ID `{finding.get('generated_internal_id') or 'missing'}`, recipient UEI/DUNS `{finding.get('recipient_uei') or finding.get('recipient_duns') or 'missing'}`.",
                    f"- Inputs: `{finding['input_values']}`",
                    f"- Calculation: `{finding['calculation']}`",
                    f"- Possible benign explanations: {finding['possible_benign_explanations']}",
                    f"- Source record: {finding.get('source_record_url') or 'not available'}",
                    f"- Verification status: {finding['verification_status']}",
                    "- Checklist: [ ] Confirm source record and identifiers; [ ] inspect transaction/modification history; [ ] document reporting-period and accounting context; [ ] record reviewer and outcome.",
                    "",
                ]
            )
    else:
        lines.append("No finding rows are currently available for manual review; the queue is empty, not a clearance or assurance.")
    lines.extend(
        [
            "",
            "## Methodological limits",
            "",
            "The first N results sorted by Award ID can underrepresent later identifiers and is not statistically representative. USAspending data can be revised after collection; checkpoint metadata records query and page state, not an immutable source snapshot.",
            "Award Amount is a total award-level field. FY obligations are assessed separately from transaction-level action amounts only for the bounded lifecycle subset. NAICS/PSC and Award Type may be absent, limiting like-for-like cohorts.",
            "Repeated recipient awards, concentration, or unusual amounts can be expected outcomes of mission, acquisition strategy, multi-year scope, or market structure. All findings remain unverified until a person checks the cited records and relevant source documentation.",
            "No personal relationships are inferred from names or addresses. No risk score, fraud label, accusation, or legal conclusion is produced.",
            "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "cleaned_path": clean_path,
        "amount_statistics_path": stats_path,
        "findings_path": findings_path,
        "transactions_path": transactions_path,
        "lifecycle_summary_path": lifecycle_path,
        "concentration_path": concentration_path,
        "repeated_awards_path": repeated_path,
        "reconciliation_path": reconciliation_path,
        "chart_path": chart_path,
        "report_path": report_path,
    }
