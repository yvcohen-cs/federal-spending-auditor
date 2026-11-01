# Phase 4C13: historical contract lineage

C13 adds an opt-in reconstruction engine over original C10 primary captures, prior C12 parent evidence and an explicitly bounded new USAspending reverse-order window. Existing history rules, financial eligibility, reconciliation, readiness and production defaults are unchanged. No historical-completeness certificate or original requirement is automatically promoted.

## Baseline and source research

Starting main is `e96a2ae4af41fbc3f8a9282580c9a3a4c0abab44`. C12 primary replay reproduced one current source parent proof, four public requests, four actions, two coherent pages, zero full historical resolutions and the original 1,570 C10/C11 plans. Its report digest remains `f12a0155fc21b2a9d86846db2f34d39a4cc7998785afc7deff21062a215bc88b`; capture inventory remains `077acc8be36a4930af14161863b7e20d389f39d9bd33b1e11f9e14258658203c`.

The [source capability matrix](historical-source-capabilities-v1.json) distinguishes DOCUMENTED, OBSERVED, UNVERIFIED and UNSUPPORTED. Official USAspending contracts document `/api/v2/transactions/`, native generated award selection, action-date sort and pagination. They do not certify an original-submission archive, directed corrections/deletions or common historical snapshots. No similarly named undocumented transaction-detail data URL was attempted. The documented transaction-search filter is PIID-style search, not a verified complete award/parent/revision selection, so it was not used to expand collection.

The historical FPDS documentation redirect and preserved source metadata remain the limits of current query verification. No new FPDS live query occurred. SAM's guide documents native versions, status, prior contract context and a six-month deletion window; those do not certify complete older histories. No authorized SAM credentials are configured and none were sought. Existing SAM captures can be replayed offline, preserving original field representations and unresolved schema semantics.

## Models and graph

`revision_lineage.py` defines schema-v1 `LineageObservation`, `LineageRelation`, `HistoryFacet`, `CoverageState` and `RelationKind` using standard-library dataclasses/enums. Each observation retains literal native context and identifiers, modification/transaction/parent components, action date, original temporal/update metadata, source-specific monetary fields, exact evidence citation, original content fingerprint, provenance digest, profile and limitations. Constructed node IDs identify evidence occurrences; hashes never establish real-world award identity. Shared per-node citations replace duplicated per-money-field provenance without discarding source values or field paths.

The deterministic graph retains duplicate occurrences and competing content separately. Duplicate classification requires both the parsed-record fingerprint and exact retained monetary-field representations to agree, so float-based record fingerprints cannot hide differing source numeric lexemes. Its relations distinguish same-source content equality, content variation, source-ID reuse across contexts, action-date display order, and the existing exact six-component USA/FPDS association. Source-local identity and cross-source mapping remain separate. SAM never joins USA/FPDS through names, amounts, agency aliases, partial identifiers or matching spelling. SAM native class/type/version/prior-ID fields remain available in observation metadata; an immutable SAM action ID is not invented, and its unique native-action count remains unknown.

Only complete supported native contexts can create date-order or USA/FPDS association edges. Cross-source relations additionally require each observation's existing verified record scope; equal components alone are insufficient. Same-day ties, higher modification labels, later retrieval/update dates, native versions and `oldContractId` do not create revision-precedence edges. No correction winner or parent transition is selected. Parent variation for a reused child PIID/agency remains an ambiguous candidate, potentially involving different awards, rather than an identity graph or established change. Missing modification identifiers are never manufactured.

Graphs are bounded to 1,000 typed observations, 16 MiB node material, 10,000 candidate pairs and 10,000 relations. The full report substantive JSON is capped at 8 MiB; rendered files at 32 MiB each/96 MiB combined. Primary replay uses bounded no-follow reads and checks every source inventory again after computation. Unsupported schema versions, profiles, native namespaces, duplicate original cases, corrupted citations or altered primary evidence fail closed.

## Parent and completeness assessments

Every action's parent pair is a **record assertion**. USA transaction-key components, direct FPDS referenced-IDV fields and SAM contractId fields retain distinct bases. The prior C12 parent primary supports the matching current USA source context only. It is never transferred across source namespaces or treated as proof of parent applicability for a historical modification. Effective intervals, historical changes and parent revision lineage remain unknown.

Nine independent facets cover award identity, parent identity, pagination, modification coverage, historical interval, correction lineage, freshness, monetary semantics and provenance. States are OBSERVED_COMPLETE_FOR_DEFINED_SCOPE, PARTIALLY_OBSERVED, CONFLICTING_EVIDENCE, INSUFFICIENT_EVIDENCE and NOT_EVALUATED. Complete claims are restricted to finite observed native components, supported/revalidated query windows and local integrity. All cited original windows must satisfy the strict page/native contracts before source pagination can be complete; a new successful probe cannot certify an older partial/minimal capture. An unattempted source is NOT_EVALUATED; an empty attempted source is insufficient, never evidence of contract absence.

`comparison_interval` is a separate versioned `HistoricalInterval`. It does not rewrite the frozen original C10 interval or resolution-plan IDs. Observed minimum/maximum dates cannot certify the requested interval, and the entire requested interval remains explicitly uncertified until primary source semantics establish coverage. Overall historical completeness remains unknown even when finite pagination is verified. No graph assessment authorizes monetary arithmetic or changes financial gates.

## Two-request authoritative experiment

`historical_probe.collect(path, c12_path, live=False, synthetic=None)` is offline by default. An actual probe requires an explicitly live C12 anchor and `live=True`. The anchor is independently replayed and the CLI binds the original case before access. Only USAspending's existing public transaction endpoint is allowed. It reuses the bounded HTTP transport, append-only store, C11 native selection and C12 anchor validation. Descending responses remain separate C13 evidence rather than being relabeled as the frozen C3 ascending protocol. This probe requires the original complete paired native parent selection; an unknown parent is not converted into a no-parent history. The original opaque award ID is preserved; requests change only the documented action-date order to descending, with page size two, at most two pages/four rows, one-second pacing, ten-second connect/read timeouts, 1 MiB bodies, no redirects and no retries. No external transport callbacks or authentication fallback are accepted.

Reservations precede requests. Original content-decoded HTTP entity bodies, exact requests, statuses, retrieval timestamps, errors, completeness flags, available HTTP update metadata and hashes are append-only. These are not byte-exact HTTP wire messages. Synthetic transcripts have an explicit separate profile/representation and cannot populate live observations. A commit manifest is written last. Interrupted histories are not repaired, overwritten, resumed or deleted. Partial requests preserve their original evidence; valid earlier pages can remain observed without completeness credit.

The actual two-request experiment for C12's exact `00002` / `8600` selection returned four native actions in two coherent descending pages. The native IDs and canonical parsed record fingerprints agree with C12's ascending window. Raw HTTP bytes remain independently hash-bound; canonical record agreement is not wire equality, common monetary revision, snapshot consistency or universal recall.

Selected reconstruction has 16 observation nodes and 30 relations, representing four native USA action contexts and four preserved FPDS counterparts. Twelve pairwise cross-source observation relations correspond to **four** exact native-component groups, not twelve distinct awards. No new action was discovered. C13 adds one real-source bounded window-agreement subproof, zero new current parent-primary proofs, zero historical parent intervals and **zero resolved original historical requirements**. The prior current-parent proof is retained rather than counted again. A separate synthetic control can support only synthetic subproof counts; real/synthetic cohorts cannot be pooled.

## Reports and original gaps

`historical_lineage_reporting.report(cases)` replays the original C10 requirements from primary evidence and builds independent C13 graphs. Every original plan retains its identifier, previous status, native context, supporting new nodes, affected dimension and remaining dependencies. A window subproof can attach only to a matching complete native context with new supporting observations; unrelated or NOT_EVALUATED plans receive no such credit. Current parent and bidirectional-window subproofs cannot satisfy the broader source-history, correction, historical parent, freshness or common-as-of requirements. Original financial decisions are not recomputed under relaxed rules.

JSON, Markdown and escaped static HTML include the complete graph and citations, readable source-native state tables, duplicate/variant observations, source-specific facets, requested uncertified intervals, original requirement impacts and financial prerequisites. Reports expose narrow source fields rather than recipient details. Verification checks all projections and manifests against a fresh primary recomputation; re-signing a false summary cannot promote evidence. Local hashes detect corruption, not upstream authenticity or privileged same-user replacement.

## Usage

Use the original C11 case recipe, adding `c12_capture` and a new `historical_probe` path. Optional `comparison_interval` uses `HistoricalInterval.to_dict()` (schema version 1), distinct from original `interval`.

```sh
# Explicitly authorized two-request public experiment, one original C12 case only.
python -m src.historical_lineage_reporting --cases /path/to/one-case.json --capture-probe --live --output /path/to/new-report
# Entirely offline graph/report regeneration over preserved inputs.
python -m src.historical_lineage_reporting --cases /path/to/cases.json --output /path/to/new-report
# Verify every projection by replaying original primary evidence.
python -m src.historical_lineage_reporting --cases /path/to/cases.json --verify-report /path/to/report
```

Exit 0 means a valid bounded report, not a certified complete history; exit 1 records an incomplete/failed probe; exit 2 rejects invalid access, controls, inputs or integrity. Use a separately chosen new directory after inspecting an interrupted capture. Do not commit source datasets, generated reports, credentials or private histories.

C14 should obtain an authoritative directed correction/deletion/as-of contract and native historical parent applicability evidence for this exact award. SAM access and offset/schema clarification are prerequisites before any separately authorized authenticated experiment. If that evidence is unavailable, continue building source-specific archival adapters and preserving uncertainty rather than weakening financial or production restrictions.
