# Phase 4C21: source-bound dependency resolution

## Baseline and actual progress

Starting main is `d662050c560fa485d59a1f64e70f8e523e8522bb`, merged C20 PR #35.
Independent replay reproduces both full C20 cohort reports at canonical SHA-256
`91b7e7a74c7e032ef160ae5ad253baf1bcdfbc4f6e5c69f1a8755d3a15bed692`,
all 1,570 original requirement IDs, eight prior real resolutions and 1,562
unresolved requirements. Both separately preserved C20 packages replay through
C14–C19. The [preregistered protocol](dependency-resolution-protocol-v1.json)
freezes 78 prior documents, including C20's 75 plus its three new documents.

The original shortlist has a concrete acquisition blocker: each child capture
contains ten rows with `hasNext=true` and `next=2`. One page cannot validate the
child transaction contract. C21 adds a separately named, versioned
`DependencyVerificationExperiment` with at most four ten-row child pages and
two source-native detail requests. The legacy `VerificationExperiment` retains
its two-page bound and byte-identical serialization. Existing C3 collection,
C12 native/pointer validation and C14 parent collection/qualification are reused.
No financial qualification rule changes.

Two exact original requirements resolved using real preserved USAspending data:

| Child / agency | Parent / agency | Original requirement ID |
| --- | --- | --- |
| `0001` / `6800` | `EPC17008` / `6800` | `evidence-resolution:v1:140225679eaffd3a8c3192bcabb490404c3f084a840d681f27d4e61e50040cdf` |
| `0001` / `6920` | `DTFAWA11A00237` / `6920` | `evidence-resolution:v1:ed25336764203d9fc45a4ece18775a7e5e14250bdaa8176526495587d73d8ba8` |

The preregistration binds native scopes, original case digests, plan digests,
existing query evidence, access prerequisites, caps, unchanged qualification
rule and expected proof dimension. These are original parent identity/primary
existence requirements, not historical applicability or financial eligibility.
Higher-priority historical and revision dependencies remain blocked.

Actual acquisition used 15 of 16 permitted data requests: 38 EPA child
transactions over four pages and ten parent actions over two pages; 32 FAA child
transactions over four pages and five parent actions over one page. Each fresh
child chain was terminal and source-contract-valid before parent acquisition.
This adds bounded-pagination subproofs but does **not** close an original
historical/source-wide completeness requirement. There are **ten prior-plus-new
real resolutions and 1,560 unresolved original requirements**.

## Source access and historical authority

The supported `SAM_GOV_API_KEY` setting was unconfigured; only its presence was
checked, with no credential discovery, protected request or entitlement claim.
Four bounded official-document GETs were preserved with original entity bytes,
retrieval metadata, hashes, normal TLS, zero retries and no redirect following.
The v1.4 FPDS dictionary URL returned 301 to SAM.gov; dated DoD guidance returned
503. Search snippets identify prospective documentation, not admitted primary
text. No PDF content or historical rule is fabricated from unavailable captures.
Current SAM guide and pinned USA transaction-contract captures returned 200.

For child `00001`/`8600`, parent `DU100G16D01`/`8600`, modification `0`, transaction
`0`, the preserved five-level assessment remains:

1. Parent identity observed.
2. Parent modification reference observed.
3. Parent modification independently retrieved.
4. Authoritative historical applicability rule unsupported.
5. Historical applicability independently verified: insufficient.

C20's documented native-reference instruction remains preserved. Missing
version-specific applicability, explicit parent-action namespace/revision
mapping, retained historical/deleted versions and common-as-of coverage prevent
promotion. `oldContractId`, modification order, matching labels, names, dates
and amounts establish no correction direction. Zero verified historical
intervals, authoritative real correction edges or financial authorizations.

## Implementation and integrity boundaries

The C21 collector, document validator and reporter share one module. An initial
three-module layout exceeded the existing 128-module implementation-fingerprint
bound and broke legacy probe planning. Consolidation restores that behavior
without raising the bound or excluding code from its digest. The installation
now uses all 128 slots; future changes must account for this explicit limit.

`dependency_resolution` creates exact original-target plans, invokes existing
bounded collectors only with explicit `live=True`, gates parent access on the
validated child chain, and replays source/plan inventories before invoking
unchanged C14 qualification. Caps are eight requests, 50 transaction rows,
one MiB per response, ten-second timeout, one-second pacing, zero retries and
zero redirects per target. Failed/incomplete child evidence stops parent access.
Interrupted evidence is preserved; no automatic repair, continuation or retry.
Parent pagination remains separate from history, source-wide completeness,
freshness and revision alignment. Monetary preflight must report integer zero
calculations/comparisons and false authorization.

`dependency_resolution.documentation` validates exact official URLs, metadata types,
entity hashes and representations. Only explicitly reviewed known document
bytes admit a quoted clause. Redirects, incomplete captures, unavailable text
and unreviewed document versions establish no historical/correction authority.
Saved entities after content decoding are not byte-exact wire HTTP messages.

`dependency_resolution.report` consumes primary evidence and verified C20 imports.
All original source roles are checked against verified package file inventories;
shared cases must agree across packages and any separately supplied copy.
Imported cases are recomputed from primary records and checked against original
case bindings. Changed unused files, mixed profiles, duplicate archives and
conflicting baseline declarations fail closed. Baseline imports remain open
only during bounded replay and cannot silently substitute source roles.

The existing seven dependency categories are reused directly. C21's baseline
1,562 obligations contain seven parent-primary, 110 historical applicability,
125 native crosswalk, 264 revision/correction, 132 history-completeness, zero
financial-semantics and 924 other obligations. The two new resolutions are
separate from their original proof/status. All 792 `NOT_EVALUATED` obligations
remain outside the requested native context, not discrepancies. Zero financial
group entries does not imply financial eligibility. No new confidence/scoring
or abstract classification layer is introduced.

## Compact packages and offline use

C21 addresses C20's directory-entry export limit using **verified baseline
imports**. New exports contain one or two new target cases plus the two unchanged
C20 ZIPs, rather than copying their shared source trees. Every imported conclusion
is still recomputed through C20 and its nested C14–C19 evidence. File, byte, path
and ZIP bounds are unchanged. Legacy package phases reject C21 fields and C21
capture contracts smuggled into old roles. Existing legacy inputs retain their
previous behavior and default phase C14.

C21's recipe is exactly:

```json
{"schema_version":1,"cases":[{"collections":["case-0-original"],"scope":{"schema_type":"ScopeRequest","schema_version":1,"namespace":"usa-fpds-v1","piid":"0001","agency":"6800","parent_piid":"EPC17008","parent_agency":"6800","modification":null,"transaction":null},"c21_parent_capture":"case-0-child","c21_parent_history":"case-0-parent"}],"baseline_packages":["baseline-0.zip","baseline-1.zip"]}
```

Each case uses existing `collections`/`scope` plus `c21_parent_capture` and
`c21_parent_history`. The referenced roots must contain the corresponding preserved primary captures.
Only explicit package-relative paths are accepted by the package reader. Stage
new target source roots, both unchanged baseline ZIPs, the four source-document
body/metadata pairs and a primary-recomputed `report/`; never export a workspace.
The package explicitly distinguishes supplied case bindings from verified
imported case bindings. Future package consumers must preserve that distinction.

```sh
python -m src.dependency_resolution --cases /path/cases.json --baseline-package /path/c20-target11.zip --baseline-package /path/c20-target23.zip --source-documents /path/docs --output /path/new-report
python -m src.dependency_resolution --cases /path/cases.json --baseline-package /path/c20-target11.zip --baseline-package /path/c20-target23.zip --source-documents /path/docs --verify-report /path/new-report
python -m src.evidence_package --build-from /path/explicit-stage --phase C21 --output /path/c21.zip
python -m src.evidence_package --verify-package /path/c21.zip
```

Reports are offline JSON, Markdown and escaped static HTML with restrictive CSP.
No execution timestamps enter substantive reports; preserved retrieval timestamps
remain provenance, not freshness certificates. Verify by recomputing all report
projections and commitments from the same primary inputs. Re-signed false
summaries or authority/finance flags fail comparison. Export twice and compare
archive bytes. Canonical report digests differ from newline-terminated file hashes.
A complete 24-case cohort assessment is separate from an included-case package.
No raw datasets, generated reports, private histories or credentials belong in Git.

Live acquisition is a separate explicit API, not an offline CLI side effect:
`dependency_resolution.collect(new_journal, case, live=True)`. It requires the
registered original native scope, new separate capture paths and unchanged
preregistered plan. No API key, endpoint discovery, FPDS collection or production
pipeline hook is introduced.

## Validation and remaining work

Deterministic synthetic tests cover the four-page contract, retained legacy
caps, nonterminal/error stopping, native identity mismatch, unavailable sources,
interrupted capture history, baseline substitution/conflicts, source hashes,
schema versions, HTML injection, re-signed false reports/packages, foreign
contract smuggling, frozen document hashes and false financial authorization.
Synthetic controls establish software behavior, never real source observations.
The completion receipt separately records unstubbed real package/cohort replay,
repeated report/archive digests, full-suite/smoke results and exact-head CI.

```sh
python -m pytest -q
python -m pytest -q -p no:cacheprovider tests/test_federal_spending_auditor.py::test_pipeline_writes_cleaned_flagged_and_summary_outputs
```

Financial eligibility, reconciliation, readiness and production defaults remain
unchanged. No production screening, real participant operations or real-data
deletion is enabled. A cross-source disagreement is not a misconduct allegation.
Hash integrity is not upstream authentication or external certification.

Recommended C22: pursue accessible version-specific FPDS historical rules and
explicit parent-action/revision mappings under legitimate source authorization.
Investigate remaining native counterpart dependencies with exact original
contexts and preregistered caps. Preserve the distinction between bounded
pagination evidence and authoritative historical coverage. Do not select a
correction winner or authorize money comparisons without the missing proofs.
