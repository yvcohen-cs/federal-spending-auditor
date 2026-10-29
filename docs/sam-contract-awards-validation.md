# Phase 4C2: authorized SAM Contract Awards API validation

This phase implements a separate, offline-first research harness. It does not
replace FPDS ingestion, change C4/C5 eligibility, authorize financial arithmetic,
upgrade Phase 4B4 readiness, or authorize larger collection. Current recommendation:
**A. Offline prototype only**. No configured SAM credential was available, so
**authenticated live validation is blocked**; live observation metrics are
unavailable, not a measured failure or a collection of zero matching contracts.

## Baseline and preregistration

Merged Phase 4C1 PR #16 is main commit
`cc4ed245adccc9809317380f00afe3690bbda589`. Branch
`phase4c2-sam-validation` starts from that latest main. The untouched baseline
passed **1,170 offline tests** and the explicit smoke test.
Baseline implementation fingerprint:
`d444cc1da3c8729d1f8713e77413424de8bc8744a58ce1bbc860d5f3af02ed23`.

[SAM protocol v1](sam-validation-protocol-v1.json) was committed as **a596d0a**
before live experiments or new evaluation outcomes. Canonical protocol SHA-256:
`fc079d50e894be93f57d5e14a77cf63a4001503f6f18a532f99dfdb3e134dfb2`.
The implementation pins that digest; future criteria changes require a new
version. The protocol sets maximums of three explicit native subjects, twelve
HTTP requests, two pages per subject, zero retries, one MiB per response, ten
seconds per connect/read timeout, and 32 MiB per capture/output directory.
Subjects and selection semantics are fixed in the new append-only run plan
before the first request, with no replacements or broad search fallback.

Frozen protocol **file-byte** hashes (different from canonical JSON hashes):

- `parent-identity-protocol-v1.json`:
  `c2dc79a231f8243395635e90298f5099633b0d5859ec32d3619071b5816f754d`.
- `readiness-protocol-v1.json`:
  `063bd4d435624b02fe9ff4cd3da648e5388ed234485e427937c319eccedb6d88`.

Original source inventories:

- 24-award pilot:
  `02b45a4c059b48a798689b842bef949a44b48996cba20da9fd3a7ee047fd0a1f`.
- Three-award holdout:
  `ff0f4393b07cd69f282e2ea14e4f2571a3a53760d25827e711d0ddeb6d7b34a8`.

The original source bytes and both protocols remain unchanged. The Phase 4C1
381-occurrence result (154 in scope, 88 out, 139 ambiguous) is a distinct
historical reference, not pooled with SAM fixtures or reclassified here.

## Current official research

Reviewed October 28, 2026, Pacific time:

- [Official GSA Contract Awards API guide](https://open.gsa.gov/api/contract-awards/).
- [Published OpenAPI YAML](https://open.gsa.gov/api/contract-awards/v1/openapi.yaml),
  `openapi: 3.0.1`, `info.version: 1.0`. The guide's browser fetch could not decode
  its binary/octet-stream media type; a bounded, TLS-verified, no-redirect GET
  retrieved 53,141 documentation bytes through the configured proxy. SHA-256:
  `87ab11d503a19a622dfbb1a1ea8fa840f19440a83b0b2d89cf6132ddb3cfb8fc`.
  This downloaded document remains outside git. It is not an authenticated
  Contract Awards data request.
- [Official FPDS/SAM variance document](https://open.gsa.gov/api/contract-awards/v1/FPDSvsSAM-ContractDataAPI.pdf).
  Field correspondences are research references, not automatic identity,
  monetary or historical equivalence mappings.

The guide records an August 25, 2026 update for commercial product/service and
publicDeltaDate. Published documentation and schemas contain discrepancies;
they are not treated as proof of observed API behavior.

| Dimension / native field | Knowledge state | Finding and limit |
|---|---|---|
| GET `https://api.sam.gov/contract-awards/v1/search` | Documented | Production route requires an account API key. Alpha, export/download links, aggregations and alternative endpoints are outside this client |
| Account authorization, roles, IP and quota | Documented; authenticated-observed unavailable | Revealed access requires an account/key; unrevealed access is role limited; system accounts can require IP registration. Listed daily defaults range from 10 to 10,000, not a verified entitlement or remaining balance |
| `limit` | Documented | Guide maximum100/default10; research limit1–10, default2 |
| `offset` | **Contradictory** | HTML describes page index/default0; OpenAPI top-level query default is1. Examples include offset25/limit5. The error description refers to offset × limit. No live continuation contract is established |
| `totalRecords`, `limit`, `offset` response | Documented with representation differences | Schemas say numbers; examples often use decimal-digit strings. Accept bounded nonnegative integer/digit-string counters without coercing identifiers. Null/missing/bool counters are unsupported |
| `contractId.piid`, `contractId.subtier.code` | Documented | Native identity fields, separate from contracting/funding agency codes. Exact query enforcement and recall remain unobserved |
| Referenced IDV PIID/subtier/modification | Documented | Separate source-native parent components. Complete pair can assert a relationship in supported award/order context; missing data cannot establish no parent |
| `coreData.awardOrIDV`, `awardOrIDVType.code` | Documented | Award versus IDV context is necessary before interpreting type letters. IDV records cannot substitute for requested child awards |
| `modificationNumber`, `transactionNumber` | Documented | Separate action components. Requested constraints are checked locally; transaction query support is not invented |
| `coreVersionId`, `transactionData.version` | Documented field; revision meaning unknown | Values such as1.4/1.5 are preserved as source document/schema context, not unique immutable action revisions or a cross-source revision certificate |
| `awardDetails.transactionData.status` | **Contradictory** | OpenAPI declares a string; guide tables/examples show an object. Both representations remain original evidence; neither is interpreted as current/deleted status |
| `dates.dateSigned`, `periodOfPerformanceStartDate` | Documented | Signed date is separate from performance start. No effective-date alias, timezone assignment or date comparison is introduced |
| Created / approved / last modified / closed dates | Documented | Distinct native timestamps, not publication, freshness or retrieval guarantees |
| `publicDeltaDate` | Documented query concept | Selects last-modified or reveal-date changes; does not establish complete publication lineage or source freshness |
| `deletedStatus=yes` | Documented | Deleted-only query and six-month visibility window, subject to account visibility. No complete deletion or correction history guarantee; this client does not issue deletion queries |
| `oldContractId` | Unknown correction semantics | Original context retained, never used as fallback identity or a correction/deletion certificate |
| `dollars.actionObligation` versus totals | Documented labels; compatibility unknown | Distinct original strings and paths retained. Currency, monetary basis, lineage and C5 comparability remain unverified |
| Source-wide history and freshness | Unknown | No complete-history or freshness certificate established; a terminal query page cannot supply either |
| FPDS/SAM/USA source independence | Inferred shared lineage limitation | Procurement representations are not automatically independent corroboration |

The OpenAPI `deleted` boolean appears in an extract/job schema, not a verified
award-record deletion indicator. It is not mapped into record status. Some
OpenAPI contracting-subtier labels and guide descriptions are inconsistent;
code/name fields and namespaces are never repaired by an assumed crosswalk.
No missing field, matching amount or matching timestamp proves any relationship.

## Authorization result

The managed environment reported no configured secrets/runtime credential
bindings. A presence-only check of the supported `SAM_GOV_API_KEY` binding was
false. No credential files were searched, no values printed, and no key was
requested or created. No authentication, API quota, role visibility or endpoint
behavior was tested against the Contract Awards data endpoint.

Actual award API request count: **0**. Authenticated subjects, pages, records,
identity rates, parent findings and revision findings: **unavailable**.
Documentation GETs and synthetic in-process calls are counted separately from
live award-data requests. Missing access does not establish a defect in SAM.

The live mode consumes only the normal environment binding and requires an
explicit `--live`, preselected native subjects and a new capture directory.
A missing credential fails before directory creation or an HTTP request. The
harness never initiates credential configuration, login, role changes or proxy /
TLS / access-control changes. Any future credential setup must use the authorized
environment workflow, not CLI arguments or uploaded files.

## Implementation and typed evidence

New additive modules:

- `src/sam_validation_models.py`: schema-v1 `SAMField`, `SAMNativeAward`,
  `SAMNativeAction`, `SAMObservedRecord` and `SAMPage`; separate native identity,
  parent, instrument, action, raw money, timestamp, prior-ID and status fields.
- `src/sam_validation_capture.py`: immutable `SAMResearchSelection`, fixed
  protocol/client budgets, secure transport, reservation journal and primary-byte
  replay validator.
- `src/sam_validation_reporting.py`: field/revision/readiness matrices, separate
  live/synthetic metrics, C6 citations/actions, deterministic safe outputs and
  primary-evidence revalidation on report write/read.
- `src/sam_validation.py`: explicit live, synthetic demo, saved-capture replay or
  offline blocked-access report. There is no production pipeline hook.

Original source identifiers remain exact strings, including punctuation and
leading zeroes. Unsafe query operators are rejected rather than removed or
normalized. Identity agency and parent agency remain different fields and
namespaces from contracting/funding agency. Native components are separate from
constructed claim/observation IDs and parsed-content hashes. Content hashes group
retrieval content, not real-world persons or awards.

Field presence distinguishes omitted, null, empty, scalar and unsupported shape.
An omitted field's null placeholder is explicitly labeled omitted, never called
a native null assertion. Numeric source identifiers are not coerced to strings.
Money values are derived canonical parsed JSON representations with source-dollar
labels and explicitly unverified currency/basis; exact numeric lexemes and all
original fields remain in the saved body bytes. No arithmetic or zero defaults
are implemented. Local native timestamps remain unzoned; no temporal alignment
or currentness certificate is inferred.

`SAMObservedRecord` recomputes fields/identity/status from its original parsed
record. A positive native parent relationship requires supported core schema
1.4/1.5, AWARD context, type A/C and a complete native pair. A returned pair
cannot fill unknown **requested** parent context. No SAM positive no-parent
rule is claimed, even for a type-D record: the Phase 4C1 FPDS-specific absence
rule is unchanged and not transferred. Unsupported versions, type/parent context,
wrong identity components and IDV/child mismatches cannot create an eligible
match. `supported_schema` means a supported **known field subset**, not full XSD /
OpenAPI conformance or demonstrated schema stability.

The before/after table compares the component-only local scope baseline with the
stricter SAM schema/instrument/parent rule on SAM records. It is not an update to
Phase 4C1's frozen cohort. Exact PIID/identity-agency agreement is a separate
metric from full scope. Action components, document versions, corrections,
deletions and common revision evidence stay separate. Conflicting contents under
a complete native action key are retained as variants, not silently collapsed
into one financial state or alleged correction. C4/C5/history never consume these
records or reports. No fabricated null-parent action key or agency crosswalk is
introduced.

## Bounded transport, capture and interruption

The request is fixed GET, production route only, exact PIID and identity-subtier,
optional documented parent/modification filters and sections
`contractId,coreData,awardDetails`. Transaction constraints are local. No free-text
search, arbitrary URL, deletion query, export, aggregation or record URL is
followed. Redirects and retries are disabled; inherited proxy and CA trust remain
intact. Public metadata excludes the API key; the key is injected only in memory.

Three subjects × two pages gives a stricter structural maximum of **six** calls,
within the protocol's twelve-call ceiling. More importantly, **live currently
stops globally after the first page** because the continuation contract remains
unvalidated, even when totalRecords appears small or zero. The plan does not
claim that any budget verifies account entitlement. Rate limits/auth failures
stop without retries, replacements, fallback hosts or larger searches.

Synthetic-only row-offset/page-index modes exercise two-page boundary logic.
They cannot be selected for live captures. Counters, requested offsets/limits,
changing totals, duplicates, response versions, unsafe continuation fields and
nonterminal page caps are checked. All occurrences and their page order remain
preserved. Unstable ordering and full recall cannot be established by two pages.
Live empty feeds remain inconclusive. Query-pagination terminality is separate
from transaction-history completeness, source-wide completeness and freshness;
the latter three remain unknown even in a terminal synthetic fixture.

Before each transport call, an append-only reservation is written. After a safe
response, metadata and raw application response bytes are saved, followed by a
result and hash commit. A pending reservation without a completion commit is
uncertain: a call may or may not have happened. Interruption returns130 and
retains this journal. Replay rejects it as incomplete and there is no automatic
resume/reissue. Existing directories cannot be reused or overwritten.

Only bounded allowlisted headers (content type, ETag, Last-Modified, Retry-After,
API version) are retained. They are observations, not revision or freshness
certificates. Non-JSON/unsafe bodies, encoded credential echoes, credential-field
keys and export/signed tokens are omitted, never redacted and relabeled as raw.
Rejected bodies have no preserved-byte hash and are explicitly marked rejected.
Safe error JSON can remain original evidence but is not parsed as award records.
Partial bodies and failures cannot become complete usable observations. Rejected
headers are explicitly noted. Standard and urllib3 HTTP/HTTPS wire-debug modes
are refused before a request, and ordinary connection logging is suppressed.
These controls are tested boundaries, not a universal security certification.

Capture replay validates the exact inventory/hash commit, strict plan/version,
reservations, subject/page order, original requests, budgets, body hashes,
response metadata, source schemas, stop rules and result semantics. Rehashing an
edited manifest cannot silently upgrade completeness, permit a forbidden request
or hide a stopping condition. Symlinks, unsafe paths, oversized files and source /
output overlap are refused. A new source implementation fingerprint still
requires a new legacy research run; old checkpoints are never silently upgraded.

## Offline outputs and reproducibility

```sh
mkdir -p reports
python -m src.sam_validation --offline --run-dir reports/NEW_sam_blocked_access
python -m src.sam_validation --demo --run-dir reports/NEW_sam_synthetic_demo
python -m src.sam_validation --root reports/SAVED_sam_capture \
  --run-dir reports/NEW_sam_replay
python -m pytest -q tests/test_sam_validation.py
python -m pytest -q
python -m pytest -q -p no:cacheprovider \
  tests/test_federal_spending_auditor.py::test_pipeline_writes_cleaned_flagged_and_summary_outputs
```

The demo creates a separate sibling directory containing explicitly synthetic
source journals. Offline no-capture mode checks credential presence only and
performs zero HTTP calls. Capture replay reads no credential. Each output root
must be new and have an existing parent. Commands finish with exit1 because
limitations remain; invalid or blocked input exits2, interruption130.

Only after supported access is configured through the authorized workflow:

```sh
python -m src.sam_validation --live --selection work/native-sam-selection.json \
  --capture-dir reports/NEW_sam_capture --run-dir reports/NEW_sam_live_report
```

A selection is a standard schema-v1 `SAMResearchSelection` envelope containing
one to three `ScopeRequest` envelopes with `namespace: samgov-v1`, an explicit
native PIID/four-character identity agency, paired parent context if known,
`limit: 2`, `profile: live`, `pagination_rule: unvalidated`. No credential belongs
in that file. Synthetic profiles are refused by this live CLI mode.

Outputs are `sam-validation.json`, readable Markdown, escaped static offline
HTML, a plan and a hash commit. The writer regenerates projections from the
primary capture before writing; the reader requires that capture again and
checks inventories, hashes, typed records, matrices, plan and readable projections.
Reports are not primary trust anchors. Claim IDs and substantive digests exclude
execution locations/times; source retrieval timestamps remain provenance.

Denominators remain separate: selected subjects, attempted subjects, reserved /
completed HTTP attempts, successful HTTP status, parsed pages, record occurrences,
distinct content and complete action-key variants. No authenticated metrics are
borrowed from fixtures. Traceability or a working parser cannot certify access,
source stability, identity precision, parent absence, historical completeness,
freshness or production readiness. No misconduct label or risk score exists.

## Migration decision and Phase 4C3

The twelve readiness dimensions are reported separately using PASS / CONDITIONAL /
FAIL / UNKNOWN / NOT_APPLICABLE vocabulary, without a weighted score. For the
current no-capture report **all source dimensions are UNKNOWN**, including access.
A synthetic journal can support PASS for its inspected provenance/replay only;
all authenticated source capabilities remain UNKNOWN. An observed authentication
failure is FAIL for the bounded access attempt, not a general source judgment.
An actual successful supported first-page capture could support at most a bounded
research recommendation. No report can authorize production migration, broader
collection, financial eligibility or an existing readiness upgrade.

Priority Phase 4C3 work:

1. Validate already-authorized account access/visibility and a preregistered
   first-page contract on explicit native subjects. Do not infer quota or roles
   from merely having a key.
2. Resolve offset defaults/progression and status-shape contradictions with GSA
   and bounded authenticated evidence before any continuation. Establish ordering
   and total-count stability independently; do not invent a pager.
3. Establish SAM-native parent/no-parent applicability and identity namespaces
   without transferring FPDS inference rules or using names/amounts/dates.
4. Establish immutable revision/correction/deletion lineage, financial meanings,
   currency, counterpart evidence, history coverage and freshness separately.
5. Only then consider a separately approved, human-reviewed parallel validation
   cohort. Production replacement and larger financial screening remain outside
   this phase.

Final offline replay, test and CI results are recorded in the PR. No source
responses, downloaded schema, secrets or generated reports are committed.

## Final local validation record

- Baseline main: **1,170 tests passed**, plus explicit offline smoke.
- Feature suite: **1,282 tests passed** in258.22seconds, including **112 new cases**.
  Explicit offline smoke separately passed in2.28seconds.
- Final source implementation fingerprint:
  `a60ad2aff07ff0cfe58c220eca0a905eefdc6192d48ba3bf71f8182782f532ce`.
- Two synthetic demonstrations and their primary-evidence report reads matched:
  `451cd94736b468122981b9571f45748b2d9e3f4fb67bb3d8d682ae8d957b972f`.
  Each is **one fictional subject, two in-process fixture calls, two parsed pages,
  three native record occurrences, three exact native parent assertions, zero
  verified no-parent cases, zero revision certificates and zero financial
  authorizations**. Six populated monetary field observations remain withheld;
  these are fields, not six comparison pairs. History/freshness remain unknown.
- Two blocked-access offline reports and their readers matched:
  `901439669279b8c19609662df8f583152695312d8fde6900ff1dc348618c1899`.
  All twelve readiness dimensions are UNKNOWN, and authenticated metrics are null.
- Revalidated original source inventories equal the preregistered hashes before
  and after the work. Both frozen protocols are byte-identical. The existing
  Phase 4C1 report still validates at digest
  `083803501caac7622c316c2cd250e1c8c2828bdbe1fb6ba3572fcfaa0ac2c598`.
- Full tests prohibit live HTTP. New cases include rehashed-but-contradictory
  controls, no credential acquisition/replay reads, partial reservations,
  cross-page duplication/total changes/caps, exact action constraints, schema
  changes, placeholder parents, IDV confusion, wrong agencies, credential echoes
  in JSON/percent/HTML/base64 encodings, HTTP/HTTPS debug modes, output escaping,
  source immutability and rejection of report-level authorization forgeries.
  The row-count cap is checked before any record object construction, preventing
  oversized result lists from consuming processing beyond the requested limit.

Existing Python3.11/3.12 CI configuration is unchanged; final check URLs/results
and the exact reviewed head are recorded in the PR. Security/evidence self-review
found no critical unresolved defect. Parser scope, authenticated behavior,
pagination, parent absence and revision/financial semantics remain limited as
specified above; no production-readiness assertion is introduced.
