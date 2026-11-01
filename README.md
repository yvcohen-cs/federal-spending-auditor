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

Phase 3C5 adds [offline financial semantics and reconciliation](docs/financial-semantics.md)
for compatible observed action obligations. It preserves exact numeric tokens,
uses Decimal arithmetic, and retains uncertainty about revisions and refresh.

Phase 3C6 adds [offline human-review packets](docs/review-packets.md): source-linked
JSON and standalone HTML, with a separate append-only reviewer-note workflow.
Review states do not change automated identity or financial findings.

Phase 3C7 provides the opt-in [end-to-end research workflow](docs/research-workflow.md):
`python -m src.research_pipeline --demo --run-dir reports/NEW_research_demo`.
The complete synthetic demo is offline; exit 1 indicates its intentional evidence
uncertainties, separately from successful technical completion.

Phase 4A adds an opt-in [bounded validation pilot](docs/pilot-validation.md),
with deterministic diversity sampling, explicit metric denominators, synthetic
controls, and separate financial, identity and data-quality research prompts.
Live collection requires `--live`; no pilot result implies misconduct.

Phase 4B1 adds [strict FPDS continuation compatibility and frozen-pilot recovery](docs/fpds-pagination.md).

Phase 4B2 adds opt-in [record identity-scope validation and SAM.gov API readiness](docs/identity-scope.md),
with separate scope metrics and conservative C4/C5 eligibility. Legacy defaults remain unchanged.

Phase 4B3 adds [observed action histories and revision-aware financial research](docs/contract-histories.md),
with separate freshness/coverage evidence, offline pilot evaluation, and bounded live opt-in.

Phase 4B4 adds [preregistered readiness gates and controlled-scale evaluation](docs/readiness.md).
Mode decisions assess evidence quality; they never authorize or enable larger collection.
The bounded probe requires explicit live opt-in; recovery reuses saved evidence
in a new output directory without making network requests.

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

Phase 4C1 adds an opt-in [parent identity and query-scope research layer](docs/parent-identity.md)
with a [preregistered experimental protocol](docs/parent-identity-protocol-v1.json).
It revalidates saved source evidence, preserves unknown parent context, and reports
cited before/after associations without granting financial eligibility or changing
legacy collection, reconciliation, review or readiness defaults:

```sh
python -m src.parent_evidence --demo --run-dir reports/NEW_parent_demo
python -m src.parent_evidence --root reports/p4a-live-24 \
  --holdout-root reports/b4-live-holdout --run-dir reports/NEW_parent_reanalysis
```

Phase 4C2 adds a separate [SAM Contract Awards validation harness](docs/sam-contract-awards-validation.md)
and [preregistered protocol](docs/sam-validation-protocol-v1.json). Without an
already configured credential, live observations remain unavailable and the
recommendation is **Offline prototype only**. Synthetic paging never authorizes
live continuation or changes production, financial or readiness gates:

```sh
python -m src.sam_validation --offline --run-dir reports/NEW_sam_access_report
python -m src.sam_validation --demo --run-dir reports/NEW_sam_validation_demo
```

Phase 4C3 adds a separate, opt-in [SAM pagination and historical evidence assessment](docs/sam-pagination-history-validation.md)
over preserved C2 journals. It does not change production behavior, financial eligibility or readiness.

```sh
python -m src.sam_semantics --offline --run-dir reports/NEW_c3_blocked
python -m src.sam_semantics --demo --run-dir reports/NEW_c3_demo
python -m src.sam_semantics --root reports/SAVED_C2_CAPTURE --run-dir reports/NEW_c3_replay
```

Authenticated behavior remains unverified without an approved credential binding.
Live continuation stays disabled; synthetic pagination never establishes complete history or freshness.

Phase 4C4 adds an opt-in, offline [review workflow validation layer](docs/review-validation.md)
with typed tasks, append-only evidence-quality decisions, two explicitly simulated
review sequences and a [future human-study protocol](docs/human-review-study-v1.md).

```sh
python -m src.review_validation --demo --study-dir reports/NEW_c4_study --run-dir reports/NEW_c4_evaluation
python -m src.review_validation --study-root reports/NEW_c4_study --run-dir reports/NEW_c4_replay
```

No actual human usability or throughput study has been completed. Review acceptance
cannot authorize financial arithmetic, change frozen readiness or enable production screening.

Phase 4C5 provides a minimal, offline [private terminal pilot workflow](docs/pilot-preparation.md)
with consent/session controls, optional timing and aggregate-only reports. Raw
stores and outputs must be outside git worktrees; no actual human study is authorized
or claimed by this preparation phase.

```sh
python -m src.pilot_review --demo --study-root reports/SAVED_C4_STUDY --store /tmp/NEW_c5_simulation --output /tmp/NEW_c5_report
```

See the [prospective governance](docs/pilot-governance-v1.md),
[unfilled consent template](docs/pilot-consent-template-v1.md), and
[participant instructions](docs/pilot-participant-instructions-v1.md).
Simulated results are separate from human measurements; accepting evidence cannot
change financial eligibility, frozen readiness or screening authorization.

Phase 4C6 adds an opt-in [offline coordinator rehearsal](docs/coordinator-rehearsal.md)
with the exact frozen 12-task plan, independently scoped prospective approval
checks, a plain terminal adapter, simulated batch retirement/deletion, and
reproducible aggregate reports. Use `python -m src.coordinator_review --help`.
No actual human pilot, source collection, financial/readiness upgrade or production
screening is authorized. Missing approvals block the prospective gate; backup
deletion, secure erasure and actual accessibility remain unverified.

Phase 4C7 adds an [engineering governance/accessibility/deletion assessment](docs/technical-assessment.md),
versioned findings and pre-pilot requirements, conflict-preserving approval dossiers,
and synthetic deletion-target hardening. New captures bind object identities;
legacy captures remain readable but cannot start new destructive transitions.
Generate offline technical reports with `python -m src.technical_assessment_reporting --help`.
No independent human certification, actual pilot, real-data deletion, financial
eligibility change or production screening authorization is established.

Phase 4C8 adds [review-ready evidence and synthetic workflow hardening](docs/review-preparation.md):
per-object deletion intents/completions, opt-in paged evidence navigation, explicit
unknown/conflicting copy-backup declarations, and commit/test-bound JSON/Markdown/
static HTML review packages. Use `python -m src.review_evidence --help`.
Merged PR #22 remains the baseline; no real enrollment, real-data deletion or
production screening is enabled. External approval and actual AT/human performance
remain unverified.

### Offline award-source diagnostics (Phase 4C9)

Revalidate preserved USAspending/FPDS C3 collections and SAM C2 captures without collection, new arithmetic, or readiness changes:

```sh
python -m src.award_validation --collection /path/to/c3-capture --scope /path/to/scope.json --output /path/to/new-report
```

Optional repeatable `--sam-capture` adds separately scoped SAM evidence. Reports identify observed identity, parent, history, pagination, and provenance gaps; they do not infer misconduct or authorize comparisons. See [the architecture, replay verification, and limitations](docs/award-source-validation.md).

### Contract-history qualification and resolution plans (Phase 4C10)

```sh
python -m src.history_qualification_reporting --collection /path/to/c3-capture --scope /path/to/scope.json --output /path/to/new-qualification-report
```

C10 reconstructs source-local observed histories and produces typed evidence requirements and source-specific resolution plans. Optional `--history-start`, `--history-end`, and `--as-of` declare requested scope without claiming coverage. Use `--verify-report` with the same primary inputs to replay findings. SAM captures remain in a separate namespace. See [qualification architecture and limitations](docs/contract-history-qualification.md). Financial and readiness gates remain unchanged.

### Targeted offline evidence acquisition (Phase 4C11)

```sh
python -m src.evidence_acquisition --cases /path/to/cases.json --run-dir /path/to/new-run --report-dir /path/to/new-report
```

C11 groups primary-replayed C10 requirements into a bounded source-specific queue. Optional `--replay-map` incorporates permitted preserved captures; `--fixture-map` runs explicitly synthetic controls. `--verify-report` recomputes resolution from primary evidence. Live execution is disabled, parent-IDV mappings remain validation dependencies, and no financial/readiness gate is upgraded. See [acquisition architecture, case format, limits and provenance](docs/targeted-evidence-acquisition.md).
