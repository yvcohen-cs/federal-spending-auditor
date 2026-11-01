# Phase 4C12 authoritative source verification

This phase adds working public-source validation and offline source-contract replay. It preserves C11's offline-only acquisition API and every legacy collector, financial gate and readiness result. It does not enable unrestricted collection or production screening.

## What changed

`source_contracts.py` validates documented USAspending award-detail and transaction fields from original responses. The new parent lookup follows the **returned** `parent_award.generated_unique_award_id`; it never constructs a CONT_IDV key from PIID/agency or uses names, addresses, amounts or awarding/funding agency aliases. The separately fetched primary record must return that exact key, expected PIID, `category=idv` and a documented IDV instrument type. The child parent PIID and `sub_agency_id` must match the original native selection. No parent-of-parent traversal occurs. Missing/null metadata is retained as a summary observation, never promoted to historical absence.

Transaction validation adds the documented `next`, `previous`, `hasNext`, `hasPrevious` tuple to C3's page check. Missing fields fail the new contract; the old capture and old result remain usable under their original protocol. Encoded transaction identity must also match the requested native award. A quoted query alone cannot supply that proof. Contradictions between encoded and observed modification/action components, unsupported components and mismatched requested parent fields also block source-contract success; consistent noncontiguous modification labels remain observations rather than inferred gaps. Cross-page overlap, same-ID variants, nonterminal chains and reversed action dates prevent a successful contract assessment. Modification labels and signed dates are preserved, without inferred missing modifications, numeric modification ordering, or correction winners. FPDS replay retains its existing direct Atom namespace/path and continuation restrictions. SAM's frozen native schemas and capture tools remain unchanged; equal identifiers do not cross source namespaces.

`source_verification.py` implements a typed `VerificationExperiment` bound to an original C11 queue and request. Its new public transport path is **USAspending only**, explicit and opt-in. Default invocation only reads preserved inputs. At most two award-detail requests plus two transaction pages execute, with a one-second pause between requests, ten-second connect/read timeouts, zero retries, no redirect following and a 1 MiB response bound. CLI page size is two (four transaction rows maximum); the typed API caps page size at ten (twenty rows). No keys are read, no caller-supplied live callbacks are accepted, and no alternate source/host is selected after failure. The existing C3 bounded HTTP transport and append-only checkpoint machinery handle transactions.

A reservation is written before each detail request. Original content-decoded HTTP entity bytes, exact request, status, UTC retrieval time, completeness/error state, Last-Modified/Retry-After metadata when available and hashes are preserved. These are **not byte-exact HTTP wire messages**: HTTPTransport decodes content and does not preserve every header or TLS envelope. Synthetic transcripts have a distinct mode and byte representation. Original source bodies remain outside Git; public projections retain narrow native fields, citations and hashes, excluding recipient details. Partial captures remain for inspection; no automatic repair, retry, resume, overwrite or deletion occurs. A commit manifest is written last, and incomplete bundles are rejected.

## Qualification boundaries

A current source parent-summary link is a **new narrow subproof**, linked to the original parent resolution plan. It is not the complete C10 historical parent requirement: it cannot prove parent applicability for every modification at a common historical revision. Reports explicitly retain `original_historical_requirement_resolved=false`. No C10 implementation or financial eligibility rule changes. Source completeness, historical recall, correction/deletion lineage, common monetary as-of and freshness remain unknown.

Successful transaction captures can enter C11 as `PreservedReplay`; C11 performs no new HTTP request and cannot relabel replay as independent evidence. C12 checks the original queue, stricter source contracts and exact experiment/C11 capture inventory before crediting any C11 resolution. C11 then recomputes qualification from primary inputs. Repeated or failed observations cannot manufacture a resolved requirement. Local manifests detect corruption; a privileged or same-user actor able to replace all primary data and hashes is outside their authentication guarantee.

## Reproducible evaluation

The C11 baseline reproduced 24 cases, 1,570 original plans, eight selected requests and zero newly resolved real-source requirements. Queue digest: `6b6b3d9a88e60e899cd051070c1489bceba10c5cf09bf626fff5e24207c1d7b6`. Report digest: `ddf502db0481b44698c443249682d8490b471c97f52c913fdfeb0f052e3acc82`. Frozen inventory hashes match their prior receipts; 52 previous protocol/document files are pinned in the new protocol.

The explicitly selected preserved case `00002` / `8600`, parent `DU100G16D01` / `8600`, was validated with **four successful public USAspending requests**. The child returned a parent generated ID; a separate parent response confirmed the IDV, and two transaction pages returned four actions already present in the preserved capture. Outcomes:

- One new current source-local parent-link subproof; no inference from a child reference alone.
- Two observed pages passed complete pagination pointer and native record checks.
- Zero previously unobserved transaction actions.
- **Zero newly resolved original real-source historical requirements**; the selected case retains ten original requirements, and the baseline cohort retains 1,570 plans.
- No historical completeness improvement or financial authorization. No SAM or FPDS live API query.

The substantial improvement is an executable, independently replayable native parent-primary lookup and stricter source contracts exercised against real responses. It is not a claim of newly certified financial history. The official research matrix distinguishes documented behaviors, this bounded observation and remaining assumptions. The FPDS wiki redirects to SAM; current query documentation remains unavailable. SAM requires an existing authorized API key; none is configured. No access was attempted. Its documented six-month deletion window would not establish older completeness even with access.

## Usage

Use C11's case-file format with a single original collection and scope. Identifiers and generated IDs come from its preserved source plan. No dataset or generated report belongs in Git.

```sh
# Explicit bounded public experiment: four requests maximum, no retries.
python -m src.source_verification --cases /path/to/one-case.json --run-dir /path/to/new-capture --capture --live --report-dir /path/to/new-report
# Offline incorporation through C11; then deterministic JSON/Markdown/static HTML.
python -m src.source_verification --cases /path/to/one-case.json --run-dir /path/to/capture --acquisition-dir /path/to/new-C11-replay --report-dir /path/to/new-report
# Offline verification always recomputes from primary evidence.
python -m src.source_verification --cases /path/to/one-case.json --run-dir /path/to/capture --acquisition-dir /path/to/C11-replay --verify-report /path/to/report
```

Exit 0 means a validated bounded source subset, not complete history or production readiness; exit 1 records partial or unsuccessful source evidence; exit 2 rejects invalid input/integrity/access state. Interrupted captures require inspection and a separately chosen new directory. Generated JSON, Markdown and static escaped HTML retain supporting citations, original plan/contract context, explicit remaining obligations and source-specific before/after coverage. Verification rejects missing/truncated/tampered projections and recomputes all substantive conclusions; re-signing a false summary is insufficient.

## Next concrete obstacle

C13 should establish authoritative action-level historical parent applicability and correction/deletion lineage for these exact native contexts, with an explicit as-of interval. SAM access, if separately authorized and configured, also requires resolving its documented offset/snapshot ambiguities before continuation. USAspending current award summaries and related-IDV listings cannot substitute for a revision-complete procurement history. Preserve all monetary/readiness restrictions until those primary proofs exist.
