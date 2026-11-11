# Phase 4C16: targeted source authority and original-gap closure

Starting main: `0347a9d005ed8521551a857d4eeb4deff716dfde` (merged PR #30). The [preregistered protocol](historical-authority-protocol-v1.json) freezes all 63 prior documents and the original evidence/package digests. This phase adds opt-in tools; existing collection, matching, financial reconciliation, readiness and production entry points remain unchanged.

## Selection and inference boundary

The original 24-case cohort contains 1,570 immutable original requirement IDs, one previously resolved real-source requirement, and 1,569 unresolved requirements. Selection uses native identifiers and missing proof obligations, never amounts or recipients. Case 3 (`00001`, agency `8600`) shares parent PIID `DU100G16D01`, agency `8600`, with the independently preserved nine-record parent from case 2 (`00002`). Its original missing-parent-primary requirement is `evidence-resolution:v1:e6c91b7fe82fdffad0afe3f76307517eded419f85b31af0e77d77e15748dd5b8`.

An exact public child-summary GET can establish the missing source-local link to that preserved primary parent. It must return the original generated child key, exact child PIID, supported contract instrument and the exact parent opaque key/PIID/subagency triple. The parent opaque key must have been returned by the source and independently validated in the C15 primary package. No `CONT_IDV` key is constructed. The original child action records must independently have verified native scope, supported identities and the same parent context. Only the unchanged original INSUFFICIENT_EVIDENCE/missing_evidence reason `parent_award_primary_record_not_observed` is eligible. Previously resolved, conflicting, foreign-scope and other-dimensional claims are rejected.

This resolves a narrowly defined identity/primary-existence dependency, when evidence passes. It does not establish which historical parent modification applied to any child action. The current summary is not an effective-date rule. The nine parent observations remain PRESERVED REPLAY, including their original C14 v1 rejection and separate v2 reassessment. They are not recollected or relabeled as new observations. Historical intervals, new authoritative cross-source mappings, real correction edges and historical financial qualifications remain zero.

## Implemented architecture

`authority_binding.py` recomputes a deterministic one-request plan from the original C3 collection and an independently replayed C15 package. `candidate_plan` binds the exact original requirement, original collection digest, original child node IDs, preserved parent source-evidence digest and C15 archive digest. New captures use exclusive append-only storage, a request reservation, original response entity bytes and source metadata, and a final inventory commit. Missing/interrupted states are never silently repaired. Body representations explicitly distinguish decoded HTTP entity bytes from synthetic transcript bytes; neither claims byte-exact HTTP wire capture. Missing Last-Modified and other metadata stay unknown. Only a complete HTTP 200 response with exact admitted fields supports the new binding. Failure/empty/redirect observations never prove absence.

`authority_identity.py` validates typed observation IDs, provenance and source namespaces before grouping the six literal native action components. Only the frozen `usa-fpds-v1` association is admitted. Same-source variants remain conflicting, repeated records do not create independent sources, missing components/scope do not join, and SAM is not silently mapped into this namespace. The audit separates finite verified existing native associations, unsupported mappings, conflicting observations and missing counterparts. It establishes no new current authoritative counterpart, common reporting revision, correction direction or financial authorization. Supporting evidence citations accompany each association.

`authority_reporting.py` independently replays the original C15 package and local primary collections, requires agreement for its packaged original cases, and reevaluates only eligible original claims. Reports retain all original IDs, prior resolutions, new real versus synthetic resolutions, an acquisition decision table, exact citations, preserved counterpart audits and C15 monetary preflight. Reports are canonical JSON, Markdown and escaped static HTML with a no-network CSP. Verification reconstructs all content from primary inputs, not serialized conclusions. Execution timestamps remain in capture provenance, outside deterministic replay operations.

`evidence_package.py` adds explicit C16 admission to the existing versioned framework and scoped primary reads from a verified private temporary copy. C16 includes the unchanged C15 ZIP, which includes the original C14 ZIP: a finite phase-checked chain, not arbitrary recursive package trust. C14/C15 formats and receipt content remain compatible. C16 qualification scope is packaged cases only; the full 24-case evaluation separately requires the preserved cohort inputs. Hashes prove local consistency, not upstream authenticity. All generated reports, captures and ZIPs remain outside Git.

## Source authority and access

The [source capability matrix](historical-source-authority-v1.json) preserves exact official references, retrieval metadata and content hashes. DOCUMENTED behavior is separate from DIRECTLY OBSERVED behavior, UNVERIFIED authority and UNSUPPORTED access. The pinned USAspending award contract documents ParentDetails with `generated_unique_award_id`, `piid`, and `sub_agency_id`. The transaction contract documents a current transaction table and pagination, not a complete archive or as-of snapshot. A source update timestamp does not establish publication time or replacement precedence.

Existing FPDS primary observations contain direct action and referenced-IDV fields; their current query support and upstream completeness are not revalidated in this phase. Official correction help documents a user correction workflow, not an immutable predecessor API. The preserved dictionary request returned HTTP 301, not a dictionary; it was not followed. SAM documentation exposes modification/transaction numbers, referenced IDV modification, `oldContractId`, and a six-month deleted-contract window. These are promising future inputs, not proof of an applicable real predecessor edge or unlimited historical recall. SAM search requires an authorized account/key, which is not configured or sought here. No SAM protected request or FPDS data request is made.

No names, approximate dates, similar amounts, descriptions, agency aliases, hashes or higher modification labels establish identity or revision precedence. Neither record absence nor reappearance establishes deletion/restoration.

## Reproduction

Supply a JSON list of case recipes in the established C15 format. Add `authority_binding` with a new output directory to the single selected original child case. Include the original C15 packaged case in the list so the supplied parent primary package can be matched and independently replayed. The baseline ZIP is the unchanged C15 package, not a newly invented summary.

```sh
# Offline planning: no capture is read or acquired at the future binding path.
python -m src.authority_reporting --cases /path/cases.json --baseline-package /path/c15.zip --plan-binding
# Explicit opt-in only. One documented USA GET, no retries/redirects; new directories only.
python -m src.authority_reporting --cases /path/cases.json --baseline-package /path/c15.zip --capture-binding --live --output /path/new-report
# Default offline generation and full primary verification.
python -m src.authority_reporting --cases /path/cases.json --baseline-package /path/c15.zip --output /path/another-report
python -m src.authority_reporting --cases /path/cases.json --baseline-package /path/c15.zip --verify-report /path/new-report
# Explicit staging directory containing cases.json, primary capture roots,
# unchanged baseline-package.zip and generated report/; never export a workspace.
python -m src.evidence_package --build-from /path/staging --output /path/c16.zip --phase C16
python -m src.evidence_package --verify-package /path/c16.zip
```

The package CLI's exact option names are shown by `python -m src.evidence_package --help`. Live access is never implied by report generation or package verification. No repair/resume, credential fallback, paid infrastructure, production integration, financial arithmetic, participant operations or real-data deletion is added.

## Financial readiness and remaining work

C15 monetary preflight remains mandatory and unchanged. Incremental transaction obligations/deobligations, modification changes, award totals, IDV ceilings, cumulative and historical as-of values retain separate semantics, currency/precision and citations. No substitutions, totals, differences or loss estimates are computed. Native identity is only one obligation; common revision, historical applicability, source coverage and existing eligibility rules remain blockers.

Phase 4C17 should obtain an explicitly authorized SAM selected-action capture and validate the documented referenced-IDV-modification/old-contract-identifier semantics against primary evidence. Admit any real correction/applicability rule only when both a documented rule and exact original action evidence support it. Alternatively, another exact missing-parent-primary requirement can be pursued with an explicit bounded child and independently retrieved parent, retaining the same narrow scope. Do not expand source coverage or financial eligibility based on terminal pagination alone.

## Observed real-source result

The preregistered experiment made one data request at `2026-11-11T05:45:36.201249+00:00`. HTTP 200 returned child `CONT_AWD_00001_8600_DU100G16D01_8600` and exact parent `CONT_IDV_DU100G16D01_8600` / `DU100G16D01` / `8600`. Original response entity SHA256: `dec44721871b6f07cc2ac55a19842cd394870c2748914f87def52ec82cf07221`; capture inventory: `d32a5b8b1425099e9ab014715fe3c250dda7f575e685558168ec47907f0eefc0`. No Last-Modified header was supplied; freshness remains unknown. There were no redirects, retries, parent-history data requests, FPDS data requests or SAM data requests. One separate public documentation GET returned the pinned USA award contract.

Primary replay qualifies the exact selected original missing-parent-primary requirement. The 1,570 original IDs remain unchanged: **one previous resolution preserved, one additional original real requirement resolved, 1,568 unresolved**. The selected two-case report contains 20 original requirements and 18 unresolved. The preserved parent has nine observations; new parent observations, authoritative new cross-source mappings, historical applicability intervals, real correction edges and financial qualifications are all zero. The four original exact child-00001 USA/FPDS action associations are preserved finite native identity evidence, not four new corroborations. Child-00002 competing source observations remain explicit conflicts; no correction winner is selected.

The completion response and PR validation record give final-head CI, full-suite counts and repeated report/package digests. These generated artifacts and raw public captures are preserved separately rather than committed to the repository. Reproduce with the explicit offline commands above; selected-package verification does not imply independent verification of unbundled cohort cases. No external audit, human study, institutional approval or production authorization is claimed.
