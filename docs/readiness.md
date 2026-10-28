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
