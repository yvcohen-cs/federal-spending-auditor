# Phase 4C14: correction authority and historical parent records

Starting main: `62dd0009cc2141dd0c19be5dee1409ed339d4f34`. This opt-in extension reads original C10 requirements, the C12 parent primary and the C13 graph. It does not change those implementations or their historical reports. Financial eligibility, reconciliation, readiness, production defaults and participant restrictions remain unchanged.

## Reproduced baseline and bounded experiment

C13 selected replay: `b23fd21db6f74c5d1e82a75889da2c7300429816350d31ba7ae7d9684107d90e`. The 24-case cohort replay is `21930461d1b774c1aaede8f27239f94d245c67cf4ca94b06f376b0cfccb34496`: four selected USA actions agree with the reverse window, 1,570 original plans, zero original resolutions. The C14 protocol pins all 58 prior frozen protocol/document files and retains original inventories and C12 evidence.

The [bounded protocol](correction-parent-protocol-v1.json) was written before the lookup. Only USAspending's documented `/api/v2/transactions/` endpoint is admitted. The opaque parent ID `CONT_IDV_DU100G16D01_8600` comes from C12's independently replayed child/parent primary, not a constructed ID or PIID search. The cap is two requests, two pages of five rows, ten rows total, ascending action date, one-second pacing, ten-second connect/read timeouts, 1 MiB bodies, no retries, redirects, credentials or alternate-source fallback. Live access requires both `--capture-parent --live`. Offline replay is the default.

The actual experiment made **one** public API request, returning HTTP 200, five IDV records (modifications `0`, `1`, `2`, `3`, `4`) and `hasNext=true`. No next page was collected. Their native transaction-number component is the literal `-NONE-`, not `0`. Capture contract v1 rejected that unknown component and stopped, preserving the response and original failure. No further API request was made.

After observing this failure, contract v2 was added to admit the records as parent record observations while preserving the transaction number as unknown. This is an explicitly post-observation parser amendment, not a preregistered outcome. The v1 capture continues to replay its original rejection; a separately labeled `record_reassessment` revalidates retained bytes under v2 without repairing, resuming or rewriting the capture. It cannot certify pagination or historical completeness. Future v2 captures retain the same request caps and record unknown components explicitly. Unsupported contract versions fail closed.

The capture inventory is `eb9486d4b6f6dc1257173353bfd3bd32c552cb4b6669968b5b42b5b82f795def`; the response body is `f59db03c62bab5422fb97c6324a46f2ca678730bb9fe46ef784c91c2d51da3bd`. Original content-decoded entity bytes, source URLs, requests, status, retrieval time, metadata, reservations and hashes remain preserved. These are not byte-exact HTTP wire messages. Replay creates no additional independent observation.

## Original requirement resolution: precise scope

The unchanged C10 `OBSERVATIONS['parent_identity']` contract requires applicable instrument semantics, exact referenced parent PIID/agency and a separately cited authoritative parent IDV record. Its narrow missing-primary reason is `parent_award_primary_record_not_observed`. Historical effective applicability, revision completeness, freshness, source coverage and common monetary as-of evidence are separate obligations.

C14 resolves **only** an original USA `parent_identity` requirement with that exact single reason, an insufficient/missing-evidence state, original in-scope child observations with already verified native scope, exact matching source-native parent components, the separately replayed C12 current parent-primary binding, and independently located parent action records that pass v2 record validation. Every original matching child must be supported. Unknown or conflicting instrument/parent semantics, foreign contexts, NOT_EVALUATED requirements, missing records, invalid source metadata or source-record contradictions receive no resolution. FPDS and SAM do not inherit a USA parent-identity promotion.

For each resolution the report retains the original plan ID, previous requirement and dependencies, precise resolved claim, updated typed `ProofRequirement`, original child citations, C12 parent-primary citations, new parent record locators/hashes, and remaining historical applicability blockers. Constructed citation IDs identify proof packets, never real-world entities. The original C10 report and financial decisions are not overwritten.

The actual selected experiment resolves **one original source-local parent award identity/primary-existence requirement**, `evidence-resolution:v1:054b5e2a722d1454fad28454d183886b6698216a3344cd0e91ad02e538f66976`. Across the 24-case cohort this changes original remaining requirements from **1,570 to 1,569**. Five newly captured parent record observations are real-source subproofs; they do not establish five new awards, five historical relationships, or five resolved original requirements. Fully resolved plan IDs and partial-only plan IDs are disjoint. Synthetic resolutions and relations have separate counters and cannot enter real-source results.

No historical applicability interval, complete history, revision archive or financial comparison is authorized by this narrowly qualified identity dimension. All other original requirements retain their previous qualification. This is not a complete contract-history qualification or a recoverable-loss calculation.

## Five independent parent evidence states

`ParentEvidenceState` distinguishes current relationship verified, historical action asserts parent, historical parent record independently located, historical applicability established, and historical applicability unresolved. The current implementation never emits applicability established: the source contract required to support it is absent.

Each historical child keeps its original parent assertion. New source-local USA parent record citations are separate from prior C12 current-parent citations. FPDS referenced IDV modification numbers are re-extracted from exact original XML paths. The selected FPDS references include modifications `0` and `3`; matching USA parent modification records are **candidates only**. A referenced modification without a transaction identifier or validated cross-source parent action mapping does not establish unique parent revision identity. No date proximity, names, amounts, partial-ID join or parent transition inference is used.

## Correction semantics and directed graph

The [source capability assessment](correction-source-capabilities-v1.json) records official URLs, retrieved representation, response metadata, hashes and supporting text. It distinguishes DOCUMENTED, DIRECTLY_OBSERVED, UNVERIFIED and UNSUPPORTED:

- USA documents generated award IDs as effectively permanent, but describes the transaction result ID as internal. Its public table contract does not establish immutable revision IDs or directed replacement semantics. Pinned published deletion implementation processes destination-row deletions and optional downstream ID journals; it does not certify deployed behavior, complete public archives or access to internal storage.
- FPDS official correction help documents correcting a final-status Award or IDV. That UI procedure is not a retained-version API guarantee. No new FPDS API query occurred.
- SAM documents `oldContractId`, version fields and a six-month deleted-contract window under access restrictions. Old identifier context is not an explicit correction edge, higher versions do not select winners, and a six-month window is not historical deletion completeness. No SAM key was configured or sought; no SAM API request occurred.

No live correction-edge adapter has been validated. **Zero real directed correction/replacement relationships are established.** The graph rejects inferred precedence from update/retrieval dates, higher modification labels, equal amounts, source absence, deletion-like labels or reappearance. SAM old-identifier fields remain cited unsupported candidates rather than source-certified replacement edges.

`RevisionStatement` and `DirectedRevision` are versioned dataclasses with explicit validation. The new directed extension retains both observations, original native IDs, exact predecessor content binding, successor occurrence, primary statement citation, rule, timestamp, conflicts and unresolved dependencies. Direct model construction is not evidence admission; the report replays the original body and exact row locator before extracting a statement.

The only admitted directed rule is `synthetic-explicit-revision-v1`, a clearly labeled fixture protocol carried in `_c14_revision`. It is **not** a federal API contract. Live records containing that control are rejected. Synthetic corrections, replacements, deletions and reinstatements exercise the engine; real-source counters remain zero. Missing/ambiguous predecessor occurrences, namespace/profile mismatches and incomplete or changed native contexts cannot create edges. Forks, cycles and contradictory relationship types preserve every assertion as conflicting. No correction winner is selected, and no edge can certify completeness or authorize money. A future live adapter requires an authoritative source relationship contract, retained native predecessors and primary replay tests; merely adding a rule name is insufficient.

## Reports, integrity and usage

`correction_reporting.py` produces deterministic JSON, Markdown and escaped static HTML with a fixed no-network CSP. Reports include the C13 graph, directed extension, source evidence, five parent states, exact original requirement impacts, before/after results and remaining blockers. Untrusted strings cannot break the Markdown JSON fence or execute in HTML. Verification recomputes all projections from primary inputs; re-signing a forged report does not make it valid.

Inputs are bounded, read through no-follow evidence readers and checked again after computation. Outputs use exclusive append-only creation, cooperative locks and a last-written manifest. Reservations precede requests. Bounded bodies and metadata are preserved before semantic admission, so malformed provenance leaves forensic evidence in an uncommitted capture. Interrupted captures are rejected, not silently repaired. Local hashes detect corruption, not upstream authenticity or privileged same-user replacement.

Add `parent_history` to the original C13 case recipe beside `c12_capture`. All other C13 recipe fields retain their meaning.

```sh
# Explicit separately authorized bounded public capture; one original case.
python -m src.correction_reporting --cases /path/to/case.json --capture-parent --live --output /path/to/new-report
# Entirely offline report generation and verification.
python -m src.correction_reporting --cases /path/to/cases.json --output /path/to/new-report
python -m src.correction_reporting --cases /path/to/cases.json --verify-report /path/to/report
```

Exit 0 means a valid bounded report, never a complete history. Exit 1 means a report retaining an incomplete/failed source capture (including the preserved v1 rejection); exit 2 rejects invalid access, schemas, provenance or integrity. Inspect original evidence and choose a new directory for any separately authorized future experiment. No resume or deletion is performed.

Run `python -m pytest -q`, then the explicit offline smoke test documented in README. Adversarial tests cover directed conflicts/cycles, reused IDs, unknown IDV transaction fields, v1/v2 replay, parent changes/candidates, pagination, unavailable APIs, malformed provenance/JSON, interruption, links, tampering, synthetic/live confusion, forged reports and false eligibility. Frozen document hashes remain pinned.

## Phase 4C15

Prioritize a source-specific authoritative parent effective/revision contract and an approved retained-version or correction/deletion interface for these exact native contexts. First resolve SAM authorization and version/offset/schema semantics or FPDS parent-action query support through official documentation. Then implement one bounded adapter with primary predecessor/replacement evidence and adversarial fixtures. If such evidence is unavailable, report the obstacle and preserve unknown applicability, completeness and financial restrictions. Do not broaden production collection, collect participant data, infer misconduct or calculate unsupported losses.
