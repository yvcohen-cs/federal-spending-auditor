# Phase 2 Implementation Plan

## Repository baseline

- Phase 1 is a small Python project with `src/federal_spending_auditor.py`, mocked tests, README instructions, and `.gitignore` rules for downloaded data and generated reports.
- The pre-change Git worktree already contained Phase 1 changes (`README.md`, `.gitignore`, and untracked Phase 1 files). Preserve them; do not commit or push.
- Python 3.11 and the existing `.venv` are available. Do not reinstall or upgrade packages unless validation finds a missing requirement.

## Verified source capabilities

- USAspending Advanced Award Search: `POST https://api.usaspending.gov/api/v2/search/spending_by_award/`.
- A live request accepted award fields `Awarding Agency Code`, `Awarding Sub Agency Code`, `NAICS Code`, and `PSC Code` in addition to Phase 1 identifiers and dates.
- USAspending transaction detail: `POST https://api.usaspending.gov/api/v2/transactions/` with `award_id` set to the award's `generated_internal_id`, plus `page` and `limit`. A live response returned transaction `id`, `action_date`, `modification_number`, and `federal_action_obligation`.
- Independent-source proof of concept: the official FPDS ATOM public feed (`https://www.fpds.gov/ezsearch/FEEDS/ATOM`) returns structured acquisition records. A live search for `PIID:00001 AND CONTRACTING_AGENCY_ID:8600` returned four entries matching the USAspending award ID and awarding sub-agency code, with modification/transaction identifiers. This supports identifier-level reconciliation, not an assertion that either system is complete or financially identical.
- USAspending API docs: https://api.usaspending.gov/docs/endpoints. SAM.gov Data Services landing page: https://sam.gov/content/data-services.

## Implementation steps

1. Extend the USAspending client to a configurable 5,000-award target, preserving official query metadata, rate limiting, retries, raw pages, and a resumable query-fingerprint checkpoint.
2. Preserve the Phase 1 CLI and CSV outputs while adding durable identifiers, agency codes, NAICS/PSC, missingness summaries, robust within-group amount outliers/percentiles, recipient concentration, and repeated-award summaries. Never turn a repeated award ID into a duplicate-payment finding.
3. Add a separate lifecycle module that fetches a deliberately small configurable set of transaction pages and records modification numbers, dates, and federal action obligations separately from award amounts.
4. Add a modular FPDS ATOM adapter and a small PIID + contracting-agency-code reconciliation run. Use explicit matched / unmatched / ambiguous states, retain source links and raw responses, and document timing, identifier, accounting, and coverage differences.
5. Generate explainable finding rows with rules, inputs, calculations, benign explanations, source references, and an unverified status; produce missing-data/coverage summaries, rule-level counts, recipient concentration summaries, deterministic manual-review selection (at most five), and charts. Skip NetworkX unless an evidence-backed parent-organization source becomes available.
6. Keep raw data and reports ignored by Git; document commands and limitations. Add synthetic unit tests for statistics, reconciliation, modifications, retries/API failures, and false-positive cases; run the full suite and a live 5,000-record pipeline when network permits.

## Reporting and interpretation guardrails

- A bounded sorted API sample is not a census and the live dataset can change between runs. Checkpoint metadata captures the query and retrieval state, not an immutable government-data snapshot.
- `Award Amount` is an award-level value; only transaction `federal_action_obligation` values dated in FY2025 can support an FY2025 action-obligation calculation. Do not substitute one for the other.
- FPDS lookup matches contract identifiers and agency codes, while upstream reporting, coverage, and update timing can differ. A missing match is not evidence of misconduct.
- Findings are screening results for human verification, not fraud labels, risk scores, accusations, or legal conclusions.
