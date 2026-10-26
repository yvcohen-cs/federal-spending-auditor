# Phase 3C3: bounded cross-source collection

Workstream C of [Issue #1](https://github.com/yvcohen-cs/federal-spending-auditor/issues/1).
This is a separate opt-in collector for explicitly selected public award
identifiers. It does not change the existing pipeline, CLI flags, outputs,
checkpoints, lifecycle, sampling, or legacy reconciliation. It does not implement
C4/C5/C6 matching, financial comparison, or evidence packets. Query-bound
candidates and anomalous records are not allegations of misconduct.

## Verified contracts and limits of validation

The official [USAspending transactions contract](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/transactions.md)
was read for this implementation (blob `246a2639368fd8908be232a25bbe25fb3e1c9720`).
It documents POST `/api/v2/transactions/`, preferably using generated natural
award IDs; deprecated numeric surrogate IDs are not used here. It documents
page/limit pagination (maximum 5,000), action-date sorting and ascending order,
string action IDs, modification numbers, action dates, and action obligations.
C3 deliberately caps USAspending page size at 100. Extra response fields remain
in preserved evidence; unsupported required structures fail explicitly. Missing
core action fields or nonnumeric obligation types leave returned context unresolved;
they are preserved, never coerced into a financial value or a complete query claim.

The historical [FPDS getting-started URL](https://www.fpds.gov/ezsearch/FPDSNG_Atom_GettingStarted.html)
returned HTTP 404. Its [wiki URL](https://www.fpds.gov/wiki/index.php/Atom_Feed)
returned HTTP 301 to SAM.gov contracting; no redirect was followed. Current
documentation for all FPDS search/pagination semantics was therefore **not**
verified. The existing FPDS public Atom endpoint remains reachable. The guarded
adapter supports the legacy public-feed PIID + CONTRACTING_AGENCY_ID query,
quoted/escaped identifiers, 10-record pages, and same-endpoint Atom next offsets
(`start` or `index`, optionally `s=FPDSNG.COM`). These semantics are regression-
tested with authored fixtures, not asserted universally from current docs.
Unknown next parameters or changed scope stop collection instead of guessing.
No alternate SAM endpoint, authentication route, or undocumented filter is added.

All automated tests are offline. The saved formats from C1/C2 remain supported.
No source-wide snapshot, exact agency crosswalk, global contract uniqueness,
revision precedence, source-refresh guarantee or full-history guarantee is assumed.

## Architecture

- `collection.py`: validated selections/limits, fixed-size bounded query traversal,
  retry scheduling, record-context observations, and completeness summaries.
- `collection_sources.py`: fixed official endpoint requests, bounded Requests
  transport, explicit synthetic transport, source parsing and next-link guards.
- `collection_store.py`: POSIX single-writer journal, immutable attempt evidence,
  fingerprints, reservations, integrity verification and conservative recovery.
- `collection_ingestion.py`: read-only C3 adapters for C2 inventory/manifest
  validation. No schema migration or modification of `src/evidence.py` is needed.
- `collect_evidence.py`: separate opt-in CLI, safe selection/fixture input and
  body-free progress messages. No fallback to fixtures in live mode.

## Explicit selection and usage

Create a selection JSON file containing `awards`, with source-native string
identifiers supplied explicitly. This fictional example is not a real award:

```json
{"awards":[{"generated_id":"CONT_AWD_SYNTHETIC-00001_8600","piid":"SYNTHETIC-00001","agency_id":"8600"}]}
```

USAspending requires `generated_id`; FPDS requires both `piid` and `agency_id`.
Missing context is recorded as unresolved without guessing an agency from a name
or generated-ID string. Optional `parent_piid` and `parent_agency_id` must be
supplied together; they constrain observed context, not an undocumented server
filter. Reusing the same PIID/agency across selected awards is explicitly
ambiguous for FPDS and does not trigger an inferred merge. Duplicate generated
IDs or identical selection rows are rejected. Names/addresses are not inputs.
Original identifier strings, zeros, punctuation, case and spaces remain intact.

Run this fully synthetic example without internet access:

```sh
mkdir -p data/raw/c3
.venv/bin/python -m src.collect_evidence --selection tests/fixtures/c3_selection.json --fixture tests/fixtures/c3_scenario.json --run-dir data/raw/c3/offline-example --retries 0
.venv/bin/python -m src.verify_evidence --root data/raw/c3/offline-example
```

For public records, explicitly supply your authored selection file and omit
`--fixture`. Never use the fictional IDs as evidence of actual awards:

```sh
.venv/bin/python -m src.collect_evidence --selection work/selected-public-awards.json --run-dir data/raw/c3/NEW_RUN --max-awards 1 --max-pages 1 --max-records-total 20 --max-requests 2 --retries 0
```

The run directory must be new; its parent must exist. To resume, repeat identical
arguments and add `--resume`. Changing selections, source order, limits, timing,
schema/collector version, endpoint configuration or fixture contents is rejected
before evidence is overwritten. Use a new run for an intentionally changed query
or another retrieval of the same content. `--sources usaspending` or `--sources
fpds` limits the requested sources. Arbitrary date/agency/name filters are not
accepted. Progress on stderr contains only selection index, source, page and
counts. Stdout is the machine-readable summary, never raw records.

Exit 0 means selected queries exhausted pagination without unresolved context;
it is not an audit assurance. Exit 1 means bounded truncation, missing/ambiguous
selection, context uncertainty or a terminal source error. Exit 2 means invalid
configuration/checkpoint/path/storage. Exit 130 means interruption. Source errors
remain visible in summary tasks and their preserved observations.

Defaults are at most 3 selected awards, 2 pages per source/award, 10 rows per
source/award, 30 total **requested record slots**, and 10 HTTP attempts including
retries. USAspending page size defaults to 10; FPDS is fixed at 10. Limits can be
reduced/configured with documented CLI options (`--help`); hard safety caps remain.
A page's request size never shrinks midway through an offset-pagination task.
If the remaining record budget is smaller than a full next page, collection
stops rather than risking skipped rows by changing page size. FPDS is not queried
when fewer than 10 slots fit. Failed attempts also consume slots, so retries and
resume cannot quietly expand the requested-record budget. Actual records returned
by a nonconforming server cannot be guaranteed solely by client-side limits;
oversized pages fail validation and their bounded body remains preserved.

Live transport uses 20-second connect/read timeouts, two retries, exponential
backoff starting at one second, and half-second pacing. Live pacing below 0.25
seconds is rejected. Timeouts/connection failures, 429 and 5xx are retryable;
permanent 4xx, redirects, TLS errors and structural parse failures are not blindly
retried. Numeric and HTTP-date Retry-After values are honored; instructions or
clock-skew waits exceeding the 60-second wait bound stop instead of retrying early.
Requests uses inherited proxy, TLS verification and CA trust; no settings are
disabled or bypassed. HTTP error status handling never relies on Response
truthiness. Connect/read timeouts are per operation, not a strict total wall-clock
deadline; global attempts and response sizes still bound the work.

## Evidence, provenance and completeness

Each request reserves an attempt durably **before** sending. Every response,
including 429/5xx/permanent errors, is saved before interpretation or retry:

| File | Meaning |
|---|---|
| `c3_plan.json` | Immutable version-1 plan and explicit selections; SHA-256 fingerprint |
| `c3_checkpoint.json` | Version-1 ordered event hashes plus at most one in-flight reservation |
| `c3_attempt_000000.body` | Immutable available application-response bytes, SHA-256 over saved bytes |
| `c3_attempt_000000.json` | Immutable source/method/endpoint/parameters, status, actual retrieval time, completeness/error, body hash and allowed metadata |
| `c3_summary.json` | Replaceable deterministic summary reconstructed from preserved observations |

Requests yields application-body bytes after its ordinary transfer/content
decoding. These bytes are saved without JSON/XML reserialization. They are C1
`response_bytes` with `original_bytes` hash basis, explicitly tagged
`application_body_bytes_not_wire_capture`: no claim of original HTTP framing,
compressed wire bytes, headers, cookies or authentication capture is made.
The byte limit is 8 MiB per response by default; a body exceeding the limit is
saved as a labeled incomplete prefix and is not interpreted as a full response.
Connection failures without a response have no body or retrieval timestamp.
Only Retry-After and raw Last-Modified response metadata are retained; Last-
Modified is not relabeled as a source-wide refresh time. Atom updated values stay
raw per-record observations. Unknown source-update information remains unknown.

C2's offline command verifies the new journal, body/metadata hashes, query context
and locators and emits C1 artifacts/record references inside C2 manifests.
Application bytes, canonical parsed JSON payload IDs, retrieval observation IDs
and native record IDs remain separate. Identical bodies at different timestamps
remain separate attempt files and observations. Old parsed JSON and decoded XML
are not relabeled as response bytes. C1/C2 schemas and historical checkpoints
remain readable; the new checkpoint is separate and cannot migrate old runs.

All returned modifications/actions remain in evidence. Negative obligations,
zero-dollar actions and revisions are retained without arithmetic judgments.
Retrieval duplicate counts use the full parsed USAspending row or full serialized
Atom entry, never PIID/modification alone, and do not imply duplicate payments.
Repeated whole pages or repeated next requests stop pagination. Candidate
association requires exact supplied PIID/agency and observed action context;
missing, nonmatching or multiple contexts are explicit. The cross-source mapping
is user-supplied, not an authoritative agency/award identity verification.

Each task reports independent dimensions:

- `pagination`: complete only after a valid terminal page for that executed query;
- `query_scope`: partial for truncation, failures or unresolved returned context;
- `history`: always unknown, even when pagination is complete;
- `freshness` and `source_wide`: always unknown.

An empty result means only that this query returned no records. It does not
establish source absence, innocence, error, misconduct or historical completeness.

## Recovery, safety, and deliberate limitations

The journal and source bytes are hashed and revalidated on resume. Responses
replay without HTTP; completed runs produce identical substantive summaries.
One fully saved observation ahead of the journal is verified and adopted. If a
reservation survived but no response files did, the outcome is explicitly unknown
and its budget remains consumed; that request is not silently sent again. A
complete plan-only initialization can recover because no request was possible.
Body-only evidence, temporary partial files, corrupt or extra observations,
incompatible plans, missing bytes and changed hashes fail closed for investigation.
Do not delete or overwrite evidence merely to make resume succeed. After a
terminal source error, use a new run for a deliberate new retrieval.

POSIX descriptor-relative no-follow IO, restrictive files, fsync, exclusive immutable
file creation, atomic control-file replacement and an advisory single-writer
directory lock protect normal interrupted runs. Root path components cannot be
symlinks; linked/nonregular evidence and unsafe paths are refused. The trusted
parent must exist and be controlled by the user. Hostile privileged writers,
mount changes, malicious coordinated evidence/hash rewrites, storage loss, and
an atomic upstream snapshot are outside the guarantees. C2 race-detection limits
still apply. POSIX primitives are required; Windows users should use Linux/WSL
or cloud execution. Existing Windows legacy commands are unchanged.

Raw evidence/reports stay under ignored `data/` or `reports/`; never commit them.
Only authored synthetic fixtures, source, tests and documentation belong in Git.
No new dependency is added. Automated tests cover retries, schemas, paging,
selection context, limits, corrupt/partial files, interruption and resume,
body/observation identity, path safety, locking, C1/C2 and legacy compatibility.

## Bounded live validation and remaining assumptions

The preserved live exercise used one selected public Navy award from the official
USAspending contract example, two total HTTP attempts, one page per source,
USAspending page size 1, no retries, and 11 total requested slots. It returned:

- USAspending: HTTP 200, one transaction with string action ID, action_date,
  modification_number and federal_action_obligation. It advertised another page;
  the page cap left pagination partial. No next page was requested.
- FPDS: HTTP 200, a valid empty Atom feed for the selected quoted PIID/agency
  query. This validates endpoint/feed accessibility for that request, not exact
  identifier-search equivalence, nonempty action fields or complete coverage.

Both response bodies, exact sanitized requests, actual timestamps, status and
hashes remain local under ignored
`data/raw/c3/validation-20261026T020958651952Z/`. Offline replay with a transport
that raises on any request was identical, made zero requests, and preserved all
source file bytes. C2 ingestion validated the seven saved files.

A preliminary FPDS reachability GET for the earlier documented PIID/agency query
returned HTTP 200 before this exercise, but its body was not retained. It is not
used as source evidence or claimed as action-field/pagination validation. The
official FPDS documentation probe returned 404 and wiki redirect as noted above.
No further live requests were made after the bounded exercise.

Nonempty FPDS records/next links, interrupted live recovery, negative/zero actions,
multi-page offsets and retries remain validated by synthetic tests rather than
this live exercise. Exact FPDS search semantics and page limits need current
official documentation/nonempty validation before scaling. Historical corrections,
agency crosswalks, parent-award uniqueness, snapshot consistency and reporting
delays remain unresolved. They do not justify wrongdoing inferences.
