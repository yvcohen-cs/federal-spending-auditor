# Phase 4B4: preregistered readiness and controlled-scale evaluation

## Design freeze, before new results

Main f0bc3e4 contains merged PR #14. The immutable v1 configuration is
[readiness-protocol-v1.json](readiness-protocol-v1.json). It records the exact
baseline implementation digest, original pilot implementation, frozen sample,
pilot plan and whole-source inventory hashes before evaluation. Source schemas
remain C1/C2/C4/C5/C6 schema-v1, C3 collector-v1/v2/v3 as explicitly supported,
record-scope-v1, history-v1 and history-metrics-v1. Existing historical metrics
remain separate. No threshold will be tuned after observing outcomes. Changing
criteria requires a new named protocol version, rationale and separate report.

Implement strict readiness contracts and pure categorical rules, then read-only
primary-evidence adapters, deterministic reports and engineering backlog, a
bounded holdout boundary, adversarial fixtures, frozen-pilot replay, current SAM
documentation review and optional holdout, full offline suite/CI and a draft PR.
No existing pipeline/collector defaults or checkpoint formats will change.

## Preregistered decision rules

PASS requires all observed requirements for that specific dimension and a nonzero
applicable denominator. A partial supported result is CONDITIONAL; known violated
criteria are FAIL; absent/unsupported evidence is UNKNOWN. NOT_APPLICABLE requires
an explicit mode-specific reason, never a convenient replacement for unknown.
There is no weighted score. Each measurement states its unit and denominator.

Twelve dimensions remain separate: operational integrity, source access/stability,
query precision, record identity, history coverage, revision alignment, financial
comparability, provenance, reproducibility, human review usability, security/bounds,
and source modernization. Terminal pages never establish complete history; source
timestamps and recent retrieval do not establish synchronization/freshness.

The ten non-negotiable controls are fixed: approved endpoints only; no credential
disclosure; bounded pagination; no evidence mutation; no fabricated native identity;
no unsupported financial claims; no silent checkpoint upgrades; no misleading
completeness; no automatic accusations; no independent-corroboration claim from
shared procurement lineage. A positively observed violation blocks every assessed
mode regardless of averages. Unknown control evidence does not become PASS.
Assertions concern the inspected execution/evidence, not universal certification.

| Proposed mode | Fixed requirements and purpose |
|---|---|
| Offline reanalysis | Operational integrity, provenance, reproducibility and security PASS; no known hard violation. Data-quality UNKNOWN is allowed because this mode emits uncertainty, never authorizes financial screening. Unknown controls yield NO-GO. |
| Bounded research, up to 30 | Offline prerequisites plus observed source access and some verified record context. Query/identity limitations, human acceptance and modernization can require CONDITIONAL GO with manual review, fixed budgets and mandatory scope/revision withholding. A successful distinct holdout is required; unavailable holdout gives NO-GO. |
| Validation, up to 100 | All preceding requirements, complete observed access/query/identity and traceability, distinct holdout with no known context conflicts, and demonstrated human acceptance. Unknown revision/history blocks financial screening even if research is technically possible. |
| Expanded screening, up to 500 | All twelve dimensions PASS, including positively supported history, common revisions, financial semantics/freshness and modernization. |
| Large screening, 5,000+ | Same dimensions plus independently established source scale entitlement/operational capacity and human-review throughput evidence. These are unverified in v1 and cannot be inferred from a 24-slot sample. |

These are proposed operating categories, not collection permission. The code must
never turn an assessment into a collector configuration or enlarge existing limits.
Conditional research explicitly forbids financial assurance, population estimates
and unsupervised case conclusions. Human review usability is at most CONDITIONAL
from automated traceability alone; no human acceptance benchmark is invented.

## Frozen holdout design

Only --live can issue requests. One official USAspending award-search request,
FY2023 activity, award type D, sorted Award ID ascending, first page of six.
Exclude original frozen generated IDs and conflicting duplicate frame IDs, then
choose the first three remaining native generated IDs in lexical order. Freeze
selection before discovery; no replacements for unavailable/ambiguous outcomes.
Record all overlap exclusions. This bounded prefix is not a probability sample.

At most one discovery transaction request per selected award, followed by one
USAspending and one FPDS request with supported native context: ten total HTTP
requests maximum, zero retries, one page per task, no redirects or alternative
endpoints. No SAM credentials are obtained. Stop all further source requests on
the first known scope conflict, unsupported schema, unsafe continuation, integrity
failure or source error/rate limit. Unknown parent context remains unknown and
cannot authorize a match. If the fixed frame has no new eligible awards, report
unavailable holdout rather than widening it. Source availability and data quality
are measured separately. No holdout outcome changes these criteria.

## SAM modernization review (official documentation, 2026-10-28)

[GSA API documentation](https://open.gsa.gov/api/contract-awards/) still requires
an account API key, with role/IP/account-specific access and quotas. The reviewed
production endpoint matches 4B2's fixed HTTPS search boundary. ContractId contains
PIID, subtier, parent and action fields; documented structural correspondence is
not independently validated cross-source identity. Last-modified, approval,
creation and reveal dates are distinct; transactionData.version is not established
as a common revision certificate. Deletion queries have a documented six-month
visibility boundary, not guaranteed complete contract history. Response limits
and offset examples remain ambiguous: the parameter says page index/default 0,
while examples include offset 25 with limit 5. No continuation rule is inferred.

[SAM transition guidance](https://sam.gov/fpds) describes ezSearch retirement and
replacement of Atom by this API. Documentation does not establish availability
of a specific endpoint/account in this environment. 4B2 remains a first-page,
contractId-only prototype; B4 neither replaces FPDS nor adds financial/history
mappings. No authenticated SAM observation is available in this protocol.
Human verification must establish authorized access, identity/parent definitions,
paging/response semantics, revision/deletion lineage and field accounting before
migration. Shared procurement lineage is never independent corroboration.

Prioritized migration prerequisites: (1) authorized account and bounded public
schema capture; (2) documented/observed pagination contract; (3) native identity
and parent/action checks; (4) temporal/revision/deletion and financial definitions;
(5) freshness/history criteria and scale entitlement; (6) human-reviewed parallel
validation before any separately approved replacement. No API key is requested,
printed or obtained automatically.

## Interfaces, measurement contracts and reproducibility

ReadinessProtocol, ReadinessAssessment, CohortAudit, SlotAudit, Measurement,
GateResult, ExpansionDecision, CauseOccurrence and ReadinessEvidenceRef are strict
schema-v1 dataclasses/enums. Unsupported fields/versions, mixed measurement units,
omitted status partitions, forged decisions and contradictory replay counts fail
validation. Live cohort hashes and criteria are locked to the preregistration;
synthetic-control profiles cannot certify a live cohort. Expected protocol hashes
remain separate from unavailable measured hashes, which stay null.

| Dimension | Primary measured unit and prerequisites |
|---|---|
| Operational integrity | Reconstructed selected slots / all selected slots; not legacy C7 technical completion |
| Access/API stability | Frozen verification HTTP successes plus all holdout HTTP successes, including frame/discovery; repeated bounded observation is not a general uptime guarantee |
| Query precision | Verified in-scope / enumerable occurrences; known context conflicts FAIL, unparsed totals remain incomplete |
| Record identity | Slots with at least one complete verified native action / selected slots; no claim of independent corroboration |
| Historical coverage | Positive historical completeness / source assessments, also requiring content-freshness support; terminal pages do not qualify |
| Revision alignment | Positively aligned observed pair results / all pair results; equal money/retrieval dates do not qualify |
| Financial comparability | Authorized revision-conditioned cross-source comparisons / all pair results; retains B3 withholding |
| Provenance | Revalidated source/control slots / all selected slots; hashes do not authenticate source truth |
| Reproducibility | Two equal substantive replays / selected slots, with unchanged source inventories |
| Human review usability | C6 citation/locator traceability / occurrences; at most CONDITIONAL without human acceptance testing |
| Security/bounds | Passed non-negotiable controls / all ten; one observed violation overrides averages |
| Modernization | UNKNOWN without authorized SAM validation; documentation is not authenticated API evidence |

Additional versioned measurements retain source parse tasks, completed collection
slots, returned row counts and their completeness, all five scope statuses,
eligible native action keys, modifications, financial withholding by reason,
source-history unknowns and freshness unknowns. Verification-only HTTP counts and
all-holdout HTTP counts are separately labeled; frame errors are never hidden by
successful record requests. Unrequested slots remain in the selected denominator.

Taxonomy units are distinct record contents, source tasks, artifacts or slots.
Multiple supported contributors share one subject occurrence; duplicate retrievals
do not create extra record-content causes. No cause count is summed into a count
of suspicious awards. Query imprecision means selection-relative native conflict,
not a proven server defect. Missing counterpart means absent from inspected
evidence, not absent in the world. Unverified freshness/history are unknown
criteria, not proven stale/incomplete sources.

Backlog ordering is fixed before holdout: a failed frame blocking new-cohort
discovery first, then distinct affected selected slots, estimated feasibility,
evidence-quality category and stable code ties. Feasibility is an explicit
engineering assumption; observational support is not certified upstream causality.
No weighted readiness/risk score is calculated.

Exact replay preserves body/manifest digests, reference multiplicity and source
times. Moving an identical frozen snapshot must preserve results: historical
absolute discovery descriptors are resolved only to the matching slot-local
discovery directory, never followed outside the current snapshot. Reordered raw
responses legitimately have different evidence hashes; a separate semantic digest
checks sorted native/raw-value/temporal observations and result counts without
discarding occurrence multiplicity. These are same-implementation replay checks,
not independent implementation or human validation.

Reports reuse full C6 EvidenceCitation objects and RecommendedVerificationAction.
JSON, Markdown and escaped offline HTML contain the evidence table, mode matrix,
separate frozen-only matrix, baseline references, backlog, assumptions, unknowns,
SAM migration prerequisites and human verification requirements. No notes or
reviewer assertions are created. Readiness outputs are projections, not trust
anchors that can replace revalidation of primary evidence.

```sh
python -m src.readiness --root reports/ORIGINAL_PILOT --run-dir reports/NEW_readiness
python -m src.readiness --live --root reports/ORIGINAL_PILOT --run-dir reports/NEW_holdout
python -m src.readiness --root reports/ORIGINAL_PILOT --holdout-root reports/NEW_holdout --run-dir reports/NEW_combined_readiness
```

Only the second command collects. It records the exact capture commit/source
fingerprint, frozen protocol and exclusions before requests. All destinations must
be new and outside evidence, with an existing parent. Source inventories and
implementation fingerprints are checked unchanged. Exclusive atomic files and
final commit markers reuse C6/PilotStore primitives. Interrupted captures retain
reservations and have no trusted final commit; there is no automatic resume,
retry or source/checkpoint upgrade. Outputs containing partial files are refused.
Exit 1 means a completed uncertainty-aware assessment/capture, 2 invalid input or
output, and 130 interruption. --execution-time affects execution metadata only.

Resource caps: 30 frozen/control slots, three holdout awards, ten holdout requests,
one page/task, zero retries, 1 MiB/HTTP response, 32 MiB/report outputs and bounded
primary-evidence readers. Existing C1–C7 and Phase 4A/4B1/4B2/4B3 CLI flags,
outputs, checkpoints and defaults remain unchanged. Larger mode categories are
not inputs accepted by any new collector.

## Observed evaluation and limitations

The frozen criteria file remains byte-identical to preregistration commit
1130ee3. Implementation hardening added explicit holdout-ledger schema/profile/
completeness checks and separated observed modification records from eligible
modifications; no gate threshold, holdout selection rule or budget was changed.
The original main baseline passed 1,015 offline tests and the explicit smoke test.
There are 86 new deterministic offline cases. Final full-suite/CI results and
replay digests are recorded in the draft PR, bound to the evaluated code commit.

The original 24 slots were evaluated using preserved evidence only. All 24 were
technically reanalyzed; all 48 source tasks parsed under the supported current
reader. Only 12/24 collection slots had terminal pagination for both sources,
which is separate from both technical completion and complete history. Of 349
enumerable verification occurrences: 111 were verified in scope, 88 out of scope,
150 ambiguous, zero insufficient and zero unsupported. There were 93 distinct
eligible action keys and 93 eligible modification strings summed within slots.
The B3 financial partition remains exactly 331 results: 238 scope-uncertain,
75 insufficient counterpart/history and 18 revision-unknown. No revision-conditioned
numeric comparison is authorized. Every history and freshness assessment remains
unknown. The whole original inventory was checked unchanged.

The controlled live holdout was captured by implementation commit 2a32241 on
2026-10-28 using the unchanged preregistered protocol. The one-page frame had six
rows, including two excluded original-cohort IDs. Three new generated IDs were
frozen before discovery; no selected slot was replaced. Ten requests total
(one frame, three discovery, six verification) all returned HTTP 200; no stop
condition triggered. These are source-native selection distinctions, not a
guarantee of globally stable real-world identity across corrections.

All six holdout verification tasks parsed, and all three bounded collection slots
reached terminal pages. Their 32 verification occurrences were **all ambiguous**
because parent context remained unknown; none was verified in scope or eligible
for action grouping. All 32 financial result units were withheld for scope
uncertainty. Terminal pages and known modification fields do not change this
conclusion. No history, freshness or cross-source revision assurance was obtained.
Frame and discovery evidence are preserved separately; dedicated verification
records are not double-counted with discovery rows in quality denominators.
All-request HTTP measurements explicitly include the frame and discovery calls.

| Dimension, combined inspected evidence | Result | Numerator / denominator |
|---|---|---|
| Operational reanalysis | PASS | 27/27 selected slots |
| Observed source access | PASS | 58/58 frozen verification + all holdout requests |
| Query precision | FAIL | 111/381 verified occurrences; 88 known conflicts |
| Eligible native action context | CONDITIONAL | 12/27 selected slots |
| Historical coverage and freshness support | UNKNOWN | 0/54 source-history assessments |
| Revision alignment | UNKNOWN | 0/363 pair-result units positively aligned |
| Revision-conditioned financial comparability | UNKNOWN | 0/363 authorized |
| Source provenance | PASS | 27/27 revalidated slots |
| Deterministic replay | PASS | 27/27 slots |
| Human review usability | CONDITIONAL | 381/381 traceable occurrences; acceptance unmeasured |
| Security/bounds | PASS | 10/10 controls in inspected evidence/execution |
| Modernization | UNKNOWN | No authenticated SAM verification |

The 363 pair-result units are the original 331 plus 32 holdout results; only 18
have the specific revision-unknown withholding reason. Others remain blocked by
scope or counterpart/history prerequisites. Do not relabel all 363 as established
same-action comparisons, all unknown revisions, or independent corroboration.

| Proposed mode | Preregistered result |
|---|---|
| Offline reanalysis | GO for inspected, immutable evidence and uncertainty reporting |
| Research up to 30 | CONDITIONAL GO: manual review, fixed budgets, mandatory scope/revision withholding; no financial assurance |
| Validation up to 100 | NO-GO |
| Screening up to 500 | NO-GO |
| Screening 5,000+ | NO-GO |

The bounded-research result allows unresolved evidence to remain a research
question. It does not certify the holdout's identities, approve additional
requests, or make this system ready for unsupervised financial screening.
No collector consumes these decisions or changes its limits. Frozen-only results
remain separately available: offline GO, every broader mode NO-GO without the
distinct holdout. The preregistered rules were not relaxed to obtain these results.

The principal uncertainty is missing authoritative history/freshness criteria,
then partial coverage and native parent/query context, missing counterparts and
revision lineage. The backlog reports distinct affected slots and subject units,
with feasibility explicitly estimated. Recommended next work is authoritative
parent/no-parent semantics and query-scope validation, a bounded authorized SAM
schema/pagination validation, and primary revision/correction/deletion lineage
before any financial scale-up. Larger-cohort permissions, human acceptance,
throughput and source-scale entitlements remain unverified. No downloaded data,
generated reports or credentials are committed; no legacy defaults are changed.
