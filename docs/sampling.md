# Phase 3B: sampling and coverage

Workstream B of [Issue #1](https://github.com/yvcohen-cs/federal-spending-auditor/issues/1).

## Selection and allocation

The CLI and `run_pipeline` now default to `stratified`: FY quarters crossed with
contract award type codes A, B, C and D (16 ordered strata). Fiscal years run
October 1 through September 30, inclusive. `--sampling-period month|quarter|year`
changes the calendar partition; `--sampling-award-types A B C D` selects a subset
of categories. Categories are deduplicated and sorted; periods are chronological.
No agency universe is guessed: agency coverage is observed, with no agency quota.

For target N and K strata, each receives floor(N/K) slots, with the first N mod K
strata receiving one extra. Empty and small strata release unfilled slots. After
the initial pass, unused slots are redistributed one at a time in canonical
stratum order, skipping exhausted strata, until N unique awards are selected or
all strata are exhausted. Zero-quota strata can receive redistributed slots;
otherwise they remain explicitly unqueried. Small targets can leave most strata
unqueried. Allocations are equal, not proportional to unknown population sizes.

Each stratum requests `Award ID` ascending with a fixed page size, starting at
page 1. Page limits never shrink on the last request: changing limits with offset
pagination could skip records. Unconsumed rows remain in a replayable buffer.
The first selected row for a nonblank `generated_internal_id` wins globally.
Rows with that identity already selected are retrieval duplicates, not duplicate
payments. A shared PIID alone is never an identity key. Different generated
identities sharing a PIID remain separate. Missing/invalid generated identities
are excluded from analysis, counted in coverage and preserved in raw evidence.
No name matching, hash-based identity invention, randomness, or random seed is used.

This deliberately spreads retrieval across periods and categories instead of
one full-year lexicographic prefix. It does **not** establish statistical
representativeness, known selection probabilities, population weights, or a
census. Within-stratum prefix bias remains; fiscal-period queries may overlap at
award level, and global deduplication attributes selected awards to the first
stratum that selects them. API changes, sort ties and live offset pagination can
still cause omissions. Results are reproducible from saved evidence, not guaranteed
to be identical when a changing upstream dataset is queried again.

## CLI compatibility

Existing flags and output filenames remain available. Examples:

```sh
.venv/bin/python -m src.federal_spending_auditor --max-records 5000
.venv/bin/python -m src.federal_spending_auditor --sampling-period month --sampling-award-types A D
.venv/bin/python -m src.federal_spending_auditor --sampling-mode legacy
```

`--sampling-mode legacy` preserves the original full-year Award-ID-prefix client
and its original raw layout/checkpoint format. The public
`USAspendingClient.fetch_contract_awards` method also retains its legacy behavior.
Legacy mode does not gain stratified deduplication or its stronger checkpoint
validation. Explicit legacy checkpoints must resume with `--sampling-mode legacy`.
There is no automatic checkpoint migration. Mixing modes is rejected.

New stratified runs use only documented field spellings: `Recipient DUNS Number`,
`NAICS`, `PSC`, `generated_internal_id`, and `Last Modified Date`, alongside the
existing supported award fields. Cleaning accepts both old and new spellings;
CSV column names remain unchanged. Analysis, lifecycle and FPDS integrations
receive the selected unique award rows. Those later stages are otherwise unchanged.

## Provenance and coverage

The raw run directory contains:

- `query_metadata.json`: versioned query plan, FY boundaries, every stratum's API
  filters, requested fields, sort/order, target, quota allocation, page size,
  safety cap, delay, identity/selection rules and fingerprint.
- `response_000000.json` and subsequent files: the exact parsed API response
  object, wrapped with its request and UTC collection timestamp. No response
  fields are removed; these are JSON evidence, not original HTTP bytes/headers.
- `checkpoint.json`: ordered page-event journal, content hashes and completion.
- `sampling_coverage.json`: current status, failures, observed agency counts,
  requested/selected counts, per-stratum quotas, exhaustion/truncation, observed
  rows, missing identities, processed duplicate rows, buffered rows, all page
  requests/metadata, collection timestamps and observed source modification dates.

`reports/fy2025_sampling_coverage.md` (FY varies) summarizes coverage on successful
collection and pipeline completion; the existing summary names the sampling mode.
The JSON coverage file is also written on collection failure before the error is
propagated. Analysis/reports are not silently produced from incomplete collection.
A complete collection means the selection algorithm finished, not that the API
population was exhausted or that the target was met. An exhausted stratum can
still have buffered rows beyond its quota and be marked truncated. Population
totals/coverage percentages are unknown; observed counts are never denominators
for population coverage. Missing identity counts cover all fetched rows; duplicate
counts cover rows consumed by selection, excluding still-buffered rows. Source
modification dates are observed values, not a guaranteed source refresh timestamp.

## Checkpoints and failures

All selection/query/quota/pagination rules, page size, target, period/types,
fields, endpoint, delay and page safety cap are fingerprinted. Incompatible
checkpoints are rejected before metadata is overwritten. Saved response hashes,
contiguous event sequence, query metadata and replayed requests are checked;
missing or corrupt evidence fails explicitly. A nonempty directory without a
checkpoint is refused. `--resume-run` requires an existing checkpoint.

Resume replays the deterministic allocation and buffers from saved pages, making
no HTTP requests for already saved responses, including a complete run. If a
process stopped between the atomic response write and checkpoint update, the
orphan response at the next expected step is validated and adopted rather than
refetched or overwritten. A malformed saved response remains preserved and blocks
resume; investigate it rather than deleting evidence to hide an error. Atomic
writes protect against half-written JSON, not storage loss or concurrent writers;
use one collector per run directory. Hashes detect changes, not malicious tampering.

Missing/invalid pagination, inconsistent page numbers, empty pages claiming a
next page, and repeated full result pages fail explicitly. A default cap of 1,000
pages per stratum prevents unbounded retrieval, configurable with
`--sampling-max-pages`. Reaching it is an incomplete error, not silent exhaustion.
The cap is fingerprinted: changing it requires a new run directory. Network
errors propagate with partial coverage/checkpoint evidence; production never
substitutes synthetic data. Existing retry, timeout, TLS and proxy behavior is
preserved. Resume cannot recover rows skipped by upstream changes between requests.

## Capability verification and validation limits

The official [spending-by-award API contract](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md)
was inspected for date ranges, contract type codes A–D, field-based ascending
sorting, page/limit pagination, `hasNext`, generated award identity and the field
spellings above. These are documentation-verified capabilities, not new successful
live API probes. No random sort, arbitrary agency code filter, population-count
endpoint, snapshot token or undocumented multi-key sort is assumed.

Live validation was attempted in this cloud session but the inherited HTTP proxy
was unreachable (`proxy:8080`); no successful new live collection or endpoint
capability check was possible. No proxy/TLS restrictions were bypassed. Offline
fixtures verify behavior, not the current upstream dataset or service semantics.

All tests prohibit real Requests HTTP calls. Run:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_federal_spending_auditor.py::test_pipeline_writes_cleaned_flagged_and_summary_outputs
```

Tests cover allocation/calendar boundaries, small/empty and zero-quota strata,
reallocation, missing identities, overlapping queries, shared PIIDs, fixed page
limits, buffered/truncated pages, pagination failures, repeated pages, safety
caps, interrupted/complete/orphan-page resume, incompatible/corrupt checkpoints,
legacy compatibility, and pipeline outputs. Source reconciliation expansion and
evidence packets remain deferred to Workstreams C/D. Findings remain screening
cues, without allegations or fraud probability scores.
