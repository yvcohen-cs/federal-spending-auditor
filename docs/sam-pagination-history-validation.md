# Phase 4C3: SAM pagination and historical evidence validation

Recommendation: **A. Offline prototype only.** No approved `SAM_GOV_API_KEY`
binding was available; the presence-only check was false. **Zero authenticated
SAM award API requests occurred.** Authenticated request/page/record success
metrics are unavailable, not a measured zero-success rate. Official documentation
and authored fixtures do not establish authenticated behavior.

This phase starts from main `ef0ed076dd706e96b663f4d464508b4640fd7ced`, including
merged PR #17. It adds read-only assessments over the existing opt-in C2 research
journal. Production collectors, reconciliation, C4/C5 eligibility, review events,
readiness gates, CLI defaults, checkpoints and outputs are unchanged. A
cross-source disagreement is not an allegation of fraud or misconduct.

## Protocol and evidence boundary

[Protocol v1](sam-semantics-protocol-v1.json) was preregistered in **93000ff** before
new assessment experiments. Its canonical JSON SHA-256 is
`e0a0efc4d2c291e2209750fcc84fa297c4f3987334356306e6f127004c8ed0c7`.
Criterion changes require a new version. The original 4B4, 4C1 and 4C2 protocol
bytes are frozen; the new protocol records their byte hashes and original source
inventory hashes. Existing C2 protocol/replay and saved reports remain readable.

Collection still requires explicit `--live`, a frozen native selection, an
already configured credential and new output roots. The **existing C2 client** is
used unchanged: at most 3 subjects, 12 requests, 2 pages/subject, zero retries,
1 MiB response, 10-second connect/read limits, 32 MiB per capture/output store,
no redirects or alternative hosts. Structural maximum is 6 requests, stricter
than 12; live currently stops globally after its **first** page. A synthetic
pagination result cannot enable a second live page. No broad discovery, fallback,
exports, aggregation, credential acquisition or automatic resume is introduced.

The report may replay up to three bounded, same-profile journals; this is not a
new collection budget or permission to make more requests. Synthetic/live/
untrusted captures cannot be pooled. Duplicate inventories are rejected rather
than counted as new retrievals. The historical 381-occurrence cohort (154 in
scope / 88 out / 139 ambiguous) remains a separate reference, never reclassified.

## Official-source audit, October 29, 2026

[Versioned discrepancy matrix](sam-documentation-matrix-v1.json) contains field
locators, official references, retrieval dates, version labels, byte hashes,
knowledge states and a next verification action for every finding. Its canonical
SHA-256 is `5c34d128a5c49ed7b7d51923072cba5a17f0eeb36eecb47e77fbd5e88d417b2d`.
The implementation pins both matrix and protocol. No finding is labeled
AUTHENTICATED_OBSERVED for this execution.

Sources were retrieved with normal TLS/proxy, no redirects and bounded 2 MiB
documentation downloads, independently of the award API. Downloaded documents
are outside git. They are documentation, not captured award records.

| Official source | Version / bytes | SHA-256 of downloaded bytes |
|---|---|---|
| [GSA guide](https://open.gsa.gov/api/contract-awards/) | Published v1 HTML; 276169 | `46cb995d2d026bef0d5a1e85ff2ec2220c3775b9d3701fded4895f5244ac7fb2` |
| [OpenAPI](https://open.gsa.gov/api/contract-awards/v1/openapi.yaml) | OpenAPI 3.0.1 / info.version 1.0; 53141 | `87ab11d503a19a622dfbb1a1ea8fa840f19440a83b0b2d89cf6132ddb3cfb8fc` |
| [FPDS/SAM variance](https://open.gsa.gov/api/contract-awards/v1/FPDSvsSAM-ContractDataAPI.pdf) | September 08, 2025; 261750 | `699018903f1f79ebb5d2f53fc71db9fad2a94cbe0ffaad63df436bf88e93496e` |

Key findings, all limited to the published documents:

- **DOCUMENTATION_CONFLICT:** request offset is described as a page index with
  default 0; OpenAPI's top-level query offset defaults to 1. Guide examples echo
  offset 1 without explicit submission, and offset 25 with limit 5. The error
  guidance uses offset × limit. None establishes a unique first/next-page
  contract, stable ordering or snapshot isolation.
- **DOCUMENTED:** counters are described as numbers in the guide, while examples
  and the OpenAPI response schema use strings. Preserve original JSON types;
  bounded normalization is for hypothesis checks only.
- **DOCUMENTATION_CONFLICT:** guide status is an object with code/name, while
  OpenAPI TransactionData.status is a string. Preserve the native representation;
  no current/deleted state is inferred from either.
- **DOCUMENTED:** native PIID/identity subtier, contracting subtier and funding
  subtier are distinct; native referenced IDV PIID/subtier, instrument class/type,
  modification and transaction identifiers remain separate. The variance guide
  is a mapping aid, not proof of cross-source semantic equivalence.
- **UNKNOWN:** oldContractId direction/uniqueness and correction/replacement
  applicability; document/core schema versions are not unique action revisions.
- **DOCUMENTED:** action obligations and aggregate totals have distinct source
  paths. Their currency/basis/revision/history compatibility is unverified.
- **DOCUMENTED:** created, approved, signed, performance-start, modified and
  retrieved times differ. publicDeltaDate selects last-modified or reveal date;
  no per-record reveal timestamp path or freshness guarantee is validated.
- **DOCUMENTED:** deleted-only queries have a six-month visibility window and
  account-dependent visibility. **UNSUPPORTED:** treating ExportLoggingInfo.deleted
  as award deletion. **UNKNOWN:** complete deletion/correction history.

The matrix also explicitly marks harness fixtures SYNTHETIC_ONLY and source
history/freshness UNKNOWN. It never upgrades a documented statement to an observed
fact. Future authenticated observations belong in separate cited capture results;
the historical documentation snapshot is not silently rewritten.

## Architecture and data contracts

`src/sam_pagination_assessment.py` adds schema-v1 `PaginationObservation` and the
`Interpretation` enum. Exact submitted parameters and original offset/limit/
totalRecords JSON are retained, including their original types and leading zeros.
Content SHA-256 values refer to canonical parsed row content, never identity.
The assessor checks two **zero-origin hypotheses**:

1. Page index: next offset = previous offset + 1; row start = offset × limit.
2. Record offset: next offset = previous offset + limit; row start = offset.

A third interpretation, including one-origin semantics, remains unresolved unless
supported by a future versioned contract. This assessor does not choose an API
contract. It emits compatible hypotheses and hypothetical terminality separately
from its conclusion. One page or limit 1 cannot distinguish these hypotheses.
Contradictory counters, changing totals/limits, repeated/skipped ranges, overlap,
duplicate content, continuation after terminality and partial-page skips block a
positive conclusion. Unique row reordering is retained without inventing a sort
order. An empty page remains inconclusive about query support, scope and recall.
Errors/rate limiting/authentication failures and interruption remain incomplete.

Only coherent **synthetic** multi-page fixtures can demonstrate bounded query
pagination completion. Live completion remains unknown even if the arithmetic
fits a hypothesis. Neither terminality nor any report certifies transaction
history, source-wide completeness or freshness. Observations retain submitted
parameters, returned counters, response completeness and HTTP status separately.

`src/sam_historical_assessment.py` groups occurrences by canonical record content
and, separately, complete supported native action context (class/type, PIID,
identity subtier, parent pair, modification and transaction). Constructed group
IDs are labeled as such; no native identifier is fabricated. Incomplete native
contexts cannot become complete keys. Repeated capture occurrences of the same
content are distinct from multiple native contexts. Multiple contents for one
native context remain unresolved alternatives, without selecting a winner or
inferring revision/correction direction, deletion, or amount delta.

`src/sam_semantics_reporting.py` revalidates C2 primary bytes/controls through the
existing independent reader, then binds observations to inventory hashes and
checks the source again. Every identity row includes requested and returned
native components, original field paths/values/presence, source versions and C6
primary citations. Missing/null/empty/unsupported/sentinel parent fields remain
unknown; the FPDS definitive-contract no-parent rule is not transferred. No name,
address, amount or approximate-date identity inference is permitted. Separate
immutable native record IDs remain UNKNOWN because none was validated.

Incomplete journals have no trusted completion. Tampered or contradictory
controls, including rehashed inconsistencies, produce no positive claims and
unavailable counts. The diagnostic preserves only inventory hashes and fixed
limitations; it does not salvage unvalidated source content or resume requests.
Filesystem safety/size errors fail closed. Reports cannot mix untrusted and
validated journals.

## Revision-conditioned financial comparison proof obligations

All eight obligations remain UNKNOWN. These are requirements for a future
reviewed design, not user-set switches that enable arithmetic:

1. Authoritative native namespace/award/parent/action identity.
2. Immutable revision identifiers and authoritative correction/supersession links.
3. Independently evidenced common as-of revision and visibility.
4. Award-level deletion/reinstatement lifecycle and entitlement evidence.
5. Compatible action/aggregate basis, currency, scale, precision and sign treatment.
6. Explicit action-history bounds, balances and missing/excluded actions.
7. Source update/reveal/timezone/lag/snapshot evidence.
8. Preserved provenance, independently revalidated citations and human review of
   unresolved contradictions through the existing workflow.

Matching schema versions or timestamps satisfies none of these alone. No C5
financial arithmetic, eligibility or readiness decision is changed here.

## Deterministic outputs and usage

Use new run directories; reports never overwrite captures or existing outputs.
JSON, Markdown (indented code for source values) and escaped static HTML are
independently regenerated on both write and read, with a plan/hash commit.
All three projections must agree with primary evidence. Output location and
execution time are excluded from substantive output; actual retrieval timestamps
remain evidence and can legitimately change the digest.

```sh
python -m src.sam_semantics --offline --run-dir reports/NEW_c3_blocked
python -m src.sam_semantics --demo --run-dir reports/NEW_c3_demo
python -m src.sam_semantics --root reports/SAVED_C2_CAPTURE --run-dir reports/NEW_c3_replay
python -m src.sam_semantics --root reports/RETRIEVAL_A --root reports/RETRIEVAL_B --run-dir reports/NEW_c3_history
```

Offline mode checks credential **presence only**. Replay reads no credential.
The fictional demo uses two in-process pages/three record occurrences; it creates
a separate sibling synthetic journal. These counts do not measure SAM.

Live usage, only with an already approved binding and a frozen C2 selection:

```sh
python -m src.sam_semantics --live --selection work/native-sam-selection.json \
  --capture-dir reports/NEW_c3_capture --run-dir reports/NEW_c3_live
```

No live selection was substituted from a fixture in this execution. Credential
absence causes no request and no capture directory. Exit 1 means completed with
research limitations, 2 invalid/blocked, and 130 interruption. Existing C2 usage
remains valid.

Programmatic validation: `read_report(output, captures=(source_a, source_b))`
recomputes all findings. A report is a projection, never its own trust anchor.

## Security and evidence-integrity self-review

- No new transport implementation, dependency, TLS/proxy exception, redirect,
  retry, alternate endpoint, credential discovery or export route.
- Reuses append-only reservation-before-call C2 evidence, application response
  bytes (not wire captures), credential filtering and bounded secure readers.
  Parsed JSON remains explicitly derived; unsafe bodies never become raw evidence.
- Read-only assessments and independent write/read recomputation reject forged
  eligibility, completeness, migration and proof-obligation upgrades.
- Output is bounded, committed last, escaped, static and separated from source
  roots; symlinks, source mutation and duplicate/mixed inventories are rejected.
- Hashes do not prove remote-server origin or detect an entirely coherent rewrite
  without a separately trusted inventory/signature. A declared live journal is
  not cryptographic proof of authenticated access. This limitation is explicit.
- No additional review-event store, identity graph, ML/fraud score or production
  integration. No dataset, captured award records, credential or generated report
  is committed. This is self-review, not a claim of external reviewer approval.

## Validation and remaining questions

Adversarial fixtures cover both hypotheses, empty/partial/nonterminal pages,
invalid numeric counters, duplicate/reordered/overlapping/skipped pages, changing
totals, authentication/rate limiting, interrupted reservations, rehashed tampering,
unknown parent/action components, conflicting contents, exact agency/date strings,
source mutation, forged projections, stable digests and C2 compatibility.
Test counts, final CI results and repeated artifact digests are recorded in the PR.

Unresolved: zero/one origin and next-page contract; stable sort/snapshot guarantees;
actual query enforcement and empty-result scope; status schema/vocabulary;
source-native immutable record IDs; instrument-specific positive parent absence;
correction/replacement direction; complete deletion visibility; revision alignment;
monetary units/basis; full histories and source freshness. No authenticated source
behavior was established by this phase.

Recommended next phase: first obtain authoritative offset/status clarification,
then, if an approved binding becomes available, preregister a native selection
and collect strictly bounded first-page observations. Evaluate those separately
before any proposal to enable continuation. Establish identity, lifecycle,
financial/history/freshness proof obligations separately before considering a
human-reviewed parallel migration. Production migration is not authorized.

Request reservations, completed attempt metadata, received HTTP responses,
HTTP 2xx responses, complete response bodies, parsed pages and native record
occurrences have separate counters. A timed-out attempt can have a reservation
without a received response; a 401/429 response is received without a successful
HTTP status or parsed award page. Attempt counts do not prove wire delivery.
