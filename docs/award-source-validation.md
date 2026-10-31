# Phase 4C9: deterministic award source validation

This opt-in offline diagnostic reads existing C3 USAspending/FPDS collections and C2 SAM research captures. It does not collect, resolve source namespaces, perform new arithmetic, or change financial or readiness decisions. It is separate from the production pipeline and the frozen historical protocols.

## Architecture and claims

`src.award_validation` revalidates preserved inventories before and after the existing scope/history and SAM replay adapters. Exact source bytes, metadata, request controls, native identifiers, record locators, and hashes remain in their existing evidence representation. No file is rewritten. Report IDs and ordering derive from substantive inputs; execution time and absolute input paths are excluded.

The version-1 report has `schema_type=AwardSourceValidation`, `schema_version=1`, and `rule_version=award-source-validation-v1`. It contains indexed input inventories, native scope, record occurrences and citations, observed native-action groups, pagination diagnostics, existing comparison assessments, source-artifact issues, and per-record proof obligations. Restrictions are explicit false values. `gap_counts` counts affected observed records, not unique awards or population prevalence.

Action grouping requires every native component (PIID, identity agency, parent PIID, parent agency, modification, transaction). It preserves punctuation and leading zeros. A complete observed key can still be out of requested scope; grouping never certifies identity, parentage, or financial eligibility. Records lacking a complete key remain separate. Same-source content variants remain alternatives, with no inferred correction direction. Missing counterparts mean not observed, never proven absent. Modification numbering is not assumed contiguous. SAM evidence retains its own namespace; matching spelling never joins it to USAspending/FPDS.

The diagnostic also retains the C3 parser's record context. In particular, a USAspending transaction can have an otherwise compatible native transaction identifier but a contradictory explicit `award_id`. That contradiction becomes an explicit blocking gap, independently of the legacy scope assessment. Existing legacy results are retained, not silently replaced.

Pagination checks independently reject missing pages, continuation after a terminal page, conflicting successful page variants, empty nonterminal pages, and overlapping record content. A consistent terminal observed chain does not establish query support, recall, source-wide coverage, snapshot consistency, or complete history. Empty observations are inconclusive. Failed attempts remain visible; this initial version conservatively leaves their diagnostic chain unresolved even if a later retry succeeds. No continuation URL is followed. Existing parsers enforce their frozen continuation restrictions.

Financial gaps include incomplete action context, unresolved identity/parent scope, unsupported monetary observations, absent observed counterparts, variant content, uncertified revisions, freshness semantics, and unknown historical coverage. Existing narrowly scoped comparison statuses are shown as prior assessments, never new authorization. Even synthetic revision controls do not remove C9's real-world revision proof obligation. Award totals, action obligations, payments, and fiscal-year values remain distinct in original typed observations.

## Offline usage

Create a JSON `ScopeRequest` using its existing versioned `to_dict()` representation. No credentials are read or needed.

```sh
python -m src.award_validation \
  --collection /path/to/existing/single-award-c3-collection \
  --scope /path/to/scope.json \
  --sam-capture /path/to/existing/c2-sam-capture \
  --output /path/to/new-report-directory
```

Repeat `--collection` up to eight times and `--sam-capture` up to three times. SAM-only use needs no scope. Inputs must have one declared evidence profile; synthetic and live cohorts cannot be pooled. Identical inventories are not independent retrievals. Existing nonempty output directories and output nested within inputs are rejected. There is no live mode.

Outputs are deterministic `validation.json`, `validation.md`, escaped static `validation.html`, a plan, and a last-written commit manifest. The Markdown summary lists gap counts followed by full source citations and diagnostics. A partial bundle is invalid and preserved for inspection; it is not overwritten or silently repaired. HTML has no active content or external assets.

`read_report(path)` verifies exact manifest bytes and deterministic projections. This is corruption detection, not authenticity: an attacker able to rewrite an entire report can recompute its hashes. Use `verify_report(path, collections, requested, sam_captures=...)` to independently reproduce every claim from preserved primary captures. Trust and external source authenticity cannot be established from local checksums alone. Copies of an identical inventory do not constitute independent evidence.

## Validation and remaining questions

The C9 preregistered offline cases use authored synthetic histories and the existing SAM demo, never observations of actual API behavior. Tests cover every existing history scenario, known explicit award-ID conflicts, native identifier spelling, missing counterparts, duplicate/variant content, pagination-chain contradictions, altered provenance, symlinks/hardlinks, source mutation during replay, altered reports, forged summaries with recomputed manifests, path boundaries, unsupported types, escaping, and repeated output digests.

Validated software behavior: existing adapters can replay these preserved formats and enforce bounded source controls. Not validated API behavior: current endpoint availability, live query recall, FPDS migration availability, source refresh lag, SAM cross-source identifier mapping, correction/deletion lineage, completeness, or common monetary revision. No live requests are performed in this phase.

Next core work should validate authoritative source-native revision and correction linkage on already permitted captures, then develop source-specific proof-obligation resolution with field-level citations. No boolean supplied by a reviewer or this diagnostic should enable financial arithmetic. Complete history and source recall require independent primary evidence. Production screening and actual participant operations remain disabled.
