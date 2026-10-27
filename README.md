# Federal Spending Auditor

The pipeline downloads a configurable bounded FY2025 sample of federal contract award records from USAspending.gov (default 5,000), saves raw API responses with query metadata and resumable checkpoints, cleans selected fields, and produces evidence-oriented statistical and lifecycle analysis. Findings are screening cues only; they do not establish error or wrongdoing. The Phase 1 award-level CSV and report paths remain available.

## Data source

The client uses the official USAspending.gov Advanced Award Search endpoint, `POST https://api.usaspending.gov/api/v2/search/spending_by_award/`. Its documented request and field behavior is described in the [official API endpoint documentation](https://api.usaspending.gov/docs/endpoints). The request filters the federal fiscal year (October 1, 2024 through September 30, 2025) and contract award type codes A-D, sorts by Award ID, and retrieves at most 5,000 records by default. Agency IDs, NAICS/PSC, and recipient identifiers are retained when supplied.

The endpoint returns award-level records. `Award Amount` is not necessarily the amount obligated in FY2025. A separate `POST https://api.usaspending.gov/api/v2/transactions/` request returns transaction IDs, action dates, modification numbers, and federal action obligations; Phase 2 requests a bounded lifecycle subset and sums only transaction action obligations dated in FY2025. Matching Award IDs alone are never treated as duplicate payments.

For a small cross-source proof of concept, Phase 2 queries the official [FPDS public ATOM feed](https://www.fpds.gov/ezsearch/FEEDS/ATOM) using exact PIID + contracting-agency-code identifiers. It records matches, nonmatches, modifications, and source links. Amount comparisons use only a uniquely latest-dated FPDS modification; ambiguous histories are left uncomparable. USAspending and FPDS can differ in reporting periods, accounting definitions, identifier mappings, coverage, and refresh timing; missing matches and amount differences are not conclusions about error or misconduct.

## Sampling and coverage

Phase 3B defaults to deterministic fiscal-quarter × contract-type strata, with
equal quotas and unused-slot reallocation. Selection is not probability-based or
statistically representative. See [sampling rules, coverage, resume and CLI compatibility](docs/sampling.md).
Use `--sampling-mode legacy` for the original full-year sorted prefix.

Phase 3C4 adds a separate [offline identity matching command](docs/identity-matching.md)
for preserved C3 collections. Award association and action equivalence remain
separate, evidence-linked claims; they do not verify finances or imply misconduct.
The existing pipeline defaults are unchanged.

## Setup

For Linux cloud setup, Python 3.11/3.12 CI, an explicit offline smoke test, and
safe read-only network diagnostics, see [Codex Cloud instructions](docs/cloud.md).

Python 3.11 is recommended. In PowerShell, create or activate the project virtual environment and install dependencies only if they are not already present:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `.venv` already exists and has the listed dependencies, no installation is needed. No API key is required.

## Run

From the project root, fetch and analyze the default FY2025 sample:

```powershell
.\.venv\Scripts\python.exe -m src.federal_spending_auditor
```

Options allow a different bounded target, request rate, comparison cohort, lifecycle subset, FPDS reconciliation subset, and a chosen checkpoint to resume:

```powershell
.\.venv\Scripts\python.exe -m src.federal_spending_auditor --max-records 5000 --page-size 100 --page-delay-seconds 0.25 --min-group-size 20 --lifecycle-awards 10 --reconciliation-sample-size 5
.\.venv\Scripts\python.exe -m src.federal_spending_auditor --resume-run data/raw/fy2025/<run-id>
```

The USAspending client uses a 20-second request timeout and retries timeouts, connection errors, rate limits, and server errors with exponential backoff and `Retry-After` support. Requests pause between pages. Query fingerprints prevent resuming a checkpoint with different parameters. FPDS calls use a separate modest request delay. A failed live request is reported; synthetic data is used only in tests and never silently substituted in outputs.

In this workspace, the VS Code PowerShell terminal may inherit an `SSLKEYLOGFILE` path that is not writable. If HTTPS fails with a TLS key-log `PermissionError`, clear it only for this run and restore it afterward:

```powershell
$savedSslKeylog = $env:SSLKEYLOGFILE
Remove-Item Env:SSLKEYLOGFILE -ErrorAction SilentlyContinue
try { .\.venv\Scripts\python.exe -m src.federal_spending_auditor }
finally { if ($null -ne $savedSslKeylog) { $env:SSLKEYLOGFILE = $savedSslKeylog } }
```

## Outputs

- Raw, unmodified response pages: `data/raw/fy2025/<UTC run id>/`
- USAspending query metadata/checkpoint: `data/raw/fy2025/<UTC run id>/query_metadata.json` and `checkpoint.json`
- FPDS XML and exact query metadata: `data/raw/fpds/<UTC run id>/`
- Cleaned awards with per-record percentile/group status: `data/cleaned/fy2025_contracts.csv`
- Per-award statistical comparison details: `data/cleaned/fy2025_amount_statistics.csv`
- Flagged evidence with rules, inputs, calculations, benign explanations, status, and source links: `reports/fy2025_flagged_records.csv`
- Lifecycle transactions and subset summary: `data/cleaned/fy2025_transactions.csv` and `data/cleaned/fy2025_lifecycle_summary.csv`
- Recipient concentration, repeated awards, and FPDS reconciliation: `reports/fy2025_recipient_concentration.csv`, `reports/fy2025_repeated_awards.csv`, and `reports/fy2025_cross_source_reconciliation.csv`
- Amount distribution chart and summary report: `reports/fy2025_amount_distribution.png` and `reports/fy2025_summary.md`

The statistics use log1p award amounts and modified z-scores with a 3.5 threshold; if group MAD is zero, they use the Q3 + 3×IQR upper Tukey fence. Comparison cohorts are within agency and prefer award type and 2-digit NAICS/PSC where available. Groups below the configured minimum are not ranked. Concentration is descriptive and uses exact UEI or DUNS values without fuzzy identity merges. Repeated awards are not duplicate findings. No risk score or fraud label is generated. NetworkX is not used because Phase 2 does not have verified parent-organization relationship data; names and addresses are not used to infer relationships.

Downloaded data, FPDS source responses, and generated reports are excluded from Git. Review findings manually using their source record/API references and the verification checklist in the report. Raw files may contain public identifiers; do not add them, credentials, or other private information to Git.

## Tests

Tests use synthetic/mocked API and FPDS responses and require no network access:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
