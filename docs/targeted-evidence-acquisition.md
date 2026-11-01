# Phase 4C11: targeted offline evidence acquisition

C11 provides a working acquisition foundation: primary-replayed C10 plans become a bounded source-specific queue; selected jobs consume preserved captures or authored synthetic transcripts; validated observations enter before/after C10 qualification replay. No live transport is enabled. No financial or production readiness rule changes.

## Planning and source contracts

`acquisition_planning.prepare(cases, limits=...)` accepts up to 24 explicit case recipes. Each recipe supplies original C3 collection roots and `ScopeRequest`, optional SAM capture roots, optional requested `HistoricalInterval`, and optionally a saved C10 report. Saved conclusions are checked against primary inputs with C10 `verify_report`; they are never trusted as authority. Across cases, primary report bytes are bounded at 32 MiB and original plans at 4,000.

The version-1 standard-library schemas are `AcquisitionLimits`, `RequirementTarget`, `SourceRequestSpec`, and `AcquisitionQueue`. Queue references bind original case/report digest, contract context, resolution-plan identifier, dimension, and original typed requirement. Native identifiers remain strings with original punctuation and leading zeros. Unknown parent identifiers do not coalesce unrelated contracts. Work sharing deduplicates an identical native query, not real-world entities. The only cross-source counterpart planning uses C10's existing complete-component USAspending/FPDS mapping; SAM remains separate.

Priority uses identity/parent/provenance prerequisites, historical coverage/revisions, counterpart/as-of requirements, monetary semantics, freshness, and the number of requirements served by one query. Award amount is not a priority input. Supported offline subsets and validation dependencies are interleaved so blocked parent requests cannot starve every history job. At most 32 jobs (default eight) are selected; excluded outside-context plans and deferred plans remain explicit. A selected request touching a plan does not mean that its evidence requirement is resolved.

Each specification contains source, native context, original query selection where available, requested historical interval, fields, pagination policy, request/page/byte/retry limits, documentation dependencies, expected evidence and stop conditions. USAspending's generated award identifier comes only from preserved request metadata; it is never reconstructed from PIID or a transaction key. The FPDS planner uses the existing quoted PIID/agency query and restricted continuation parser. SAM uses the frozen source-native first-page request and no live continuation or retry. Date intervals remain declared requirements; unsupported date filters are not invented.

`DOCUMENTED_SUBSET` means the existing request/parser subset is documented and offline-testable. It does not certify current endpoint access, native query enforcement, recall, freshness or historical completeness. C11 claims **no verified new live API behavior**. The separate assumptions include parent-IDV mapping, historical/as-of coverage, revision/correction/deletion lineage and SAM continuation semantics.

Parent-IDV requests are explicit `VALIDATION_REQUIRED` or `BLOCKED` dependencies. The current award adapters do not establish an authoritative parent-IDV query/record mapping. Their request payload stays null; a child reference is never relabeled as a parent record, and no USA parent generated ID or SAM/FPDS alias is inferred. Operator/source validation must resolve this before a future adapter can execute such a request.

## Acquisition, provenance and failure boundaries

`evidence_acquisition.acquire(queue, path, preserved=..., synthetic=...)` defaults to offline operation. Inputs are typed `PreservedReplay` bindings or `SyntheticScenario` transcripts, not caller-provided transport callbacks. Live flags and locally invented authorization records cannot enable networking: this phase has neither separately verified live access nor an installed live transport. No source credentials are read. There is no TLS/proxy bypass or redirect fallback.

A preserved replay revalidates source controls, body hashes, native selection and relevant pagination, then copies the exact original files into a new private append-only bundle. Original timestamps and representation labels remain intact. It is labeled `PRESERVED_SOURCE_OBSERVATION_NOT_NEW_HTTP_REQUEST`; a copied capture is not independent evidence. Synthetic materialization uses only fixture transports and a synthetic profile, labeled `SYNTHETIC_ONLY`; it is never presented as a live federal API success. Synthetic and preserved-live cohorts cannot be pooled.

The default request budget is 16, page bound two, and retry count zero; caps are 64 requests, four pages, one retry, and 1 MiB per body. Original selected-source attempts are counted separately from all source attempts retained in a multi-source capture. A failed/uncertain job consumes its reservation; failure cannot reset the global budget. Retryable fixture failures may recover within the cap, retaining every failed attempt. Long Retry-After instructions stop rather than being ignored. SAM retains its frozen zero-retry, first-page boundary. No captured next URL is followed by a live transport.

Successful pagination establishes only a bounded observed subset. Empty feeds are inconclusive. Unsafe continuations, missing pages, conflicting counters, unsupported identity, failed requests and partial bodies block successful incorporation. Any supplied-job failure blocks before/after incorporation for the batch; original evidence and partial synthetic stages remain for inspection. No partial history is silently repaired. The new-run interface does not resume interrupted C11 bundles; use a separate fresh run after inspection. Existing C3 checkpoint semantics are unchanged.

Synthetic materialization stages are preserved siblings named `<run-name>-synthetic-NNN`, including failures. They are not cleaned up or overwritten automatically. Input/source files are never edited. Run outputs are limited to 64 MiB and 4,096 files on readback. Commit manifests are written last. Missing files, extra files, symlinks/hardlinks, altered bodies, unsupported versions, duplicate receipts, budget conflicts and unsafe relative paths fail closed.

## Integration and resolution reporting

`resolution_replay(cases, run_path)` rebuilds the queue from original primary evidence, revalidates the acquisition manifest and every copied capture, and recomputes C10 qualification from old plus newly validated inputs. Existing C10 bounds remain: at most eight C3 roots and three SAM roots per case. Identical inventories already present in the baseline are not incorporated twice. If acquisition failed, original qualification remains unchanged and no requirement is marked resolved.

Each new observation is stored once with native identifiers, action/revision fields, original monetary/temporal observations, retrieval timestamp and provenance. Its requirement-impact records identify the original plan and requirement, supplied observation, native context, dimension, recomputed state, whether the narrow requirement resolved and remaining contract blockers. Unrequested context records in a preserved multi-source capture remain explicitly distinguished. No revision winner or missing modification is inferred. Trace output is bounded at 10,000 impact records.

JSON, Markdown and escaped static HTML separate prepared/documented requests, additional validation dependencies, preserved/synthetic evidence, resolved narrow requirements, unresolved blockers and unknown historical completeness. Resolution requires fresh primary replay, not a saved conclusion. Report checksums detect corruption, not source authenticity; `verify_report` recomputes the entire result from original cases and the acquisition bundle. Neither acquisition success nor a resolved evidence requirement enables financial arithmetic or screening.

## Offline CLI

A case file is a JSON list. Paths are runtime inputs and are not serialized into the public queue. `scope` and `interval` use their existing versioned `to_dict()` schemas. Omit `report` to recompute C10 directly.

```json
[{"collections":["/path/to/c3"],"sam_captures":[],"scope":{"schema_type":"ScopeRequest","schema_version":1,"piid":"SOURCE-PIID","agency":"0001","parent_piid":null,"parent_agency":null,"modification":null,"transaction":null,"namespace":"usa-fpds-v1"}}]
```

Prepare a queue and report without acquiring anything:

```sh
python -m src.evidence_acquisition --cases /path/to/cases.json --run-dir /path/to/new-plan-run --report-dir /path/to/new-plan-report
```

Inspect `pilot-plan.json` for request IDs. A replay map is a list of `{"schema_type":"PreservedReplay","schema_version":1,"request_id":"evidence-request:v1:...","path":"/path/to/permitted-capture"}`. A fixture map is a list of `{"request_id":"...","scenario":{"schema_version":1,"responses":[...]}}`, using the existing C3 fixture format or SAM JSON fixture responses. Then create a fresh run with `--replay-map` or `--fixture-map`. Use the same cases with `--run-dir ... --verify-report /path/to/report` for primary verification. `--live` always refuses before source access or output creation.

No real datasets, credentials, private histories or generated reports belong in Git. The only compatibility infrastructure change raises the source-installation module-count bound from 100 to 128 so the two new modules are included in the existing compatibility fingerprint. Its hashing algorithm, symlink rejection, 8 MiB size cap and checkpoint mismatch checks remain intact; no modules are omitted from attestation.

C12 should validate an authoritative source-native parent-IDV mapping and a narrowly authorized acquisition scope, then address revision/deletion coverage and common as-of evidence. Current historical completeness, freshness and financial restrictions remain unresolved until primary evidence establishes them.
