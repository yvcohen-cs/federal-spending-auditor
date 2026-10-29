# Phase 4C1: parent identity and query-scope research

Phase 4C1 is a separate, opt-in, offline experiment. A source query returning a
record is not proof that the record belongs to the requested award. All claims
are about narrow source-record associations. No misconduct label, score,
identity inference from names/addresses/money/dates, or independent corroboration
claim is produced.

## Preregistration and lineage

PR #15 was merged at `aa8112abf78b472db04c6308ef1bd448b88cb479`.
Branch `phase4c1-parent-identity` starts from that latest main.
[Protocol v1](parent-identity-protocol-v1.json) was committed as `496db3b`
before experimental reclassification. Its canonical JSON SHA-256 is
`2aed20d36722a1bddf2b7000ebf8fae185f83298c79b8e7467fa9c5e70b5d723`.
The implementation pins this digest. Any future criterion change requires a new
protocol version. No minimum improvement target exists. Intermediate evaluations
are development observations, never replacements for the final replay.

The frozen readiness protocol `docs/readiness-protocol-v1.json` is unchanged.
Its original conclusions and counts remain historical results. The experimental
rule does not recalculate or upgrade readiness decisions.

Baseline implementation SHA-256 (research_models.implementation_digest):
`f4a9d3559731641dd2e0feb8415f471b72b439121373ee07700d00ebfdd3e527`.
Original pilot implementation, sample and plan hashes remain in the unchanged
4B4 protocol. The pilot's 24 generated IDs are retained in its sample; the
holdout's three generated IDs remain in its committed selection. Generated IDs
are cohort membership strings, never proof of parent absence or universal
real-world identity. No cohort rows, raw responses or generated reports are
committed here.

Required source inventories:

- Frozen 24-slot pilot:
  `02b45a4c059b48a798689b842bef949a44b48996cba20da9fd3a7ee047fd0a1f`.
- Three-slot holdout:
  `ff0f4393b07cd69f282e2ea14e4f2571a3a53760d25827e711d0ddeb6d7b34a8`.

Both include controls and failed attempts, not just usable source bodies.
Cohort evaluation refuses a different inventory, never substitutes a new cohort,
and retains unavailable slots explicitly. Missing evidence cannot become a
known zero count. Source roots are read only and inventories are checked again.

## Official semantics research

Reviewed October 28, 2026 (Pacific). Official documentation is distinguished
from authenticated API behavior and preserved-response observations.

| Official source | Established meaning | Boundary |
|---|---|---|
| [FPDS 1.4.4 dictionary](https://www.fpds.gov/downloads/Version_1.4.4_specs/FPDSNG_DataDictionary_V1.4.4.pdf), elements 1G/1H, 12B | Referenced PIID/agency identify the referenced IDV; award type A is BPA call, B purchase order, C delivery/task order, D definitive contract | Indexed official historical text; current document URL redirects to SAM. Not a live API contract |
| [FPDS 1.5 dictionary](https://www.fpds.gov/downloads/Version_1.5_specs/FPDS_DataDictionary_V1.5.pdf), 1G/1H | Parent applicability differs across awards, IDVs and modifications; orders and some BPAs reference IDVs | Do not generalize IDV, PO or other-transaction rules to every award |
| [FPDS definitive-contract form](https://www.fpds.gov/help/Create_a_Stand_Alone_Contract.htm) | Referenced IDV is not applicable specifically to a definitive contract | Positive native award type is required; blank fields alone are insufficient |
| [FPDS 1.4 changes](https://www.fpds.gov/downloads/FPDS-Specifications-Version14-Changes.pdf), [1.5 changes](https://www.fpds.gov/downloads/FPDS-Specifications-Version15-Changes.pdf), [Atom specification](https://www.fpds.gov/wiki/index.php/Atom_Feed_Specifications) | The award type field is `award/contractData/contractActionType`, with an optional description; primary identity is `award/awardID/awardContractID`, parent is `award/awardID/referencedIDVID` | Indexed official specification; current wiki redirects to SAM. `contractDetail` is not substituted for `contractData`; no local-name fallback |
| [FPDS glossary](https://www.fpds.gov/help/Glossary.htm), Referenced IDV Agency Identifier | Parent agency is the agency of the referenced IDV; historical instructions permit a blank where the IDV is otherwise unique | Blank is not an agency crosswalk or proof of absence; this rule still requires a native pair to verify a relationship |
| [SAM Contract Awards API v1](https://open.gsa.gov/api/contract-awards/) | `contractId.subtier.code`, `piid`, modification and transaction are distinct from contracting/funding agencies; `referencedIDVPiid`, `referencedIDVSubtier.code`, referenced modification and `oldContractId` are distinct | Authentication, roles, paging and source-correction semantics remain unvalidated here. No SAM mapping or network work added |
| [USAspending analyst guide](https://www.usaspending.gov/federal-spending-guide) | Summary award keys and parent award PIID linkage differ from transaction identities | Dynamic guide is poorly exposed to text retrieval; indexed official text is background, not an operational no-parent rule. Existing C4 CONT_TX parser remains pinned; sentinel values mean unavailable |
| [FAR 4.1603](https://www.acquisition.gov/far/4.1603), current FAC 2026-01 page | Procurement instrument and supplementary modification identifiers have separate roles; new PIID structure has instrument designations | No position-based classification, historical-ID repair, punctuation removal or zero-padding is implemented |

No general source-native null/empty/sentinel rule was established that proves
no parent for USAspending transactions or SAM contractId-only captures. A
USAspending generated ID with `-NONE-` cannot independently establish absence.
Parent links and old identifiers may change through corrections; their presence
does not establish a common revision across sources. IDV types reuse letter
codes in a different context (for example D can mean BOA for an IDV), so an IDV
container is never interpreted as an award of type D.

## Schemas and inference rules

`src/parent_identity.py` defines strict schema-v1 `NativeParentField` and
`ParentAssessment` dataclasses and the five `ParentStatus` values:

- `verified_parent_relationship`: supported native parent PIID **and** parent
  agency assert this record's relationship. This is not verification of the
  parent's existence, the request's unknown parent, or independent corroboration.
- `verified_no_parent`: only FPDS award schema 1.4/1.5, positive native type D,
  known qualified field paths, no conflicting version, and no substantive,
  malformed, null, placeholder or partial referenced-IDV context. The dictionary
  plus definitive-form rule supports this narrow applicability assertion.
- `parent_relationship_conflict`: known requested parent conflict, definitive
  type conflicting with a native parent, or independently anchored contradictory
  native versions. This does not prove an erroneous source or misconduct.
- `parent_relationship_unknown`: missing pair or unvalidated applicability.
- `unsupported_parent_semantics`: unvalidated schema, namespaces, repeated or
  compound fields, or unsupported source structure.

Fields retain native text exactly, qualified paths, source schema version,
instrument type, presence state, original raw JSON value, rule/rationale and a
full existing C6 `EvidenceCitation`. Omitted, empty, explicit XML nil, malformed
and embedded-component unavailable states remain distinct. Derived entry XML
is labeled derived and bound to C4's structural record fingerprint; it is not
relabeled as byte-exact HTTP evidence. Original application-response byte hashes,
URLs, request parameters, locators and retrieval times remain in C6 citations.
Hashes establish reproducibility/integrity, not source authenticity.

The experimental `parent-scope-v1` recomputes from preserved C3 evidence through
existing C2/4B2 validators. It preserves known native conflicts and unsupported
baseline observations. Requested PIID/identity agency and any requested
modification/transaction must agree exactly. Known compatible native parent
pairs can retain existing scope verification. A returned pair cannot fill an
unknown **requested** parent. A positive documented no-parent rule can resolve
previous parent ambiguity only when all other requested components are exact.
A requested known parent conflicts with a positively established no-parent
record. Unsupported or contradictory parent semantics cannot create a positive
scope assertion. Unknown applicability remains withheld.

Version conflicts require the same source-native `id`/`atom_id` or a complete
native parent-bound action key with different contents. Child PIID/agency/action
alone cannot identify one award across different parents. Content hashes group
retrieval content; they never infer a real-world identity. Duplicate occurrences
remain separate; two conflicting source versions are not silently collapsed.
Cross-root conflicts are recomputed from the complete bounded input set.

`ParentScopeRun` retains input inventories, artifact issues, actual submitted
requests and typed assessments. Output reads recompute classifications, query
explanations, transitions and metrics; edited statuses or omitted conflicts fail
validation. A serialized report is not an identity trust anchor: future analyses
must revalidate the primary evidence.

## Query-scope findings

The legacy collector submits `PIID:"..." AND CONTRACTING_AGENCY_ID:"..."`.
[Historical official feed documentation](https://www.fpds.gov/wiki/index.php/Atom_Feed_Usage)
lists these and separate referenced-IDV filters. It does not establish exact
native award/parent enforcement. The source identifies the agency filter as
contracting agency; this experiment does not equate that namespace with
`awardContractID/agencyID`. No collector query is changed in Phase 4C1.

Each occurrence explanation contains requested native context, actual submitted
parameters bound by response body hash/time and metadata path, returned native
components, parent evidence, local inclusion decision, duplicates, known component
conflicts, citations and manual next step. Parent/modification/transaction
constraints are checked locally but are not submitted by the legacy FPDS query.
This is a concrete limit of the current query, separate from server behavior.
Known differing parents can be other parent-bound awards sharing an order PIID.
A record with conflicting native components is excluded, not silently repaired.
An IDV container, an unsupported schema, duplicate retrievals and an unrelated
award are different observations. Query precision explanations preserve all of
them; they do not claim the server is defective.

Current official wiki/spec URLs may redirect to SAM. Historical UI wildcard
help does not establish Atom tokenization or exact-match guarantees. The saved
responses establish returned-record observations only. Tokenization, query
recall, partial matching, field enforcement and the cause of individual historic
mismatches remain unverified. An empty feed is inconclusive. No new award-data
requests were made: repeating a current query cannot determine a historic server
cause, and authenticated SAM behavior cannot be tested without authorized access.
No live switch or wider collection permission was added.

## Downstream boundaries and compatibility

C4 action matching, C5 financial comparisons, C6 packets/review events, C7,
4B3 revision/history and 4B4 readiness **do not consume** this experimental rule.
Their existing modules, flags, checkpoints and output definitions are unchanged.
The report enumerates complete action keys only as an experimental prerequisite
metric. No null-parent sentinel is inserted into C4 action keys. Resolving parent
scope alone does not provide revision alignment, counterpart evidence, compatible
monetary semantics, history completeness, freshness or numeric authorization.
Newly eligible financial comparisons are zero **by design**, not a causal estimate
of what a future integration might authorize. Legacy 4B3 partitions are replayed
and reported independently, not recomputed with experimental eligibility.

Review citations and recommended next actions reuse C6; no new review-event
system exists. Reports include unknowns and excluded records, immutable source
references, exact transition rules and a manual verification step.

## Reproduce without network

```sh
# Each target must be new with an existing parent.
python -m src.parent_evidence --demo --run-dir reports/NEW_parent_demo
python -m src.parent_evidence --root reports/p4a-live-24 \
  --holdout-root reports/b4-live-holdout --run-dir reports/NEW_parent_reanalysis
python -m pytest -q tests/test_parent_identity.py
python -m pytest -q
python -m pytest -q -p no:cacheprovider \
  tests/test_federal_spending_auditor.py::test_pipeline_writes_cleaned_flagged_and_summary_outputs
```

A demo creates explicitly synthetic journals in a separate sibling directory.
The frozen command requires exact cohort inventories and revalidates 4B4 holdout
selection/budgets without collection. No missing-evidence fallback exists.
`parent-identity.json`, Markdown, escaped static HTML and a hash commit are
written append-only through the existing secure output primitives. Output roots
inside evidence, symlinks, path traversal, overlapping journals and oversized
inputs/outputs are refused. Completed experiments exit 1 (limitations remain),
invalid evidence exits 2, and interruption exits 130. There is no automatic resume,
network or financial integration. No execution timestamp enters substantive
output; primary retrieval timestamps remain provenance.

Metrics distinguish enumerated verification occurrences, distinct source/content
pairs, affected selected slots, and complete native action keys within each slot.
Discovery/frame rows are not verification occurrences. Each cohort and status
partition has its own denominator. Unavailable slots remain in the selected-slot
denominator and make occurrence-count completeness false. Neither an observed
in-scope fraction nor its change estimates population precision, recall or
screening effectiveness.

## Validation and self-review

The untouched main worktree passed 1,101 offline tests and the explicit smoke.
An initial test run overlapped source editing and correctly detected implementation
fingerprint changes; it was discarded and rerun in the isolated baseline worktree.
The new synthetic cases cover every requested adversarial category, including
unsupported positive rules, spoofed namespaces/type paths, different parents with
a reused child action, contradictory native IDs, source mutation, unsafe storage,
report tampering, stable replay and unchanged legacy financial behavior.
Final evaluation/test/CI results are recorded below after validation.

## Unresolved questions and Phase 4C2

1. Obtain an authorized, bounded SAM validation of native identity/agency,
   instrument applicability, corrections and paging. Documentation examples are
   not an authenticated behavioral test. Preserve the existing first-page-only
   adapter until its continuation contract is verified.
2. Establish authoritative parent evidence for USA transactions and unsupported
   historical FPDS schemas. Never propagate an FPDS absence assertion into USA
   solely because PIID/agency happen to agree. Investigate prior identifiers and
   parent corrections without joining by a partial child identity.
3. Research exact source search field semantics, contracting versus identity
   agency and referenced-IDV filtering through a separately preregistered probe.
   A small bounded probe may characterize current behavior, not historic causes
   or population precision. Keep mismatches preserved and locally excluded.
4. Define source-native revision/correction/deletion lineage and counterpart
   requirements before any integration with financial comparison. Parent
   resolution is only one prerequisite. Establish history/freshness separately.
5. Human-review the new evidence explanations and develop acceptance criteria
   before changing packets, pipeline defaults or readiness thresholds. Larger
   screening remains unauthorized by this experiment.

## Final saved-evidence observations

All 27 selected slots were inspected, without network collection or unavailable
substitutions. There are 381 verification occurrences and 361 distinct source /
content pairs across the combined cohort; a repeated content in another slot
is not a new globally unique award. Original counts are reproduced exactly.

| Cohort | Occurrences | Previous in / out / ambiguous | Experimental in / out / ambiguous |
|---|---:|---:|---:|
| Frozen pilot, 24 slots | 349 | 111 / 88 / 150 | 150 / 88 / 111 |
| Holdout, 3 slots | 32 | 0 / 0 / 32 | 4 / 0 / 28 |
| Combined, 27 slots | 381 | 111 / 88 / 182 | 154 / 88 / 139 |

Insufficient-identity and unsupported-baseline-schema occurrence counts are zero
in both scope partitions. **Parent**-semantics unsupported is a separate dimension:
63 occurrences. Parent classifications over the 381-occurrence denominator are
109 verified native parent assertions, 45 verified no-parent, 44 parent conflicts,
120 unknown and 63 unsupported. A parent conflict does not replace a known
PIID/agency/parent mismatch's out-of-scope result with a positive assertion.

| Previous → experimental scope | Occurrences | Distinct source contents | Affected slots |
|---|---:|---:|---:|
| Ambiguous → in scope | 45 | 45 | 10 (7 original + 3 holdout) |
| Ambiguous → ambiguous | 137 | 137 | 15 |
| In scope → ambiguous | 2 | 2 | 1 |
| In scope → in scope | 109 | 109 | 12 |
| Out of scope → out of scope | 88 | 68 | 9 |

Every promoted occurrence has FPDS schema 1.4/1.5, primary native type D and the
specific dictionary/form no-parent rule; JSON reports retain exact fields,
citations and authorization identifiers. Of the 182 originally ambiguous
occurrences, 137 remain ambiguous. The 47 changed occurrences affect 11 selected
slots; these are selected-award slots, not inferred global real-world awards.

The two demotions are in original slot 022: the BPA-call type A includes a
`part8OrPart13="PART8"` attribute outside the validated attribute subset.
The current official indexed specifications did not establish that attribute's
contract during this research. `malformed_or_repeated_parent_or_instrument_field`
is the adapter's unsupported-subset reason; it does **not** establish malformed
source records. These observations remain preserved and reviewable. No rule was
broadened solely to improve the metrics.

Complete native parent-bound action-key count remains **93**, summed distinctly
within slots. No null-parent action key is invented for the 45 promotions.
Financial integration remains disabled, so **zero** newly eligible financial
comparisons are exported. The independently replayed legacy 4B3 results remain
363 combined result units: 270 scope-uncertain (238 original + 32 holdout),
75 insufficient counterpart/history, and 18 revision-unknown, with zero authorized
numeric comparisons. These are result units, not 363 verified same-action pairs.
No revision alignment, complete history, freshness, or screening-readiness gain
is inferred from parent resolution.

Two combined frozen-evidence replays produced the same substantive report SHA:
`083803501caac7622c316c2cd250e1c8c2828bdbe1fb6ba3572fcfaa0ac2c598`.
Reports were saved locally under ignored `reports/c1-final-combined-a` and `-b`;
the output reader revalidated the first report's typed projections and hash commit.
Both synthetic demonstrations produced SHA:
`cf64984047e4f1e1505b4dbcb5447ec8a6844dd42df825c1a6877b89489f61a8`.
Both original evidence inventories stayed exactly as preregistered. Zero award
API requests were made. Official documentation lookups are documentation research,
not authenticated API validation.

Final local validation: **1,170 tests passed**, including **69 new parent-identity
cases**, plus a separately run offline smoke test. The source implementation
fingerprint is `d444cc1da3c8729d1f8713e77413424de8bc8744a58ce1bbc860d5f3af02ed23`.
The existing GitHub Actions matrix is retained for Python 3.11 and 3.12; exact
run/check results are recorded in the pull request before merge consideration.
Final self-review checked source-native identity boundaries, immutable protocol
and evidence inventories, no collection/financial integration, native-string
preservation, schema/path spoofing, untrusted report reads, output escaping and
source/output path protection. Source data, credentials and generated reports
remain excluded from git.
