# Phase 3C1: evidence schema contract v1

Workstream C of [Issue #1](https://github.com/yvcohen-cs/federal-spending-auditor/issues/1).
These contracts are opt-in Python data structures in `src/evidence.py`. They do
not collect data, match records, compare money, generate packets, or integrate
with the pipeline. Existing CLI, CSVs, reports, checkpoints, and reconciliation
statuses remain unchanged. No runtime dependencies were added.

An outcome applies only to a narrowly defined claim. A cross-source disagreement
is not an allegation of fraud or misconduct. Source agreement is not assurance
about procurement propriety, nor proof that reporting systems are independent.

## Wire format and versioning

All nine public contracts and the supporting `SourceIdentifier` use frozen,
keyword-only standard-library dataclasses. Constructors require their declared
Python types (enums and tuples included). `from_dict` and `from_json` accept JSON
wire types, recursively validate them, and convert arrays to immutable tuples.
Identifiers, decimals, and timestamps are never numerically coerced.

Every nested object carries `schema_type` and integer `schema_version: 1`.
Readers reject unknown fields, missing/wrong type discriminators, absent versions,
future versions, duplicate JSON keys, and invalid nested values. Constructors
also reject unsupported versions. There is no automatic migration. Previously
saved collector responses are not v1 schema documents; future adapters may read
them without altering them. Omitting optional metadata preserves its explicit
null/unknown default, never supplies the current time or an inferred value.

`to_dict()` produces JSON-compatible objects. `to_json()` uses sorted object keys,
compact separators, ASCII escaping, and rejects nonfinite numbers. Arrays retain
their declared order: evidence manifests, result order, identifiers, and rationale
lists are substantive ordered inputs. Permuting arrays is not promised to yield
the same serialized document. No mutable arbitrary dictionaries are retained.
`request_json` and `original_json` hold canonical JSON strings so original value
types and immutable nested content can be preserved without coercion. They must
use the same canonical JSON settings. This preserves parsed values, not original
HTTP formatting or numeric token spelling; the artifact remains authoritative.

## Contract fields

| Contract | Required fields | Optional/default fields and constraints |
|---|---|---|
| `EvidenceArtifact` | source, relative_path, sha256, representation, hash_basis | endpoint, method, canonical request_json, retrieval/source-update UTC times, HTTP status, limitations; unknown collection metadata requires an explicit limitation |
| `EvidenceRecordRef` | constructed artifact_id, record locator, source | native_id, record URL, query URL, constructed-record-URL marker; native ID source must agree |
| `AwardIdentity` | nonempty native identifiers and source evidence | parent identifiers, award category; no duplicate/conflicting primary source namespaces |
| `ActionIdentity` | award identity, nonempty native action identifiers and evidence | separately namespaced modification, transaction, revision identifiers; no duplicate primary namespaces |
| `TypedValue` | evidence reference, field path, definition, kind, parse status, canonical original_json | parsed string, currency, date basis, period; missing/invalid values have no parsed value |
| `CoverageAssessment` | explicit scope | pagination, transaction_history, source_wide each default unknown; evidence, rationale, limit/failure markers |
| `ComparisonResult` | claim type, native subject, scope, dimension, status, evidence, rationale, coverage | candidate refs; identity/comparability/sufficiency support, each unknown by default; explanation refs; complete-history requirement; limitations |
| `ReviewEvent` | claim_id, review state, reviewer, rationale, UTC review time | evidence refs and superseded event ID; completed review requires citations |
| `VerificationRun` | code/rule/parser versions, configuration SHA-256, ordered artifacts and results | nullable execution UTC time; validates referenced artifact membership/source and rejects duplicate artifacts/claims |

Strings that represent identifiers preserve leading zeros, punctuation, case,
and even original surrounding spaces. Empty/whitespace-only identifiers,
control characters, numeric IDs, and booleans are rejected. No trimming, case
folding, parsing of generated IDs, or identity inference occurs. Source and
namespace are required. `parent_identifiers` represent an explicit parent key,
not an inferred relationship. Names and addresses are not identity inputs.
The application cannot establish that a caller's namespace/value is authoritative;
future evidence adapters must substantiate that assertion.

Artifact IDs are constructed `artifact:sha256:<digest>` references to preserved
content, not native identifiers or evidence of real-world identity. Locators
identify records within an artifact (for example a JSON pointer or XML locator).
The manifest accepts one artifact per digest; repeated observations of identical
content with different collection metadata can be retained in separate runs.
Later collection design may introduce a separate observation ID without changing
the native source identifiers.

All URLs must be HTTPS and cannot contain credentials or whitespace. A schema
validation does not fetch a URL, validate its current availability, or authorize
access. Query URLs and record URLs are separate. Constructed record URLs are
explicitly marked and remain unvalidated. Relative artifact paths cannot escape
the evidence root; no filesystem IO or artifact hash verification occurs here.

## Representation and provenance

| Representation | Hash basis | Meaning |
|---|---|---|
| `parsed_json` | `canonical_json` | Preserved parsed JSON, canonically encoded for hashing |
| `decoded_xml` | `utf8_text` | Preserved decoded XML text encoded as UTF-8 for hashing |
| `response_bytes` | `original_bytes` | Original response-body bytes; does not assert capture of headers or HTTP framing |
| `document_bytes` | `original_bytes` | Original document bytes |

Contradictory representation/hash-basis pairs are rejected. Historical parsed
JSON and decoded XML must retain those labels. Schemas cannot inspect bytes to
prove a caller's representation assertion; future loaders must enforce it.
UTC timestamps require an explicit zero offset. Unknown retrieval/source update
times stay null. A source record update timestamp is not source-wide freshness.
Hashes detect content changes, not authenticity or government endorsement.
Metadata must exclude secrets; this contract is not a credential detector.

## Independent completeness and outcome dimensions

Pagination, transaction history, and source-wide completeness are three separate
`Completeness` fields: `unknown`, `partial`, `complete`, or `not_applicable`.
An exhausted query does not set either of the other fields. Assertions other than
unknown require evidence and rationale. A limited or failed retrieval cannot
declare complete pagination. An asserted complete history requires its own
justification, even if pagination is complete. Different evidence may support
history completeness despite a limited query; no automatic propagation occurs.

Each `ComparisonResult` covers exactly one of `identity`, `amount`, `date`,
`coverage`, or `freshness`. Separate results are required for separate dimensions.
The schema records assertions and prerequisites; it does not decide which source
fields or date/money definitions establish them.

| Status | Validation contract |
|---|---|
| `verified_match` | Explicitly supported identity, comparability, and evidence sufficiency; citations from at least two sources; no unresolved multiple candidates |
| `explainable_difference` | Same prerequisites, plus cited explanation evidence included in the result's evidence |
| `unresolved_discrepancy` | Same prerequisites; rationale describes the unresolved difference without alleging misconduct |
| `ambiguous_match` | At least two distinct candidate references, included in evidence; identity cannot be asserted supported |
| `insufficient_evidence` | At least one prerequisite is unknown or unsupported; it cannot contradict three supported prerequisites |

Any decisive result with `requires_complete_history=True` also requires explicitly
complete transaction history. Callers must declare that requirement when their
claim needs it. A free-text scope is not parsed to infer requirements. Source-wide
or freshness claims need their own evidence; two source labels alone do not
establish independence, completeness, or synchronized refreshes.

No ordinal confidence or probability is defined. Limitations and explicit
unknown/unsupported prerequisites describe confidence boundaries. Review states
(`not_reviewed`, `in_review`, `awaiting_evidence`, `review_complete`) are independent
of comparison statuses. Completed review need not resolve a discrepancy. Events
are immutable values; persistence, append-only enforcement, event ID assignment,
and transition validation belong to later work.

## Deterministic identifiers and execution metadata

`ComparisonResult.claim_id` is computed as `claim:v1:` plus SHA-256 of canonical
JSON containing schema version, claim type, namespaced native subject, exact
scope, dimension, and the complete-history requirement. It excludes evidence,
candidate lists, outcome, rationale, and execution time. The same question keeps
its ID when new evidence changes its outcome. Scope must identify its period,
as-of basis, and definition sufficiently to avoid conflating questions. Changing
any of those semantics requires changing scope/type. Structured scope vocabularies
remain a later design decision. The computed ID is accessed as a property and is
recomputed after deserialization, rather than accepting caller-supplied IDs.

`VerificationRun.to_json(substantive=True)` excludes only `executed_at_utc`.
`substantive_sha256` hashes that serialization. Retrieval/source-update timestamps
remain substantive provenance. Review timestamps are substantive review history.
Full serialization includes execution time and supports round trips; substantive
serialization restores omitted execution time to null when read. The checked-in
golden fixture protects v1 serialization and claim-ID compatibility.

## Fixtures and verification

`tests/evidence_fixtures.py` and `tests/fixtures/evidence_v1.json` are explicitly
synthetic contract examples with invented source IDs, placeholder digests, and
`example.invalid` URLs. They are not retrieved records, verified real awards,
or a production fallback. Tests cover all nine contracts, invalid identifiers,
unknown provenance, representation honesty, ambiguous candidates, unsupported
outcomes, independent completeness dimensions, partial histories, manifest
references, version rejection, stable IDs/serialization, and legacy reconciliation.
Existing offline tests continue to protect CLI, output and checkpoint behavior.

Run the full suite and explicit offline smoke test using the commands in
[cloud.md](cloud.md). CI covers Python 3.11 and 3.12. No live source/API behavior
is validated by these schema tests.

## Unresolved questions and boundaries

- Authoritative agency namespaces/crosswalks and parent-award key semantics still
  require official documentation. No mappings or matching rules ship here.
- Revision precedence, deleted/corrected actions, date equivalence, financial
  definitions, precision tolerances, and evidence sufficiency remain unvalidated.
- Completeness assertions require future source-specific evidence rules; these
  contracts reject structural contradictions but cannot prove their truth.
- Source-wide completeness cannot be inferred from bounded retrieval.
- Older evidence with missing collection metadata remains usable for limited
  claims, with unknowns and explicit limitations; no raw-evidence migration occurs.
- Review storage, packet rendering, network adapters, artifact verification,
  rule execution, and pipeline integration are deliberately deferred.
