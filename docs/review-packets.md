# Phase 3C6: offline human-review evidence packets

Workstream C of [Issue #1](https://github.com/yvcohen-cs/federal-spending-auditor/issues/1).
Built on merged C1–C5. This opt-in reporting/workflow layer does not collect
records, infer relationships, change automated findings or implement C7.
An observed difference is not an allegation of fraud or misconduct.

## Architecture and trust boundary

The implementation plan is a strict projection layer: revalidate C3 and C4/C5,
project one packet per narrow claim, render escaped static HTML, publish a
commit-marked bundle, and store human assertions in a separate append-only log.
No collector, legacy report, checkpoint, existing schema or financial/matching
rule is changed. Standard-library models, C1 claim statuses and existing
C4/C5 results/provenance are reused rather than redefined.

- `review_packet_models.py`: schema-version-1 packet contracts; rules
  `review-packet-v1`. JSON readers check constructed IDs and recompute complete
  packet projections from the embedded validated financial/identity run.
- `review_packet_builder.py`: read-only C3/C4/C5 adapter, secure optional report
  readers, exact claim selection and conservative explanation catalog.
- `review_packet_html.py`: escaped accessible HTML with no scripts or remote
  assets; bounded generation and restrictive HTTPS source-link policy.
- `review_packet_io.py`: descriptor-relative POSIX IO, exclusive atomic file
  publication and commit-marked bundles, bounded secure readback.
- `review_events.py`: separate immutable review events, transition/chain/context
  validation, advisory locking and explicit append CLI.
- `build_review_packets.py`: separate opt-in offline JSON/HTML bundle command.

Generation reruns C4/C5 against actual preserved C3 evidence, including hashes,
source request scope and locators. Optional prior C4/C5 reports are schema and
wrapper checked, then compared substantively to the recomputed run. A stale or
tampered report cannot authorize a packet. Byte-integrity checks are repeated
after projection and before output publication. These are ordinary race checks,
not an atomic filesystem/upstream snapshot or proof of source authenticity.
Coordinated edits to evidence and all declarations remain outside hash assurance.

## Packet contracts and claim scope

| Model | Contents and validation |
|---|---|
| `ReviewPacket` | Stable snapshot packet ID, existing claim, source summaries/citations, comparison explanation, full alternative catalog, limitations, unresolved questions, next checks and rule version |
| `ReviewedClaim` | Exactly one existing C4 identity result or C5 financial result; claim ID and C1 status must agree. The name means reviewable claim, not completed human review. |
| `EvidenceCitation` | Full C4 evidence reference, C1 artifact/record locator, source URL/provenance/representation and retrieval observation ID; never a reviewer assertion |
| `SourceObservationSummary` | Existing C4 source identity and untouched native identifiers/components, every retained locator and relevant C5 monetary observations including original field/value |
| `ComparisonExplanation` | Narrow scope, preserved reasoning, compatibility, agreement limitation and C5 delta/tolerance if arithmetic was authorized |
| `AlternativeExplanation` | Catalog code, supported/ruled_out/unresolved/not_applicable state, rationale and citations; supported or ruled_out requires references |
| `EvidenceLimitation` | Explicit scope, coverage, freshness, history, source integrity/representation or exclusion limitation and relevant citations |
| `RecommendedVerificationAction` | Bounded next verification instruction with optional citations; no external action is taken |
| `ReviewPacketManifest` | Complete C5 run/C4 evidence context, selected claim IDs, available count, deterministic packet list and optional generation time |

C4 and C5 claim IDs are reused. Constructed packet IDs bind the claim, complete
substantive C5 input digest and packet-rule version; they are snapshot references,
not source-native identities or new financial events. Citation IDs distinguish
artifact content, retrieval observation, record locator and metadata. Different
retrievals remain distinct even when content repeats. Native PIID/agency/parent,
modification and transaction strings retain their original spelling; no names,
addresses or hashes supply identity.

Each claim has its own section: what is checked, what each source reports, exact
supporting and countervailing evidence, comparison prerequisites, observed
agreement, uncertainty and next verification steps. Identity-only sections never
claim financial verification. Financial sections preserve C5 statuses exactly:
even a compatible nonzero saved delta remains insufficient evidence when source
revision/refresh alignment is unknown. C6 cannot promote that finding to an
established discrepancy. C5's restrictions on explainable_difference and
unresolved_discrepancy remain intact. C4 identity discrepancies retain their
identity-only scope.

Candidate groups, rejected contexts, native identifiers, source date/type context
and monetary inventory remain visible. Monetary inventory is explicitly not a
comparison: cumulative/ceiling values are not substituted for action obligations.
Negative and zero obligations are displayed unchanged. Pagination, history,
query scope, source-wide completeness and freshness remain separate. Missing
URLs/update timestamps are unknown; unavailable/empty/partial responses retain
their exclusion limitations, never invented records or source-absence findings.
Required C3 provenance that cannot be validated causes explicit failure.

The catalog covers amendments/modifications, deobligations/corrections, reporting
delay, FY/lifetime scope, incremental/cumulative fields, agency/parent context,
missing history, pagination/API coverage, schema changes and precision. Plausible
causes remain unresolved. Only documented field-scope mismatch for a selected
compatible action pair is ruled out, narrowly, with citations. Exact calculation
rounding is not applicable when zero tolerance was used; upstream rounding
remains unknown. No causal explanation is automatically marked supported.

## Separate human review

C1's `ReviewEvent` and `ReviewState` remain unchanged: their legacy claim-ID and
state contracts differ from this requested workflow. The companion v1
`ReviewWorkflowEvent` uses existing C4/C5 claim IDs and snapshot packet bindings;
it is explicitly not a migration of C1 review records.

Every event records packet/claim/manifest IDs, a global sequence and previous
event hash, workflow state, reviewer-entered label, notes, explicit UTC time and
optional follow-up instructions. User labels are **not authenticated identities**.
Hashes are not cryptographic signatures. Events cannot overwrite automated
statuses or original evidence.

| Prior state | Allowed next states |
|---|---|
| No recorded event | pending_review |
| pending_review | pending_review, needs_more_evidence, reviewed |
| needs_more_evidence | needs_more_evidence, pending_review, reviewed |
| reviewed | reviewed, needs_more_evidence, closed |
| closed | none (terminal in v1) |

All events require nonblank bounded notes and a reviewer label; timestamps must
be UTC and nondecreasing. Closing means workflow closure, not financial agreement
or an allegation. With no event, HTML shows pending review explicitly labeled
as unrecorded. Follow-up citations must belong to the packet. Events use
exclusive, immutable `review-event-NNNNNN.json` files and a one-time
`review-context.json`, bound to the exact selected manifest. Changed, missing,
extra or partial files fail closed. Cooperative concurrent writers are rejected
with advisory directory locks. Torn temporary files are preserved for inspection,
not deleted or silently recovered. There is no authenticated multiuser service,
tip intake, automatic reopen, event-edit command or source-write action.

## Commands and output

Fully synthetic, without internet access:

```sh
mkdir -p data/raw/c3
.venv/bin/python -m src.collect_evidence --selection tests/fixtures/c4_selection.json --fixture tests/fixtures/c5_scenario.json --run-dir data/raw/c3/NEW_C6_SYNTHETIC --retries 0
# C3 exits 1 because FPDS query scope remains unknown; preserved records are usable.
.venv/bin/python -m src.build_review_packets --root data/raw/c3/NEW_C6_SYNTHETIC --output-dir reports/NEW_review_bundle
```

Optional `--identity-report reports/c4.json` and `--financial-report reports/c5.json`
consume existing reports outside evidence. Source evidence is still recomputed.
If a saved C5 report used custom C4 configuration, supply its matching C4 report
as well; configurations are not silently changed. `--claim-id ID` may be repeated
to select an exact subset. Default selection is all available identity and
financial claims, with a default limit of 100 and hard cap of 1,000. Exceeding
the bound fails rather than selecting the first claims. Available and selected
counts stay explicit, so a subset is not described as a census.

The **new** output directory contains:

- `packets.json`: canonical versioned manifest and packets, no raw response bodies;
- `review.html`: standalone accessible report with local CSS;
- `review-events.json`: separate snapshot of reviewer assertions, empty by default;
- `output-manifest.json`: byte hashes and versioned commit marker, published last.

Files are fsynced and atomically published without overwriting by exclusive
temporary-file/hard-link operations. The whole directory is **not** a single
atomic transaction. Failed/interrupting builds may leave a partial new directory;
without the final commit marker it is not a complete bundle. Use a new path for
another build; never delete preserved evidence to retry. Output readback checks
all hashes, schemas, projections and re-rendered HTML. Existing output bundles,
evidence stores and review logs cannot contain nested output/log stores.

To append a separate human assertion (use a packet ID from packets.json):

```sh
.venv/bin/python -m src.review_events --root data/raw/c3/NEW_C6_SYNTHETIC --packet-bundle reports/NEW_review_bundle --review-dir reports/NEW_review_log --packet-id PACKET_ID --state pending_review --reviewer 'Reviewer-entered label' --note 'Check current source revisions.'
.venv/bin/python -m src.review_events --root data/raw/c3/NEW_C6_SYNTHETIC --packet-bundle reports/NEW_review_bundle --review-dir reports/NEW_review_log --packet-id PACKET_ID --state needs_more_evidence --reviewer 'Reviewer-entered label' --note 'Signed-date evidence is needed.'
.venv/bin/python -m src.build_review_packets --root data/raw/c3/NEW_C6_SYNTHETIC --output-dir reports/NEW_review_with_notes --review-dir reports/NEW_review_log
```

Appending revalidates the original bundle and source snapshot before writing
notes. Custom upstream report configurations can be supplied with the same
identity/financial report options. `--timestamp` accepts an explicit UTC event
time; otherwise actual append time is used, never a fabricated source time.
Repeat `--follow-up` for optional plain-text instructions. Rebuilding with history
must retain the same claim selection/input manifest; annotations are not silently
transferred between different snapshots or selections. Automated packet data and
substantive hashes remain unchanged by review notes; the sidecar/HTML reflect the
separate history. `--generation-time` adds only optional run metadata, excluded
from packet IDs and substantive hashes.

## Security and bounds

All untrusted text, identifiers, notes, monetary raw values and attributes are
HTML-escaped. No raw API body is embedded. There is no JavaScript, external CSS,
tracking pixel, remote image, font or iframe. A restrictive CSP permits only the
hash of the fixed local stylesheet. Reports have a language, headings, skip link,
table captions/headers, responsive layout, visible focus and disclosure sections.
Source hyperlinks require HTTPS, an exact official-host allowlist, no userinfo,
nonstandard port, controls or backslashes; unsupported URLs remain escaped text.
Links are never fetched during rendering. Clicking a link is an explicit user
action and can require internet access; linked availability/content is unverified.

Descriptor-relative reads/writes reject path traversal, symlinked ancestors,
nonregular/hard-linked input files and overwrites. Output is outside evidence;
review logs are also separate from immutable bundles. Root/file race checks and
advisory locks do not defend against a privileged actor coordinating all edits.

Defaults: 100 claims and 8 MiB total output. `--max-output-bytes` permits 1 KiB
through 32 MiB. HTML is bounded during generation, and exact total JSON/HTML/
history/commit bytes are checked before output creation. C5 snapshot input and
prior report limits are 16 MiB; projected packets have a 32 MiB aggregate cap.
C2–C5 limits remain in force. Review history is bounded to 1,000 events, 16 MiB
total input and 64 KiB per serialized event. Notes are at most 4,096 characters,
reviewer labels 128, with at most eight bounded follow-up instructions. Oversized
events are rejected before publication; no candidate/evidence list is silently
truncated. Metadata-only failures and unsupported schemas are explicit errors or
inherited exclusions as appropriate, never synthetic fallbacks.

Build exit codes: 0 means all selected saved claims are verified matches with no
excluded source artifacts; it does not mean human review or complete finances.
1 means unresolved/ambiguous claims, exclusions or no selected claims. 2 means
invalid evidence, stale reports, limits, state/storage or output. 130 means
interruption. Append returns 0 only after durable validated publication, 2 for
invalid transitions/storage/context and 130 for interruption. An interruption
after publication can leave a valid event; inspect the log before retrying.

POSIX/Linux/WSL filesystem support is required. Native Windows has no insecure
fallback. C1–C5 flags, reports, checkpoints, collection defaults and schemas remain
unchanged. No datasets, secrets, generated reports or temporary outputs are
committed. There are no accounts, public submissions, remote collaboration,
multi-agent workflows, authentication guarantees or C7 integration.

## Validation and remaining limitations

Deterministic synthetic tests cover existing statuses, negative/zero amounts,
ambiguous identifiers, unknown coverage, duplicate locators, stale/tampered
C4/C5 reports and source bytes, forged projections, explanation assertions,
review transitions/history/torn files/locking, markup and URL attacks, source
changes during projection/rendering, output limits, path/symlink restrictions,
commit-marker interruption, re-render validation and offline execution.
The full existing suite and offline smoke test plus Python 3.11/3.12 CI remain
required. Reused authored C5 source-shaped fixtures are synthetic, not datasets.

Unresolved limits from C4/C5 persist: parent-absence rules, historical encodings,
source version/refresh alignment, complete action histories and supported
financial scopes. Additional limitations are local reviewer labels without
authentication, no signed/tamper-proof audit authority, no full-directory atomic
publication, no cross-snapshot annotation migration, no native Windows secure
IO and no assurance about linked sites. No review state, absent source record or
plausible explanation implies wrongdoing or independent financial correctness.
