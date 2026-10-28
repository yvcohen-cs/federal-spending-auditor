# Phase 4B2: record scope and replacement-source readiness

## Plan fixed before validation

Start from main 7de7721 (merged PR #12). Add a versioned record-scope layer
between preserved C3 evidence and opt-in C4/C5 adapters. Keep legacy default
matching, monetary rules, C6 packets and C7/pilot output definitions unchanged.
Preserve every occurrence, its native strings, provenance and raw source bytes.
Only verified scope associations enter eligible C4 records; all other records
remain reviewable in the scope report. Conflicting native versions cannot be
removed to manufacture a clean match. New scope-v1 metrics are separate from
Phase 4A/4B1 baseline measurements.

Implementation sequence: (1) strict scope contracts and deterministic rules;
(2) read-only occurrence adapters and additive C4/C5 filtering; (3) opt-in scope
command, synthetic demonstration and metrics; (4) documented SAM v1 boundary and
bounded authenticated adapter only for supported contracts; (5) adversarial tests,
small live validation if permitted, full regressions/CI and a draft PR.

## Official identity research (accessed 2026-10-28, Pacific time)

- [FPDS modification help](https://beta.fpds.gov/help/Modifications.htm) identifies
  agency/PIID and modification context. [FPDS schema changes](https://www.fpds.gov/downloads/FPDS-Specifications-Version15-Changes.pdf)
  distinguish awardContractID from referencedIDVID, including transaction and
  modification fields. Legacy specifications can redirect or be unavailable;
  indexed historical text is not a live schema guarantee.
- [Treasury's analyst guide](https://www.usaspending.gov/federal-spending-guide)
  describes award-summary keys and parent IDV PIIDs. Existing C4's narrowly
  supported CONT_TX parser remains the rule for USA transaction IDs; generated
  award IDs, names, amounts and agency display labels are not new crosswalks.
- [FPDS BOA help](https://www.fpds.gov/help/Create_a_BOA.htm) is form-specific;
  it does **not** establish that missing parent fields on arbitrary award
  transactions mean no parent. IDV/form-specific non-applicability is not
  implemented as a general award rule. A machine-readable positive absence
  rule for the supported award subset remains unvalidated.

Award association uses native PIID, identity-owning agency and applicable parent
context. Actions additionally require modification/transaction context. Funding,
contracting, top-tier and identity-subtier codes are different namespaces unless
specific official mappings justify equivalence. No agency-name inference, padding,
case folding or punctuation removal is introduced.

Parent states remain separate: known compatible, known conflicting, omitted or
unknown, unsupported/ambiguous, and authoritatively not applicable. The last state
is reserved but not inferred in v1. Null, absent, blank and native sentinel tokens
remain distinguishable original values; none alone asserts no-parent status.

## Scope policy

Statuses concern the exact requested context, not wrongdoing: verified_in_scope,
verified_out_of_scope, ambiguous_scope, insufficient_identity, unsupported_schema.
Each occurrence records requested/observed fields, comparisons, rationale, missing
prerequisites, parser/rule versions and an original body hash/record locator.
Known conflicting requested identifiers establish out-of-scope; missing fields
do not. Unknown requested parent context remains ambiguous even when PIID/agency
match. Only explicit compatible parent context can verify a parent-bound award
in this first conservative policy. Unrequested modifications are distinct actions,
not discrepancies; requested action fields are compared exactly when supplied.

Unsupported XML/JSON structures are never coerced into identities. Unparseable
bodies have unknown row counts and artifact-level diagnostics rather than fake
records. Duplicate content and distinct retrieval observations are separate units.
Conflicting supported native IDs/composite action keys block affected eligible
records, including conflicts found in otherwise excluded records.

## Source compatibility matrix

| Dimension | USAspending C3 transactions | FPDS Atom | SAM Contract Awards v1 |
|---|---|---|---|
| PIID | supported CONT_TX component | awardContractID/PIID | contractId.piid |
| Identity agency | supported CONT_TX component | awardContractID/agencyID | contractId.subtier.code |
| Parent | CONT_TX parent PIID/agency; sentinels unavailable | referencedIDVID PIID/agencyID | referencedIDVPiid/referencedIDVSubtier.code |
| Action | modification_number plus supported ID transaction component | modNumber/transactionNumber | modificationNumber/transactionNumber |
| Automatic comparison | existing C4 rules, opt-in scope filtering | existing C4 rules, opt-in scope filtering | no automatic C4/C5 mapping |

The [official migration comparison](https://open.gsa.gov/api/contract-awards/v1/FPDSvsSAM-ContractDataAPI.pdf)
(September 8, 2025) distinguishes identity-agency query piidSubtierCode from
contractingSubtierCode and documents schema differences. Structural field
correspondence is not an implemented identity equivalence. The runtime
identity-matrix-v1 lists unsupported crosswalks explicitly. SAM requests use a
different explicit native namespace; a USA/FPDS request cannot silently become
a SAM scope assertion. Source lineage is shared or not established independent:
two representations of procurement records are never counted as independent
corroboration. No names, monetary similarity, oldContractId substitution or
contractor graph is used.

## SAM readiness and supported boundary

[Official API documentation](https://open.gsa.gov/api/contract-awards/) establishes
the production GET endpoint api.sam.gov/contract-awards/v1/search and requires a
SAM account API key, including revealed data. Roles affect visibility; system
accounts may require IP allowlisting. Listed daily quotas range from 10 requests
for a non-federal personal account without a role to 10,000 for a federal system
account. These are account defaults, not entitlements this program verifies.

The first-page prototype requests only contractId, piid, piidSubtierCode, optional
documented referenced-IDV/modification filters, Award result type, limit <=10 and
offset 0. JSON numbers or documented decimal-digit string counters are accepted
without coercing native identifiers. Missing/invalid identity sections are retained
as unsupported or insufficient records. Known schema changes stop interpretation.
The specification calls offset a page index, while examples show offsets consistent
with row positions. Therefore this version does **not** implement continuation.
No response URL, export token, download endpoint, email option, alpha endpoint or
aggregation is followed. A later verified contract must resolve paging first.

Dates include signed, created, approved, modified and public-delta concepts;
they are not interchangeable. Dollars-obligated, totals and potential/current
contract values require separate semantics work. No SAM monetary field is mapped
into C5. Raw contractId JSON preserves missing/null/empty field distinctions.

The adapter reuses C3's bounded TLS/proxy-aware transport and C1 artifacts/record
references with a dedicated versioned capture validator. It does not masquerade
as an FPDS C3 journal or claim full legacy C2/C7 support. Source bytes are original
application response bytes, not wire captures; authentication material is explicitly
omitted from request provenance. Capture plans/reservations and commits are
append-only and bounded. Missing credentials fail before requests or directory
creation. Interrupted reservations are preserved and never automatically resumed.

No SAM credential was configured in this environment. Live SAM behavior is
**unverified**; mocked captures use an explicit synthetic profile. No key was
requested, generated, printed or obtained from files. The live adapter consumes
only the configured SAM_GOV_API_KEY environment binding; never put it in JSON,
CLI arguments, logs or reports. Client debug output is suppressed and wire-debug
mode is refused. Credential echoes, sensitive tokens, unsupported/error payloads
or credential-bearing headers are omitted/rejected with explicit metadata rather
than stored or relabeled as faithful raw evidence. This security policy can leave
an unusable observation without preserved body bytes; it never fabricates a body.

## Commands and integration

```sh
mkdir -p reports
python -m src.scope_evidence --demo --run-dir reports/NEW_scope_demo
python -m src.scope_evidence --root data/raw/ONE_C3_AWARD --request work/native-scope.json --run-dir reports/NEW_scope_analysis
# Only with credentials supplied through managed environment configuration:
python -m src.sam_contracts --live --request work/sam-native-scope.json --run-dir reports/NEW_sam_capture
python -m src.scope_evidence --sam-root reports/NEW_sam_capture --run-dir reports/NEW_sam_scope
```

An explicit request uses the normal schema-v1 envelope, for example:

```json
{"schema_type":"ScopeRequest","schema_version":1,"piid":"SYNTH-0001","agency":"0001","parent_piid":"SYNTH-PARENT","parent_agency":"0002","namespace":"usa-fpds-v1"}
```

For SAM use namespace samgov-v1 with researched source-native strings, not an
assumed agency crosswalk. Optional modification/transaction constrain action
scope; transaction is checked locally because this prototype does not assume a
documented transaction query parameter. Known C3 selected native identifiers must
agree with the requested context. Multi-award C3 roots require separate requests
and are refused by this first single-context adapter.

Reports contain every enumerated scope occurrence plus typed, eligible C4/C5
outputs. They also retain original field-presence context, per-source counts,
matrix/lineage limitations and baseline financial counts separately. Scope reports
are review evidence, not reusable trust anchors: adapters re-read the raw source.
No new HTML renderer or automatic C6/C7 integration is introduced. Existing C6
packets remain unchanged; passing a scoped report to an unscoped C5/C6 workflow
fails stale-report validation rather than bypassing scope.

Completed demonstrations/evaluations exit 1 because broad completeness is unknown;
invalid input/storage exits 2 and interruption 130. Every output directory must be
new with an existing parent. Outputs inside evidence roots, symlinks and oversized
inputs are refused. Capture recovery is intentionally not automatic: preserve
partial work and use a new run. Source evidence is never edited.

## New metric definitions

scope-metrics-v1 leaves Phase 4A/4B1 metrics untouched. Counts are enumerated record
occurrences, not unique contracts. The in-scope fraction uses those occurrences;
zero denominator gives null, not a percentage. Unparseable/unusable artifacts
are reported separately and make returned_occurrence_count_complete false; no
row total is invented for an unparseable body. Distinct source/content pairs and
documented retrieval observation IDs are separate counters.

Financial action contexts withheld counts distinct observed USA subject contents
that fail scope or lack a complete exact eligible FPDS action key. Its denominator
is distinct observed USA subject contents. This is a prerequisite gate, not a
but-for causal estimate: baseline C4/C5 may already have refused those claims.
Monetary date/currency incompatibility alone is not attributed to scope. Actual
financial claims and authorized numeric comparisons come from C5, never new
scope arithmetic. Unrequested ordinary modifications and deobligations are not
misconduct or financial anomalies.

## Bounded observations and reproducibility

On 2026-10-28, three previously studied native award contexts were selected from
the ignored Phase 4A bridge (rows 2, 4 and 7). The third request deliberately
retained unknown parent context. Seven real HTTP requests were made: two
USAspending and five FPDS, all HTTP 200. The third query used three bounded FPDS
pages with the existing strict continuation rules; the next page was not
requested. Neither accepted pagination nor HTTP success establishes identity or
complete history. No further requests were needed for the final read-only recheck.

| Query | Occurrences | In scope | Out of scope | Ambiguous | Numeric comparisons, baseline → scoped |
|---|---:|---:|---:|---:|---:|
| Known compatible parent | 8 | 8 | 0 | 0 | 4 → 4 |
| Conflicting returned parent context | 20 | 10 | 10 | 0 | 0 → 0 |
| Parent context unknown, FPDS only | 30 | 0 | 0 | 30 | 0 → 0 |

There were 58 distinct source/content pairs and seven retrieval observations;
insufficient-identity and unsupported-schema occurrence counts were both zero.
The observed in-scope fraction was 18/58 (31.03%). This convenience sample is not
a population precision estimate, a measure of query recall, or a source-wide
quality assessment. Ten observed USA action contexts lacked eligible FPDS action
evidence; baseline C5 already withheld their numeric comparisons. Explicit scope
exclusions therefore improve the audit trail without claiming an increase in
financial comparability. All history and freshness assessments remain unknown.
No SAM requests were attempted without credentials.

Local live responses and generated reports remain ignored and uncommitted.
Final saved-response analysis digest:
`d151a1a979d203a287a1eb2bae34220641a71ed146c83b30f854892d67ec9bd9`.
Source inventories were byte-identical before and after reanalysis. The eight-case
synthetic demonstration was run twice with equal substantive digest:
`a8570ca07990c84b753b6aa05ab5d00e5dd66fd1efc4fe8d4455b71bf96d9be1`.
Execution locations/times do not enter the deterministic substantive output.

## Unresolved boundaries and later research

Before broader work, validate SAM authentication and documented response fields
with an authorized account, clarify its offset semantics, and establish a
positive source-specific no-parent rule if one exists. These are future Phase
4B3 recommendations, not capabilities implemented here. Investigate the FPDS
query/returned-parent disagreement with maintained official documentation; do not
repair returned identities or broaden searches to force agreement. Query support,
recall, full modification histories, source refresh timing and cross-source agency
equivalence remain bounded or unknown. No automatic SAM financial mappings,
replacement collection, C6/C7 integration or independent-corroboration claim is
introduced. Scope disagreements concern narrow identity prerequisites only.
