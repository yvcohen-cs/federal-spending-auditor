# Phase 4C17: historical parent-modification authority

Starting main: `9348287c115f4fcdbb6b38d512a6ff898103d102`, merged PR #31. The [preregistered protocol](parent-modification-authority-protocol-v1.json) pins all 66 prior documents. The original C16 ZIP is available and independently replayed, including its unchanged nested C15/C14 primary packages. Its SHA256 remains `007167368b8c68313c080fe7a7df6a4e19fd228bbf1df11002c8388a0362ff25`; the full C16 cohort reproduces `93cb6738ad4588775bc9a8de4f21da5eebef4fde0f79ac6562c98417cf9c937d`. All 1,570 original requirement IDs, two prior real resolutions, 1,568 unresolved requirements and nine preserved parent actions were verified before collection. No original source capture is modified.

## Actual historical action and missing authority

The selected action is child PIID `00001`, identity agency `8600`, parent `DU100G16D01` / `8600`, child modification `0`, transaction `0`. Its original USA native action ID is `CONT_TX_8600_8600_00001_0_DU100G16D01_0`. The exact original USA/FPDS action association is revalidated under the existing six-component mapping. Original FPDS XML explicitly references parent modification `0`; the preserved USA parent-IDV modification `0` is independently observed and cited from original bytes.

These establish three separate observations: the child references a parent, the child explicitly references a parent modification in FPDS, and a matching parent modification label exists in USAspending. They do **not** establish an authoritative cross-source parent-action mapping, an effective interval or the applicable historical reporting revision. Levels four and five remain unverified. Action dates, label order, source update timestamps and retrieval order cannot supply that missing rule. Competing child observations and reused parent modification labels remain unresolved. Duplicate occurrences do not create independent corroboration or modification reuse. Invalid parent native-component assertions and ambiguous selected-action associations fail closed; the original competing observations remain preserved.

`parent_modification_authority.py` performs this finite, original-action audit. It admits no real effective-date or correction rule. There are zero established historical parent-applicability intervals and zero authoritative real correction edges. No historical applicability or financial qualification is inferred from the new fallback history.

## Official semantics and authorized access

Three bounded public documentation GETs were preserved with status 200, original decoded entity bytes, exact URLs, retrieval timestamps and hashes. See the [source assessment](parent-modification-source-authority-v1.json). It distinguishes DOCUMENTED, DIRECTLY OBSERVED, UNVERIFIED and UNSUPPORTED capabilities; documentation is never a selected-record API observation.

SAM documents `contractId.referencedIDVModificationNumber` as a string and exposes an `oldContractId` array of prior native identifier components. The reviewed description does not independently establish an effective historical parent revision or a directed retained predecessor edge for the selected action. Contract effective/signed dates and last-modified dates are separate from immutable publication/version evidence. `deletedStatus=yes` is deleted-only visibility within the last six months, subject to revealed/unrevealed scope; it cannot certify complete 2016 deletion history. FPDS documents its final-record correction workflow, without providing a selected retained predecessor relationship. USAspending documents a current transaction table and bounded pagination, without a source-wide history/as-of guarantee.

The repository already has explicit SAM adapters that require `SAM_GOV_API_KEY`. That **known setting only** and the environment's safe credential metadata were checked: no authorization is configured. No credential files were searched, no key was requested in chat, and no protected SAM request was attempted. The exact prerequisite is an existing authorized SAM account/key configured through the supported environment mechanism, appropriate destination scope and entitlement, followed by explicit bounded selected-action validation. A locally created configuration or document is not proof of source authority.

## Real fallback result

The initial `6920` candidate had a nonterminal ten-row original USA query. Before any award-data access, selection moved to original child `0001` / `6925`, parent `DTFH6115A00003` / `6925`, whose original USA query ended after six rows. Selection used native identifiers, missing proof and retrievability, not names, amounts, dates or aliases.

The fallback original requirement is `evidence-resolution:v1:300461544d1f281e610e4e91a2959264d5f7ba152cf01befb3e69551a8b0639d`. One explicitly opted-in experiment made **five** USAspending data requests: exact child summary, the source-returned parent summary, one child transaction page, and two parent transaction pages. It observed six child rows and seven parent-IDV actions (modification labels `0` through `6`), with terminal observed pagination. This is finite query evidence, not complete historical retrieval, recall, deletion coverage or an atomic snapshot. The original nine parent records concern a different parent and remain preserved replay. Repeated child observations are not new independent corroboration.

Exact source-native child and parent keys, original PIID/agency/parent context, complete provenance, finite child-query admission and independent parent records satisfy the **unchanged C14/C16 missing-parent-primary identity/existence rule only**. The resulting cohort has **two previous real resolutions preserved, one additional original real requirement resolved, and 1,567 unresolved requirements**. All original IDs remain conserved. No unsupported proof dimension is upgraded.

`parent_authority_acquisition.py` reuses the existing C12/C14 collectors rather than introducing another network adapter. It caps acquisition at five requests, twenty transaction rows, 1 MiB response bodies, one-second pacing, ten-second connect/read timeouts, no retries, no redirects and USA-only endpoints. Parent requests stop if the child capture is failed or its finite-query contract is incomplete. Plans bind the original unresolved requirement and source inventories. New source captures and the orchestration journal use exclusive append-only files and last-written commits. Interruption is preserved, never silently repaired or resumed. Paths must be separate from original inputs and each other. Response entity bytes are not labeled wire-exact HTTP captures. Missing metadata remains unknown.

## Reproducibility and compatibility

`parent_authority_reporting.py` recomputes the unchanged C16 baseline from its own primary package and local original inputs, then evaluates the separate new captures through the existing qualifier. Qualification can change only for the exact originally unresolved USA parent-primary requirement. Its previous requirement, updated typed requirement, original native identifiers and all primary evidence citations remain in the report. Prior real results, new real results, real partial subproofs, synthetic-only results and remaining IDs are separate.

Canonical JSON, Markdown and escaped static HTML contain the original-action assessment, references, new source observations, unresolved dependencies and monetary preflight. HTML is static with a no-network CSP. Fully re-signed false projections and package indexes are rejected by primary recomputation. Hashes provide local integrity, not authentication of the federal publisher or external certification. No actual human review, participant operation or real-data deletion is introduced.

C17 extends the existing schema-v1 package phase enum and admits at most three case recipes, with an explicit `selected_action` in `cases.json`. It includes the unchanged C16 ZIP, which includes C15/C14: a finite phase-checked chain, not arbitrary recursive trust. Original C14/C15/C16 recipes and receipts retain their behavior. New raw child/parent captures and the source-contract snapshot are preserved. Package qualification covers its included cases only; full-cohort results separately replay all 24 original cases. Reports, raw captures, ZIPs and credentials are not committed.

For a recipe, retain the original C16 cases, including the two original cases represented in the supplied C16 ZIP. Add a separate fallback case with `new_parent_capture` and `new_parent_history` pointing to new directories. The selected-action JSON has exactly `original_case_sha256`, `modification` and `transaction` strings.

```sh
# Offline plan; no network or capture-directory creation.
python -m src.parent_authority_reporting --cases /path/cases.json --baseline-package /path/c16.zip --selected-action /path/action.json --plan-fallback
# One explicit fallback; source and report/journal directories must be new and separate.
python -m src.parent_authority_reporting --cases /path/cases.json --baseline-package /path/c16.zip --selected-action /path/action.json --capture-fallback --live --journal /path/new-journal --output /path/new-report
# Default offline generation and full primary replay.
python -m src.parent_authority_reporting --cases /path/cases.json --baseline-package /path/c16.zip --selected-action /path/action.json --output /path/another-report
python -m src.parent_authority_reporting --cases /path/cases.json --baseline-package /path/c16.zip --selected-action /path/action.json --verify-report /path/new-report
# Explicit staging only: relative cases.json, primary roots, baseline-package.zip,
# official-documents/usa-award-detail.body and .json, generated report/.
python -m src.evidence_package --build-from /path/staging --phase C17 --output /path/c17.zip
python -m src.evidence_package --verify-package /path/c17.zip
```

## Financial readiness and C18

The new preflight preserves original and new source citations, lossless numeric tokens and existing C5 semantics. Transaction obligations and deobligations, modification changes, award totals, IDV ceilings, cumulative values and historical as-of values retain separate bases, currency and precision. No incompatible substitution, aggregation, comparison, delta or suspected-loss calculation is performed. Common revision, historical parent applicability, source coverage and all existing financial eligibility obligations remain required. Production collection, reconciliation, readiness gates and defaults are unchanged.

C18 should obtain one expressly authorized SAM action capture and establish the actual interpretation of its parent-modification and old-ID fields using both primary evidence and source-supported historical/revision semantics. A current referenced label alone must not be promoted to historical applicability. If no authorization is supplied, retain that blocker and pursue another exact public-source obligation; do not broaden collection or weaken financial restrictions.
