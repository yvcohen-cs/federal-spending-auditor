# Phase 3C2: offline evidence ingestion and provenance

Workstream C of [Issue #1](https://github.com/yvcohen-cs/federal-spending-auditor/issues/1).
This opt-in layer reads existing local evidence, checks supported structures and
declared hashes, and produces a deterministic inventory. It never collects data,
calls APIs, follows URLs, matches awards, compares finances, or assigns claim
outcomes. A cross-source disagreement is not an allegation of misconduct.

## Usage

From the repository root, with an existing trusted evidence directory:

```sh
.venv/bin/python -m src.verify_evidence --root data/raw/fy2025/EXISTING_RUN
.venv/bin/python -m src.verify_evidence --root data/raw --output reports/evidence-validation.json
```

The output defaults to one JSON object on stdout. `--output` exclusively creates
a new file outside the evidence root; its parent must already exist. Existing
files, symlinks, and output paths inside evidence are refused. The command does
not create directories or overwrite reports. Reports contain public provenance
and identifiers; do not commit them. `reports/*` remains ignored.

An optional `--execution-time` adds the actual validation execution UTC timestamp,
which is excluded from the substantive digest. It never fills a retrieval time.

To check a previously saved report, explicitly place a copy in the trusted root
(a user operation, not performed by the validator), then use its relative path:

```sh
.venv/bin/python -m src.verify_evidence --root data/raw/fy2025/EXISTING_RUN --manifest validation.json
```

The manifest control file is securely read and rechecked but excluded from its
own inventory. The input can be a C2 `IngestionManifest`, the CLI report wrapper,
or a C1 `VerificationRun`. A C2 inventory is exhaustive: new or missing entries
fail verification. A C1 run declares a subset of artifacts and its comparison
record references, so other collected metadata remains inventoried. C1 artifact
hashes are checked using their declared representation basis. Existing v1 schema
types, IDs, serialized fixtures, and readers are unchanged; no migration occurs.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Nonempty scan finished; every inventory entry passed supported structural validation |
| 1 | Scan finished, but evidence is incomplete, unsupported, or the directory is empty |
| 2 | Invalid/missing/unreadable/changed evidence, invalid declarations/arguments/output, or incomplete scan |
| 130 | Validation interrupted; partial batch results cannot be trusted |

The JSON wrapper contains `manifest`, `summary` counts, `substantive_sha256`, and
`exit_code`. A wrapper's counts/digest/exit code must agree with its manifest when
read back. `complete` means the **directory validation scan** finished, not that
source data, transaction history, or a financial claim is complete. `verified`
means supported structural checks passed, never a C1 `verified_match` claim.
Unanchored content is labeled `integrity: unanchored`; matching a declared hash
is `declared_match`. Neither authenticates a source or prevents malicious edits
to both evidence and its declarations.

## Verified saved formats and adapter boundaries

These formats were verified by reading current collectors and by tests invoking
them with deterministic mocked responses. No live API format, current endpoint
availability, historical source completeness, or source authenticity was newly
validated. Unknown formats are explicitly unsupported, never guessed from data.

| Saved artifacts | Code-defined representation and provenance |
|---|---|
| `response_000000.json`, etc. | Phase 3B stratified v2 envelopes: exact parsed `request`, `retrieved_at_utc`, and parsed `response`; query plan in `query_metadata.json`, canonical envelope hashes in checkpoint events |
| `page_0001.json`, etc., award collection | Legacy parsed USAspending response bodies; query metadata and a legacy checkpoint; no exact page request/limit or per-page timestamp saved |
| Transaction `page_0001.json`, etc. | Parsed response body with transaction `results`; adjacent query metadata identifies the transaction endpoint and generated award ID; no exact page request/limit or retrieval timestamp saved |
| `fpds_lookup_001_page_001.xml`, etc. | FPDS XML from `response.text`, written as UTF-8 text; `fpds_lookup_001_query.json` records initial lookup parameters and **lookup completion** time, not each page request or retrieval time |
| `query_metadata.json`, `checkpoint.json`, `sampling_coverage.json`, `run_metadata.json`, FPDS query JSON | Supporting parsed JSON with byte and canonical hashes; structure validated to the adapter's documented extent |

Legacy `generated_at_utc` is query metadata generation, not page retrieval. FPDS
pagination URLs and per-page HTTP status were not saved. These omissions remain
explicit. For stratified requests, POST is supplied by the inspected collector
contract and labeled `method_from_collector_contract`, not claimed as captured
HTTP metadata. Endpoint comes from validated saved query metadata, not from a
guessed URL. If that metadata is absent, endpoint stays null. Legacy pages without
metadata remain award-or-transaction unknown. Numeric native identifiers are not
coerced into strings; their limitation is recorded and original values remain in
the source artifact. String IDs preserve zeros, punctuation, case and whitespace.

The adapters extract only the actual result identifiers and record locators:
USAspending JSON pointers into `results`, and FPDS Atom `/feed/entry[n]` positions.
FPDS PIID/agency/modification/transaction and Atom IDs remain separate namespaces.
An alternate link is retained only as a source-supplied link, not validated as a
unique permalink. Source update strings stay raw, per-record values; date-only
values are not fabricated into UTC timestamps. Repeated records, identifiers or
modifications are inventory observations, never duplicate-payment conclusions.

## Identity, representation, and reproducibility

`src/evidence_io.py` owns bounded, descriptor-relative IO and strict parsers.
`src/evidence_ingestion.py` owns collector adapters, C1-compatible artifacts and
record references, companion C2 v1 schemas, and manifest validation.
`src/verify_evidence.py` owns only the opt-in command and report destination.
No normal collection or reporting code imports or calls this layer.

Three identities must stay distinct:

- **Artifact identity:** unchanged C1 `artifact:sha256:<digest>`, covering the
  complete preserved representation. JSON hashes use sorted keys, compact
  separators, ASCII escaping, and no nonfinite values, matching Phase 3B's
  envelope digest. XML hashes cover UTF-8 decoded text without newline or Unicode
  normalization. `byte_sha256` separately covers actual saved file bytes.
- **Payload content identity:** `content:sha256:<digest>` covers the canonical
  JSON response body, excluding a stratified envelope's request/time metadata;
  for XML it covers the same decoded text as the artifact. Thus two envelopes
  can have equal response content but different artifact and observation IDs.
- **Observation identity:** `observation:v1:<digest>` fingerprints source,
  endpoint, method, exact request, known per-page retrieval time and representation.
  It excludes content and local path. Missing event metadata yields a null ID
  and `observation_identity_status: ambiguous`; no filesystem time, ordinal, random
  ID, or current time is substituted. Equal fingerprints may be copied evidence
  or indistinguishable events; they do not prove retrieval-event multiplicity.

Source-record identity is a separate C1 `SourceIdentifier` supported by a record
locator. No record/content hash, name, or address is a real-world identity.

Every occurrence remains a separate sorted path entry, including identical
content at multiple paths. Conflicting payloads for one documented event
fingerprint fail closed rather than choosing an observation. Artifact hashes do
not include a path, so copied content keeps its C1 identity. C2's companion
manifest supports these occurrences without relaxing C1 `VerificationRun`'s
unique-content constraint.

Companion schemas use C1's strict `schema_type` and `schema_version: 1` handling.
Computed observation/content IDs and ambiguity status are emitted and checked on
read. Fields include representation and byte hashes, metadata dependencies,
record references/native IDs, known provenance, limitations, validation status,
and sanitized error codes. Unknown metadata stays null. Execution time is separate.
Entries and metadata paths are sorted; record order remains source order.
Serialization is deterministic for the same directory and declarations.
Changing from unanchored validation to declaration checking changes the integrity
assessment and consequently the substantive digest; an execution timestamp does not.

## Security model and limits

Supported execution is POSIX with `dir_fd`, `O_NOFOLLOW` and directory descriptors
(the project's Linux Python 3.11/3.12 CI). Unsupported platforms fail closed.
The user explicitly chooses a trusted root and output parent. No symlinks are
accepted in their path components. Relative artifact/manifest paths reject
absolute paths, traversal, empty/dot segments, backslashes, drive syntax and
control characters. File reads refuse symlinks, hardlinks, directories, devices,
sockets and FIFOs. Filenames from checkpoint entries are constructed only from
validated integer page/step numbers. Metadata cannot choose arbitrary read paths.

Reads compare file identity, type, size, link count, nanosecond modification and
change times before/after reading, then re-open the rooted path to detect
replacement. All source and dependency files are read again and compared after
adaptation. Discovery is repeated to detect added/removed files. A detected
metadata change invalidates dependent observations. A failed/interrupted final
scan drops all previously trusted observations and returns a partial failure.

This is conservative race detection, not an atomic filesystem snapshot. Keep
collectors stopped during validation. The root/output parent and their ancestors
must be controlled by the user, with no hostile mount changes or directory moves.
Privileged attackers, coordinated changes after final checks, storage loss, and
authenticity/tamper-proof signatures are outside this threat model. An interrupted
output write may leave a partial newly created report; it is never substituted
for an existing file and will fail later JSON validation.

Defaults cap each artifact at 8 MiB, the cumulative first-read file sizes at
64 MiB, all directory entries at 4,096, and traversal depth at 16. CLI byte limits
can be adjusted with `--max-artifact-bytes` and `--max-total-bytes`. The Python
API also accepts positive `max_files` and `max_depth`. Reads are bounded even if
a file grows; rereads repeat the same per-file cap. Parsed object and report
memory has Python overhead beyond byte caps; this is bounded-input processing,
not a streaming archive parser. JSON recursion failures fail explicitly. XML is
limited during parsing to 100,000 elements and depth 128.

JSON uses duplicate-key detection and rejects NaN, Infinity and overflowing float
tokens. UTF-8 decoded XML uses standard-library ElementTree with an explicit
DOCTYPE rejection target plus conservative DTD/ENTITY prechecks. Alternate byte
encodings/NUL declarations are refused; no XInclude, stylesheet, external entity
or remote-resource processing occurs. Links are never followed. No parser or
runtime dependency was added.

Errors contain fixed codes, not raw values or OS exception text. Credential-like
metadata keys are rejected rather than echoed or silently redacted. This is a
guard against known sensitive keys, not a general secret detector; use only the
public collector evidence and inspect reports before sharing. Reports intentionally
contain public native IDs, URLs and requests, but never full response records.

## Tests, limits, and deferred work

Tests create authored synthetic inputs under temporary directories, including
artifacts emitted by mocked unchanged collectors. They cover parser attacks,
paths/links, limits, hash mismatches, missing pages, races, metadata dependencies,
observation ambiguity/conflicts, C1 compatibility, deterministic serialization,
CLI/report codes and partial interruptions. The existing suite prohibits Requests
HTTP. The CI matrix runs the full suite and explicit offline smoke test on Python
3.11 and 3.12. No downloaded datasets or generated reports are checked in.

Checkpoint validation here checks structure, referenced-file presence, v2
envelope hashes and query-plan consistency; it is not the sampler's full
allocation/buffer replay or a proof that no records were omitted upstream.
Legacy checkpoint formats do not declare content hashes. Supporting metadata
validation is structural, not a semantic audit of every historical field.
No pagination exhaustion is promoted into complete transaction history or
source-wide completeness. No claim-specific comparison result is generated.
Unknown source namespaces, financial/date equivalence, revision ordering,
authoritative completeness, freshness and agency crosswalks remain unresolved.
Collection hardening, matching/comparison engines, packets, review persistence
and normal pipeline integration remain deferred to later phases.
