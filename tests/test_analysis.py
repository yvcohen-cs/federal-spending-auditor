from src.analysis import analyze_awards, missingness_summary, recipient_concentration, repeated_awards


def make_award(index, amount, agency_code="086", recipient_uei="RECIPIENT-1"):
    return {
        "internal_id": index,
        "award_id": f"PIID-{index:04d}",
        "generated_internal_id": f"CONT_AWD_PIID-{index:04d}_{agency_code}",
        "recipient_name": "Example Supplier",
        "recipient_uei": recipient_uei,
        "recipient_duns": None,
        "awarding_agency": "Example Agency",
        "awarding_agency_code": agency_code,
        "awarding_sub_agency_code": "8600",
        "award_type": "not reported",
        "naics_code": "541330",
        "psc_code": None,
        "start_date": "2024-10-01",
        "end_date": "2025-09-30",
        "award_amount": amount,
        "source_record_url": f"https://www.usaspending.gov/award/CONT_AWD_{index}",
    }


def test_robust_outlier_in_sufficient_agency_category_group_has_reproducible_evidence():
    records = [make_award(index, 100_000) for index in range(1, 25)]
    records.append(make_award(25, 1_000_000_000))

    analysis = analyze_awards(records, amount_threshold=2_000_000_000, min_group_size=20)

    findings = [row for row in analysis["findings"] if row["rule_id"] == "ROBUST_AMOUNT_OUTLIER"]
    assert len(findings) == 1
    finding = findings[0]
    assert finding["award_id"] == "PIID-0025"
    assert "Tukey fence" in finding["calculation"]
    assert '"group_size": 25' in finding["calculation"]
    assert '"empirical_percentile": 100.0' in finding["calculation"]
    assert finding["source_record_url"].startswith("https://www.usaspending.gov/award/")
    assert finding["verification_status"] == "unverified"
    assert "multi-year scope" in finding["possible_benign_explanations"]
    assert analysis["statistics"]["minimum_group_size"] == 20


def test_small_cohort_extreme_value_is_not_statistically_flagged():
    records = [make_award(index, 100) for index in range(1, 19)]
    records.append(make_award(19, 1_000_000_000))

    analysis = analyze_awards(records, amount_threshold=2_000_000_000, min_group_size=20)

    assert not [row for row in analysis["findings"] if row["rule_id"] == "ROBUST_AMOUNT_OUTLIER"]
    assert analysis["statistics"]["records_without_sufficient_comparison_group"] == 19


def test_nonfinite_amount_is_reported_as_invalid_not_as_large_outlier():
    records = [make_award(1, "NaN")]

    analysis = analyze_awards(records)

    assert analysis["rule_counts"]["INVALID_AWARD_AMOUNT"] == 1
    assert analysis["rule_counts"]["AWARD_AMOUNT_SCREEN"] == 0
    assert analysis["statistics"]["records_without_valid_nonnegative_amount"] == 1


def test_missingness_concentration_and_repeated_award_summary_are_descriptive():
    records = [make_award(index, 100 * index) for index in range(1, 4)]
    records[0]["psc_code"] = None
    records[1]["recipient_uei"] = None
    records[1]["recipient_duns"] = "DUNS-1"

    missing = {row["field"]: row for row in missingness_summary(records)}
    concentration = recipient_concentration(records)
    repeated = repeated_awards([make_award(index, 100 * index) for index in range(1, 4)])
    analysis = analyze_awards(records, amount_threshold=1_000_000)

    assert missing["psc_code"]["missing_count"] == 3
    assert len(concentration) == 2
    assert {row["recipient_id"] for row in concentration} == {"RECIPIENT-1", "DUNS-1"}
    assert all(row["recipient_count"] == 2 for row in concentration)
    assert len(repeated) == 1
    assert repeated[0]["distinct_award_count"] == 3
    assert "not evidence" in repeated[0]["interpretation"]
    assert "REPEATED_AWARD_ID" not in analysis["rule_counts"]
