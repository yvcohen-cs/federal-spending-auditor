# Phase 4C15: parent continuation, packages and financial preflight

Starting main is `491216c92696fb31852c7d2a2c5cfded7574d337` (merged C14 PR #29). C15 adds four opt-in modules without changing existing collection, identity, financial, reconciliation, review, readiness or production behavior. The [bounded protocol](parent-coverage-protocol-v1.json) pins 61 prior documents and the original C14 package, capture and cohort digests.

## Baseline and actual progress

The original 24-case C14 report reproduces `35b846d2eb0418636a279294fb2a34df5dcd4379ae93f311f80e1f66f14d20ae`: all 1,570 original plan IDs remain identifiable, one narrowly scoped USA parent-identity/primary-existence requirement is resolved and 1,569 remain unresolved. The separately supplied original ZIP is available: `da24ea28b6d1e1f0e3d9ae3ee011301ac9b481d1de07af236909a5982c85d6c1`. The new verifier independently reproduces its selected-case result, `994f87819dea8d9f9911cb8e1390b2ee6b17d493a590ef93c76b7d96b3717989`, using only ZIP contents in a private temporary directory. This is software primary replay, not an external human audit or authentication of the upstream publisher. A selected-case package does not independently reproduce unincluded cohort cases; the 24-case evaluation separately replays the preserved full primary corpus.

The C14 v1 parent capture still replays its original rejection. Its separate v2 record reassessment remains explicitly labeled and does not repair or resume that capture. Its inventory remains `eb9486d4b6f6dc1257173353bfd3bd32c552cb4b6669968b5b42b5b82f795def`.

C15 made **one** new public USAspending request, for page 2 of the exact parent key returned by C12, with the original five-row page size and ascending action-date order. It returned four records, modification labels `5`, `6`, `7`, `P00001`, and `hasNext=false`. No page 3 request was made. Combined with the five preserved page-1 records, this establishes a **nine-record observed contiguous terminal page chain**. It does not establish source recall, historical completeness or snapshot consistency across capture times. Missing modification labels are never inferred from the mixed label set.

| Evidence outcome | Before | After |
| --- | ---: | ---: |
| Original plans identifiable | 1,570 | 1,570 |
| Previously resolved real requirement preserved | 1 | 1 |
| Additional original real requirements resolved | 0 | 0 |
| Remaining original requirements | 1,569 | 1,569 |
| Observed parent record identifiers | 5 | 9 |
| Historical applicability intervals established | 0 | 0 |
| Authoritative real correction edges | 0 | 0 |
| Complete historical financial qualifications | 0 | 0 |

The new evidence is a finite-query pagination subproof. The unchanged original `source_completeness` requirement also needs authoritative query recall, historical interval, deletion visibility and snapshot/as-of evidence; terminal pages cannot resolve it. Historical parent applicability, correction direction and common monetary revisions remain missing. The previously resolved C14 identity claim is retained, not counted as new. Distinct native record identifiers are deduplicated across captures; repeated observations are not independent corroboration.

## Separately supplied evidence packages

`evidence_package.py` defines schema-v1 `EvidencePackageManifest`, a deterministic exporter and offline verifier. A package contains `cases.json`, exact primary bodies and metadata under declared relative roots, generated report projections, a derived `evidence-index.json`, and a last serialized `package-manifest.json` inventory. The index records source requests, metadata, original body digests, source-native identifiers and component states, retrieval times, pagination, capture/record/reassessment contract versions and limitations. The index and serialized report are **recomputed**, not trusted. The full verification receipt includes every member's digest, package profile, case bindings and exact reconstruction scope.

The original C14 manifest (`schema_version: 1` plus a `files` map) has an explicit legacy reader. It remains unchanged. New manifests use the typed schema and canonical `files_json`; unsupported versions and profile conflicts fail closed. Both formats must reproduce all report projections from primary evidence. A valid hash inventory alone cannot authorize a false conclusion.

Packages support one or two selected cases. Paths are relative and bounded; source/report roots cannot alias. ZIP input is limited to 32 MiB compressed, 256 files, 32 MiB per member and 128 MiB total, with a compression-ratio bound. Encrypted archives, unsupported compression, directories, links/devices, duplicate/case-colliding names, file/directory collisions, traversal, absolute paths, dot paths and partial-file names are rejected. Declared source roots accept known capture layouts rather than arbitrary workspace files. No `extractall`, executable loading, network call, credential lookup or caller-controlled extraction directory is used.

Extraction creates only owned temporary copies through descriptor-relative no-follow operations. Files are private and individually created exclusively. Temporary cleanup does not modify the supplied ZIP or frozen source roots and is not secure erasure. Local hashes do not authenticate remote sources or prevent privileged same-user forgery. Exporters must stage permitted public/synthetic evidence explicitly; the software does not certify that arbitrary user-supplied content is secret-free.

```sh
# Verify the separately supplied original C14 package; JSON receipt includes exact inventory.
python -m src.evidence_package --verify-package /path/to/phase4c14-evidence-package.zip
# Export a self-contained C14 staging directory containing relative cases.json and report/.
python -m src.evidence_package --build-from /path/to/stage --phase C14 --output /path/to/new.zip
# Export/verify a C15 staging directory with the envelope described below.
python -m src.evidence_package --build-from /path/to/c15-stage --phase C15 --output /path/to/new-c15.zip
python -m src.evidence_package --verify-package /path/to/new-c15.zip
```

A C14 recipe is the existing relative case array. A C15 package uses `{"schema_version":1,"cases":[...],"baseline_package":"baseline-package.zip"}`. Add `continuation` beside `parent_history` and `c12_capture`; include the separately supplied C14 ZIP as `baseline-package.zip`. All source paths stay within the package. Its report is stored in `report/`. The verifier replays the nested C14 package, binds its original case/parent inventory and report digest to the local primary replay, then independently replays the C15 result. Nested C15 baselines are rejected. If no package is supplied to a normal report, verification is NOT_SUPPLIED; an unavailable or mismatched supplied package is rejected, never marked verified.

## Offline-first continuation

`parent_continuation.py` reconstructs the entire preserved parent page history and validates the C14 v2 record reassessment, exact C12 parent binding, original request parameters, native IDs, IDV type, dates and complete pagination pointer tuple. Only a validated nonterminal page permits planning. It preserves the opaque generated parent key; it never constructs a key from a PIID or searches by names.

`ContinuationLimits` permits one or two requests and five to ten new rows. Page size remains five: changing it while incrementing page numbers could skip or repeat records. A budget insufficient to reserve another full five-row page stops collection. Allowlist is USA only, fixed documented endpoint, no redirects, no retries, one-second pacing, ten-second connect/read timeouts and 1 MiB bodies. Live access requires both explicit flags and a live bound anchor; synthetic transcripts cannot masquerade as live responses.

Each continuation is a new directory with its own plan, acquisition label/ID, reservations, original responses and last-written commit. Its content-addressed acquisition-evidence ID distinguishes retained executions; copied journals do not create independent evidence. The plan ID identifies the bounded request plan, not a real-world award. Bounded transport evidence is persisted before semantic admission. Missing request histories, uncommitted/interrupted states, changed anchors, mismatched IDs, duplicates/variants and source-order changes are rejected or explicitly conflicting. No source capture is repaired, overwritten, resumed or deleted. Source errors stop without retry/fallback. Request/record caps with a remaining page yield INCOMPLETE_ACQUISITION_BUDGET.

```sh
# No network or report directory required. Recipe may name the future continuation directory.
python -m src.parent_coverage_reporting --cases /path/to/cases.json --baseline-package /path/to/c14.zip --plan-continuation
# One explicitly authorized case, new continuation and report paths only.
python -m src.parent_coverage_reporting --cases /path/to/cases.json --baseline-package /path/to/c14.zip --capture-continuation --live --max-requests 2 --max-records 10 --output /path/to/new-report
# Offline generation and exact primary replay.
python -m src.parent_coverage_reporting --cases /path/to/cases.json --baseline-package /path/to/c14.zip --output /path/to/new-report
python -m src.parent_coverage_reporting --cases /path/to/cases.json --baseline-package /path/to/c14.zip --verify-report /path/to/report
```

## Applicability, source coverage and financial preflight

`history_preflight.py` separates observed parent identifier, located parent record, observed parent modification, historical child reference, and historical applicability. Candidate records require an in-scope supported child assertion and the exact referenced parent PIID/identity-agency pair as well as the literal modification number. Exact FPDS references remain candidates for USA records, not a validated cross-source parent-action mapping. Signed/effective date fields remain observations. No date proximity, higher modification, recipient name, amount, absence or reappearance establishes effective applicability or correction direction. C14's directed engine is unchanged and has no admitted live correction rule.

The pinned USA transaction contract documents page/limit/order behavior and supports the bounded continuation; it supplies no revision archive or atomic historical snapshot guarantee. C14's preserved FPDS correction help documents a final-status correction operation, not a public predecessor relationship. C15 rechecked the official FPDS 1.5 dictionary URL: HTTP 301 to `https://sam.gov/contracting`, with no dictionary body; the redirect was not followed. No historical applicability rule was established. SAM's documented old identifiers, structural/version fields and six-month deletion window remain insufficient; authorized API access is unconfigured and no SAM API request or credential discovery occurred. No FPDS data API query was made.

Coverage reports keep original/native/parent observations, finite pagination, observed modification labels, requested intervals, effective fields, correction/deletion authority, freshness and monetary compatibility separate. HTTP update-after-retrieval conflicts are reported as metadata conflicts; missing, stale, malformed or future markers never certify freshness or revision precedence. Unknown IDV transaction components remain null with original sentinel text, not zero.

Financial preflight lists exact preserved child action fields, parent IDV action fields and separately cited award/IDV summary values. It reuses existing C5 semantics and lossless number-token parsing. Transaction obligations, possible deobligations, cumulative values, totals, IDV values/ceilings and historical as-of values are not substituted. Unmapped summary fields stay undocumented/unknown; an IDV value is never promoted to a child obligation. Currency conflicts stay explicit. No amounts are compared, summed or differenced, and no loss estimate or eligibility upgrade is computed. All existing financial/reconciliation checks and common-revision, historical-parent and source-coverage obligations remain mandatory.

## Validation and next work

Reports use deterministic JSON, Markdown and escaped static HTML with a fixed no-network CSP. Verification recomputes all projections, manifests, indexes and qualification results from preserved inputs; fully re-signed false summaries fail. Outputs use exclusive creation and do not overwrite existing evidence. Original plan IDs, previous resolutions, new partial subproofs, synthetic-only results and remaining blockers have distinct fields. No actual human observations, participant operations, real-data deletion or production screening are introduced.

Run `python -m pytest -q` and the explicit offline pipeline smoke test in README. Tests include ZIP attacks, legacy/new/nested package replay, unknown contract versions, missing pages, duplicate/variant IDs, source changes, stale/future timestamps, currency/field misuse, interrupted acquisitions, synthetic/live confusion and false historical/financial promotion. Generated reports, ZIPs, raw data and credentials stay outside Git.

C16 should validate an authoritative effective-parent or retained predecessor/replacement contract for this exact native context before admitting real applicability or correction edges. A bounded expansion of the narrow parent-primary identity resolver to a few other original plans can proceed separately where source-returned native keys and authorized public access exist. Preserve the financial and readiness restrictions; terminal pagination alone must not become a shortcut to qualification.
