# Phase 3C4: conservative offline identity matching

Workstream C of [Issue #1](https://github.com/yvcohen-cs/federal-spending-auditor/issues/1).
This separate, opt-in subsystem associates observed USAspending transaction
records with FPDS awards and actions. Identity association is **not financial
verification**. Disagreement, missing records and ambiguous identifiers are not
allegations of fraud or misconduct. No C5 financial calculations, C6 evidence
packets, contractor graphs, name/address matching, scores or network collection
are added. Legacy reconciliation, collection defaults, reports and checkpoints
are unchanged.

## Source research: verified relationships and limits

The following official documents/source code were inspected. Source-code
semantics are pinned, not a guarantee that every historical or future API
deployment uses the same rules.

| Primary source | What it supports |
|---|---|
| [USAspending transactions contract](https://github.com/fedspendingtransparency/usaspending-api/blob/0a6d86a1e7e4105f349ec5db193ed4c7fca00466/usaspending_api/api_contracts/contracts/v2/transactions.md), blob `246a2639368fd8908be232a25bbe25fb3e1c9720` | Award-query context, internal string transaction ID, modification and action fields. Transaction results do not promise separate PIID, agency, parent or transaction-number columns. |
| [Official transaction view](https://github.com/fedspendingtransparency/usaspending-api/blob/0a6d86a1e7e4105f349ec5db193ed4c7fca00466/usaspending_api/awards/v2/views/transactions.py), blob `05a86cd083eab1a0e473d291cb61069ce058e917` | `id` is the transaction unique ID with a `CONT_TX_` prefix for FPDS contracts; query results are filtered by the requested award. |
| [Official loader field mappings](https://github.com/fedspendingtransparency/usaspending-api/blob/0a6d86a1e7e4105f349ec5db193ed4c7fca00466/usaspending_api/etl/transaction_loaders/field_mappings_fpds.py), blob `6a343bae6e959e88b253a8d3b32d9e29f4defb08` | Broker native transaction key feeds `transaction_unique_id`; Broker modification feeds `modification_number`. Agency ID is distinct from awarding top-tier/sub-tier fields. |
| [Treasury Broker FPDS ingestion](https://github.com/fedspendingtransparency/data-act-broker-backend/blob/bed939e6e51e5b31cac4ece7e3389a7464e6e78a/dataactcore/scripts/pipeline/pull_fpds_data.py), `calculate_remaining_fields`, and [derivations](https://github.com/fedspendingtransparency/data-act-broker-backend/blob/bed939e6e51e5b31cac4ece7e3389a7464e6e78a/doc/fpds_derivations.md) | Award-action key components, in order: agency ID, referenced-IDV agency, PIID, modification, parent PIID, transaction number. Empty values are encoded with a sentinel. Parent modification is excluded. IDV ingestion has different omissions; this matcher does not claim IDV-action support. |
| [FPDS Atom specification](https://www.fpds.gov/wiki/index.php/Atom_Feed_Specifications) and [official v1.4 XML comparison](https://www.fpds.gov/downloads/FPDS-Specifications-Version14-Changes.pdf) | Distinct awardContractID and referencedIDVID containers and their named string fields. Historical namespaces differ; C4 accepts only C3's already supported namespaces. |
| [Official FPDS dictionary](https://beta.fpds.gov/downloads/Version_1.5_specs/FPDS_DataDictionary_V1.5.pdf) and [DoD reporting instructions](https://www.acquisition.gov/dfarspgi/pgi-204.606-reporting-data.) | Four-character agency identifier, referenced IDV/modification context, and transaction numbers for separately reported actions. A modification label by itself is not an action identity. |

The saved C3 USAspending representation was inspected: its row has `id`,
`modification_number`, action/date/type and obligation fields, without explicit
PIID/agency/parent columns. Saved FPDS review bodies contain direct award/parent
identifiers, modification and transaction strings. Observed parent modification
values vary across actions without changing parent PIID/agency. No new government
API requests were made for C4. These observations validate the inspected shapes
only. Research probe bodies are not silently admitted as C3 matching inputs.

Official [SAM transition information](https://sam.gov/fpds) describes migration of
public FPDS functionality. Historical FPDS documents and locally saved successful
responses do not establish present endpoint availability, universal query scope,
refresh times or historical completeness. C4 never calls an endpoint or follows
a saved URL. C3 empty feeds remain inconclusive.

### Supported ID interpretation

Rule `identity-v1` decodes only `CONT_TX_` IDs with exactly six non-escaped,
underscore-delimited components. The full native ID remains intact. Components
are labeled `usa_cont_tx_v1`, distinct from direct `source_field` observations.
Extra separators are ambiguous/unsupported: the matcher does not guess where an
underscore belonged. Unknown prefixes, assistance IDs, changed formats and
missing/malformed fields cannot establish identity.

Sentinels `-NONE-` and `-none-` indicate unavailable components; they never
establish real-world absence of a parent. Supporting these two observed/source
spellings is an explicit v1 compatibility rule. Neither becomes a parent key.
The generated award ID in the **request** and the user-supplied selection mapping
are not decoded into evidence of identity. Native transaction components must
substantiate the association. This deliberately leaves many standalone awards
and IDV actions unresolved until a separately researched parent-absence/category
rule or additional supported source evidence is available.

No trimming, padding, numeric coercion, case folding or punctuation removal is
applied to comparison keys. Four-character ASCII alphanumeric agency codes are
supported; other code shapes are malformed/unsupported, not repaired or mapped
to a top-tier/sub-tier agency. Source documents describe field widths, but this
ASCII/alphanumeric acceptance subset is a conservative adapter policy, not a
claim about all historical codes. PIID, modification and transaction values keep
zeros, punctuation, case and surrounding spaces. Controls, oversized values,
whitespace-only values and non-string identifiers cannot supply keys. Blank or
unknown parent fields never act as equality wildcards.

## Models, serialization and evidence

The new models use the C1 `Schema` serializer, dataclasses, enums,
`SourceIdentifier`, `EvidenceArtifact`, `EvidenceRecordRef`, `Completeness` and
`ComparisonStatus`. They are companion **schema version 1** contracts; C1/C2/C3
schemas and golden fixtures are unchanged. Unsupported versions fail without
migration. No third-party dependency is added.

| Model | Contents and invariants |
|---|---|
| `IdentityComponent` | Canonical original JSON, exact comparison value only when valid, basis and explicit valid/absent/malformed/unsupported/conflicting state. |
| `SourceRecordIdentity` | Source, retrieval-content SHA-256, untouched native identifiers, native-ID state, six typed identity components, raw action/date context, issues, and every supporting evidence reference. |
| `AwardIdentityCandidate` | Complete or individually incomplete candidate group, all constituent record IDs/evidence, exact/possible/conflict relation and field-specific reasons. |
| `ActionIdentityCandidate` | Same evidence contract, separately scoped to an action within its award. No amounts or dates in keys. |
| `MatchEvidenceReference` | C1 record locator, full C1 artifact/provenance/representation, recomputed C2 observation ID and validated metadata paths. No invented timestamps or URLs. |
| `MatchDecision` | Subject retrieval record, award-association or action-equivalence claim, C1 status, rule version, candidate sets and supporting/countervailing evidence. |
| `MatchCoverage` | Source artifact/observation and observed next-page flag; pagination, history, query scope, freshness and source-wide dimensions remain separate. |
| `MatchRunSummary` | Sorted unique records/decisions/coverage/exclusions, validated input-manifest digest, configured limits, bounded work count, rule version and optional execution time. It checks references and recomputes rule outcomes on deserialization. |

Constructed `record:v1:` IDs identify source plus parsed retrieval content;
they are **not source-native award/action IDs**. Content equality consolidates
identical retrieval rows only and retains all locators and observations. It
never infers a contractor identity, payment or financial event. Hashes detect
accidental changes; they do not authenticate a public source or protect against
coordinated editing of evidence and its declarations.

FPDS retrieval fingerprints use expanded XML names, attributes, exact text/tails
and ordered children rather than ElementTree's globally registered output
prefixes. USAspending fingerprints use canonical complete parsed rows. Every
source field remains preserved in its artifact; fingerprint normalization never
changes an identifier comparison value or evidence representation.

`identity-claim:v1:` hashes the subject retrieval record ID, narrow claim and
rule version; it excludes outcome, execution time, candidates and evidence order.
Different observed record contents have different snapshot claims, including
revisions. This does not imply a new real-world action. Canonical serialized
ordering does not imply action chronology. Modification strings are not sorted
numerically or used to infer sequence, supersession or revision precedence.

All lists with set semantics serialize in canonical order. An optional run
execution timestamp is excluded from `substantive_sha256`. Actual retrieval
timestamps remain substantive provenance; changing the observed evidence should
change the report digest. Native IDs, evidence locators, URLs, processing labels
and source times remain separate from constructed IDs. Application-body bytes
retain C3's `application_body_bytes_not_wire_capture` limitation.

## Deterministic rules and claim-specific outcomes

For every observed USAspending retrieval record:

1. Consider FPDS records with the same PIID or unresolved PIID. Known different
   PIIDs are outside this subject's candidate scope but stay in the report inventory.
2. Group FPDS award candidates by the complete exact tuple `(PIID, agency,
   parent PIID, parent agency)`. Missing components never group unrelated records
   under a partial key. Different modifications under one full award key support
   one award association, without collapsing their action records.
3. A unique complete equal award tuple establishes an observed award association
   only if unresolved plausible alternatives or internal contradictions do not
   block it. Known unequal agency/parent context is a rejected candidate with
   an explicit conflict rationale. PIID equality alone is never sufficient.
4. Evaluate specific actions separately using the award tuple plus exact
   modification and transaction number. A USA native ID that disagrees with its
   modification field is contradictory. A different known modification denotes
   another candidate action; it is not evidence that an action is missing globally.
5. Conflicting contents for a source-native action key, or reused native IDs with
   conflicting award contexts, block an exact action/award assertion as applicable.
   Every relevant observed version is cited; no latest-wins rule is assumed.

| Status | Narrow meaning |
|---|---|
| `verified_match` | One exact complete identity group within observed evidence and supported rules; no unresolved plausible alternative. No assertion of global uniqueness, financial agreement or complete history. |
| `ambiguous_match` | Multiple plausible candidate identity groups; none is chosen. |
| `insufficient_evidence` | Missing/unsupported components, one incomplete candidate, no observed counterpart, or award identity unavailable for action comparison. Missingness is not a contradiction. |
| `unresolved_discrepancy` | Known candidate identifier differences or internally contradictory native fields/observed versions. It does not allege the records should have matched or that either source is wrong. |
| `explainable_difference` | Recognized C1 status, intentionally never emitted in v1: no researched identity-equivalence exception rule justifies it. |

Original-action, amendment, correction and deobligation labels are not inferred
from dates, numbers, signs of obligations or modification-label appearance.
Existing USAspending action-type/code/description fields are preserved as raw
context; null stays null. Conflicting observed versions may represent benign
corrections, but v1 has no supported precedence rule to explain them away.
FPDS dates are context only. Negative and zero-dollar records are retained with
the same identity rules; there are no financial comparisons.

## Offline workflow and bounds

The input is **one flat C3 collection directory**, collector semantics 1 or 2.
The reader reruns C2 validation, verifies C3 journals/request context/hashes,
checks evidence locators against parsed records, then rereads the bytes it uses
and compares the inventory and all files again before returning. Old C3 evidence
is readable; nothing is resumed or migrated. Pending/interrupted journals,
tampering, unsupported files, absent required controls and linked inputs fail
closed. Compound FPDS identity containers/duplicate Atom IDs fail explicitly
rather than selecting the first usable identity. Multiple parent references are
retained as contradictory context. Source artifacts are never modified.

Only C2 `verified` C3 response bodies supply matching records. Failed/partial
responses, metadata-only failures and inconclusive empty feeds are explicitly
excluded from matching while their coverage/provenance stays visible. A valid
partial collection may still establish identity between particular observed
records. It cannot establish absence of unobserved records.

Coverage is deliberately conservative: a saved response with a next page marks
pagination partial; a terminal page alone leaves traversal completeness unknown.
C4 does not independently certify the full C3 traversal chain or trust summary
completeness claims. History, source-wide completeness, query scope and freshness
remain unknown. Source-read errors and input limits are never reclassified as
source absence.

Defaults: 1,000 retrieval rows before deduplication, 100 candidate groups per
claim, 10,000 charged comparison slots. Hard maxima are 10,000 / 1,000 / 100,000.
The IO boundary also retains C2 defaults: 8 MiB per artifact, 64 MiB total and
4,096 discovered entries. Limits fail the entire matching run with a fixed error
code; no truncated candidate set is presented as a result. Comparison slots
conservatively charge eight times the USA/FPDS pair product, including both
evaluation and schema revalidation; conflicting-native-ID expansion additionally
charges `16 * max(1, USA records) * sum(conflicting group size squared)` before
expansion. This count is a resource bound, not a statistical confidence score.

Authored synthetic example, with no internet access:

```sh
mkdir -p data/raw/c3
.venv/bin/python -m src.collect_evidence --selection tests/fixtures/c4_selection.json --fixture tests/fixtures/c4_scenario.json --run-dir data/raw/c3/NEW_C4_SYNTHETIC --retries 0
# Collector exits 1 because FPDS query scope remains unknown; its evidence is usable.
.venv/bin/python -m src.match_evidence --root data/raw/c3/NEW_C4_SYNTHETIC
.venv/bin/python -m src.match_evidence --root data/raw/c3/NEW_C4_SYNTHETIC --output reports/NEW_identity_matching.json
```

JSON goes to stdout or an exclusively created file outside evidence. A concise
body-free human summary goes to stderr. Output parents must exist; overwrites,
symlinks and paths inside evidence are refused. Reports and collected data must
not be committed. `--execution-time` adds the actual run time only. `--max-records`,
`--max-candidates` and `--max-comparisons` configure the supported bounds.

Exit 0: nonempty decisions are all exact identity matches and no artifact was
excluded; this is **not complete source coverage or financial assurance**.
Exit 1: unresolved/ambiguous claims, exclusions, no source counterpart or no
decisions. Exit 2: invalid evidence, limits, arguments or output. Exit 130:
interrupted, no trusted partial report. All FPDS records remain in the inventory,
including those outside every USA subject's candidate scope. Reports are
USAspending-subject comparisons, not a symmetric census of absent actions.

Linux/POSIX and WSL are supported by the secure C2/C3 filesystem boundary. Native
Windows use of this command is unsupported; no insecure path fallback is added.
Pure matching models/rules use the standard library. Advisory checks detect
ordinary concurrent changes but do not supply an atomic filesystem or upstream
snapshot. Legacy portability is unaffected.

## Tests and open methodological questions

Synthetic tests cover complete tuples, agency/parent conflicts, missing/malformed
and unsupported identifiers, ambiguity, duplicate retrievals, repeated observations,
multiple modifications, native-ID conflicts, corrections, dates, negative/zero
amount independence, missing/contradictory provenance, partial pagination, unknown
coverage, byte mutations, bounds, serialization, version rejection and old C3
readability. The existing full suite and explicit legacy offline smoke remain
required; Python 3.11/3.12 CI runs both without live-network dependence.

Unresolved: current and historical upstream key-generation/deployment equivalence;
an authoritative parent-absence rule for standalone contracts/IDVs; underscore
escaping and ambiguous historical key collisions; broader agency-code shapes and
crosswalks; historical namespace support beyond C3; corrections/revision/deletion
precedence; multiple reports for one action; globally complete candidate coverage;
source refresh guarantees. V1 preserves uncertainty instead of using names,
amounts, dates or user mappings to fill those gaps. No financial or misconduct
conclusion follows from an identity status.
