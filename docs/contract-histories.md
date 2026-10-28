# Phase 4B3: observed histories and revision-aware financial evidence

## Implementation plan (fixed before evaluation)

Start from main 8dba601, merged PR #13. Keep C1–C7 and Phase 4A/4B1/4B2
defaults unchanged. Add companion schema-v1 history contracts and history-v1
rules, a read-only bounded adapter over one or more preserved single-award C3
collections, deterministic reports and an explicit opt-in CLI. Preserve every
scope assessment; only verified in-scope records enter eligible history groups.
Retain conflicting versions as review candidates rather than selecting a winner.
Reuse C5 lossless parsing/Decimal operations and C6 citation, limitation, action
and safe-output primitives. Do not add a reviewer-note or workflow system.

Sequence: contracts/rules; immutable adapters/timelines; research reports and
synthetic controls; frozen-pilot evaluation; bounded live validation; adversarial
tests, full offline regression/CI and a draft PR. No historical totals, missing
action synthesis, source replacement or legacy behavior changes.

## Research log (accessed 2026-10-28)

- [Treasury transaction contract](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/transactions.md)
  describes the transaction-history endpoint, internal ID, action date,
  modification number and transaction obligation. It does not expose a verified
  cross-source revision certificate. IDs remain native strings, not guarantees
  of identity stability through corrections.
- [Treasury Broker mapping](https://github.com/fedspendingtransparency/data-act-broker-backend/blob/bed939e6e51e5b31cac4ece7e3389a7464e6e78a/doc/fpds_elements.csv)
  maps action obligation to dollarValues/obligatedAmount and action_date to
  signedDate. C5's separate cumulative/current/potential interpretations remain
  in force; cumulative totals and ceilings never substitute for action amounts.
- [FPDS correction help](https://www.fpds.gov/help/Correct_a_Transaction.htm)
  distinguishes correcting a finalized action from adding a modification.
  A correction is not assumed to create a new modification or preserve every ID.
- [DoD reporting instructions](https://www.acquisition.gov/dfarspgi/pgi-204.6-contract-reporting)
  describe transaction-number use for multiple reports and modifications.
  Transaction numbers are not a universal modification/revision sequence.
  [FPDS manual](https://www.fpds.gov/downloads/Manuals/FPDS-NG_User_Manual_V15.pdf)
  supports net action obligations, including deobligations. Signed, effective,
  publication and retrieval dates have distinct meanings.
- [FPDS schema changes](https://www.fpds.gov/downloads/FPDS-Specifications-Version15-Changes.pdf)
  document transactionInformation/createdDate and lastModifiedDate. The legacy
  [Atom specification](https://www.fpds.gov/wiki/index.php/Atom_Feed_Specifications)
  now redirects to SAM contracting; indexed historical examples are not current
  availability guarantees. Record update fields are preserved without assuming
  they certify a monetary revision, deletion precedence or cross-source sync.
- [Official SAM API](https://open.gsa.gov/api/contract-awards/) distinguishes
  dateSigned, periodOfPerformanceStartDate, transactionData created/modified/
  approved dates and version. publicDeltaDate can reflect last modification or
  reveal date, so it is not an action date or a common revision token. Its
  documented version field is not assumed to be a cross-source revision key.
  Existing 4B2 contractId-only captures cannot supply missing temporal/financial
  sections. No new SAM mappings, credentials or requests are introduced here.
- [SAM transition page](https://sam.gov/contracting) reports legacy ezSearch
  retirement and planned Atom retirement. Endpoint behavior must be observed
  separately from historical documentation. Source restrictions remain binding.

No authoritative rule establishing complete contract history, universal action
ordering, a cross-source revision identity, or per-record freshness was found for
this supported subset. A terminal page, empty result, recent retrieval, identical
amount or identical source timestamp cannot establish those facts.

## Rule boundaries

Production alignment can recognize the same preserved record occurrence, distinct
declared update markers within the same source, different actions, insufficient
identity, unsupported temporal semantics, or unknown revision relationships.
Repeated content is a duplicate observation, not proof of independent revision
alignment. Different update markers describe different declared reporting states;
they do not establish correction causality or a latest authoritative winner.
All live cross-source revision relationships remain unknown until a positively
supported source-specific rule exists.

Synthetic fixtures may contain a fictional history-control-v1 revision token.
This is an authored known-answer control, not a government field mapping. The
adapter recognizes it only in explicitly synthetic C3 evidence, reports its
synthetic basis, and refuses to promote it into live semantics. It tests exact
agreement and unequal comparable amounts without authorizing real claims.

Financial comparisons additionally require verified scope, complete exact action
identity, compatible C5 field semantics, signed dates, currency and cent-exact
values. Deltas use C5 exact Decimal arithmetic and zero tolerance. Negative and
zero obligations are ordinary supported values. There are no history sums or
inferred missing modifications. A stricter revision-aware result does not rewrite
the narrower existing C5 saved-value equality claim.

## Versioned contracts and reconstruction

All companion wire schemas require explicit schema_type/schema_version=1;
history-v1 and history-metrics-v1 identify rules and measurements separately.
Unknown versions/fields and contradictory computed IDs/statuses are rejected.
There is no automatic migration of old evidence or reports.

| Contract | Preserved facts and validation |
|---|---|
| ContractHistoryScope | Exact 4B2 native request; no action filter that could hide modifications; supported USA/FPDS namespace only |
| ContractActionObservation | One scope occurrence, input manifest, C4 evidence, native components, money contexts, temporal evidence and journal position |
| ModificationIdentity | Exact modification/transaction strings and original JSON representations; neither is a fabricated sequence number |
| FinancialObservationContext | Existing C5 MonetaryValue/FieldSemantics, original tokens, dates, currency and evidence; no new amount mappings |
| SourceRevisionEvidence | Source-declared update markers, separately labeled fictional control token when present; no live revision certificate |
| FreshnessAssessment | HTTP retrieval time, distinct typed temporal fields and unknown content freshness; UTC is not assigned to local source times |
| HistoryCoverageAssessment | Per-input/source pagination, observed eligible action count, unknown history/source-wide completeness and no authoritative gap rule |
| RevisionAlignmentDecision | Both observations, six alignment outcomes, deterministic rationale and rule version |
| HistoricalFinancialComparison | Exact compared fields, alignment, narrow outcome, reasons and an authorized Decimal delta or null |
| HistoryVerificationRun | Every input scope assessment exactly once, complete bounded comparisons, coverage and separate optional execution timestamp |

TemporalField retains original JSON and a supported parsed representation.
Malformed/non-string dates stay explicit unsupported observations. XML extracted
text is decoded text, not a byte-exact token; source body bytes remain authoritative.
HTTP Last-Modified, when present, is response metadata, not an action revision.
Equivalent time-zone spellings do not create different reporting states; local
times with unknown zones are not compared to zoned times as known revisions.

The adapter revalidates C2/C3 and 4B2 contracts, pins all source inventories before
work, reparses C5 money from original JSON numeric tokens or XML text, and rechecks
all files/inventories afterward. It never writes source directories. Hashes detect
changes relative to declarations; a coordinated rewrite of bytes and declarations
is not authenticated by these checks. Saved reports are projections, never inputs
that can authorize new primary-evidence claims.

Only verified_in_scope occurrences with complete action components enter eligible
action groups. All others remain in the report, including legacy scope cases
where unknown namespaces appear as insufficient identity. Additional history
issues expose unsupported temporal containers without changing 4B2 semantics.
Within-input contradictory native versions retain 4B2's conservative exclusion.
Across snapshots, conflicting observations under the same fictional revision
block comparisons; no convenient version is selected. Identical retrieval rows
retain every locator and observation, and do not become independent corroboration.

Timeline display order is source, parsed HTTP retrieval instant, then deterministic
journal/locator ties. It is not signed/effective-date chronology or authoritative
modification ordering. No base action is synthesized when modification 0 is absent.
No gaps are inferred from alphanumeric modification numbers or transaction numbers.

## Reports, commands and recovery

```sh
python -m src.history_evidence --demo --run-dir reports/NEW_history_demo
python -m src.history_evidence --root data/raw/ONE_C3_AWARD --request reports/native-request.json --run-dir reports/NEW_history
# Repeat --root for up to eight saved snapshots of the same native award context.
python -m src.history_pilot --root reports/ORIGINAL_FROZEN_PILOT --run-dir reports/NEW_pilot_histories
# One previously studied C3 award; at most TWO HTTP requests total, no retries:
python -m src.history_evidence --live --root data/raw/PREVIOUS_C3_AWARD --request reports/native-request.json --run-dir reports/NEW_live_history
```

Requests use the existing ScopeRequest schema from [4B2](identity-scope.md).
Every output directory must be new with an existing parent. Reports cannot be
written inside source evidence. Linux/POSIX secure file handling, exclusive atomic
files and commit markers reuse C6/PilotStore primitives. A completed report bundle
contains history.json, history.txt, history.html, pilot-plan.json and
history-commit.json. HTML escapes all source text and contains no scripts, dynamic
URLs or external assets. C6 EvidenceCitation, EvidenceLimitation and
RecommendedVerificationAction types provide the read-only historical supplement.
C6 packet schemas, reviewer events, authentication limitations and workflows remain
unchanged; there is no competing note system or automatic reviewer assertion.

Reports include original and parsed values, requested identity, source timeline,
coverage/freshness, alignment and withheld reasons, contradictions, citations,
unresolved questions and next research actions. --execution-time adds actual run
time outside substantive output. Deterministic digests retain real source retrieval
provenance while excluding execution metadata. Older C5 equality claims keep their
original meaning; the new revision-conditioned claim is deliberately stricter.

Completed commands exit 1 because history/freshness remain unknown; invalid
input/storage exits 2 and interruption 130. There is no automatic resume/reissue.
Uncertain pending C3 journals must first be resolved through existing C3 recovery;
B3 refuses them and does not edit checkpoints. Partial report directories remain
preserved and lack a valid final commit; use a new destination. Live reservations
and responses remain append-only through C3. The live path stops after an error,
unsupported schema/temporal evidence or a known record-scope conflict. It does not
follow alternate endpoints or obtain SAM credentials.

Limits: eight roots, 1,000 occurrences, 32 monetary fields per record, 10,000 pair
work units, 8 MiB serialized observation budget, 16 MiB estimated pair budget and
32 MiB report/output budget. C2/C3 input bounds also apply. Limits fail closed;
they do not select convenient partial candidate sets. Oversized/uninterpretable
record financial fields remain unsupported with raw source evidence preserved.

## Measurement definitions

history-metrics-v1 and history-pilot-v1 leave all Phase 4A/4B1/4B2 baseline reports
and definitions unchanged. Counts distinguish returned row occurrences, distinct
source/content pairs, retrieval observations, eligible native action identities
and modifications. Duplicate occurrences are occurrences minus distinct content
pairs, not inferred duplicate real-world actions. Declared update states count
distinct source/native-action/field/raw-marker tuples; incomplete native keys stay
separate by observation. These tokens are not certified source revisions.

Financial units are bounded observed record pairs, including repeated retrieval
and same-source pairs. Multiple transactions remain separate action keys; repeated
observations can produce multiple pair statements. This is not a count of globally
unique transactions, independent corroboration, or contract-wide payments. Rates
use explicit pair denominators; zero denominators produce null. Scope-uncertain,
revision-unknown, different reporting states, incompatible scope and missing
counterparts are separate outcomes. Withheld reasons are prerequisites, not causal
estimates of how many legacy C5 claims would otherwise have passed.

Frozen-pilot aggregation uses all selected slots as its denominator, including
unsupported/unavailable slots. Action/modification counts sum distinct keys within
each frozen slot, not global unique actions. Freshness counts use occurrences;
historical coverage uses per-input/source assessments. Existing raw evidence and
earlier reports are checked unchanged; no network fallback or sample replacement
occurs during evaluation.

## Observations and validation

Baseline main: 933 offline tests plus the explicit offline pipeline smoke test
passed before implementation. Eighty-two new offline cases exercise all 18
known-answer scenarios, strict schema readback, exact raw amounts beyond binary
float precision, sub-cent refusal, cross-snapshot contradictions, misleading
timestamps/zones, output escaping/commits, interruption, safe recovery boundaries,
bounded transport controls and frozen-pilot immutability. The entire pytest suite
forbids real HTTP through its existing autouse fixture. Final full-suite and Python
3.11/3.12 CI results are recorded in the draft PR.

Two final 18-case synthetic runs produced equal demonstration digest:
`d76f2aa0af0b54725ce56782a8b706256f24cb150958bef34c00d7ce235bff37`.
These are fictional known-answer controls, not live revision verification.

The original preserved 24-slot Phase 4A sample was evaluated offline without
rewriting its evidence, replacing slots or recomputing old metric definitions.
All 24 slots were evaluable. There were 349 record occurrences; 12 slots had
eligible observed action timelines, with 93 distinct native action keys and 93
distinct modifications summed within slots. There were zero repeated-content
occurrences, and 181 distinct declared update tokens under the definition above.
Of 331 observed pair statements: 18 were revision-unknown, 238 scope-uncertain,
and 75 lacked sufficient eligible counterpart/history evidence. None authorized
arithmetic. All 349 content-freshness assessments and 48 input/source history
assessments remained unknown. These are descriptive convenience-sample results,
not population estimates. Final pilot evaluation digest:
`8c0b83d33db5a4283bc068f4e5a43a612e77a87a1389aaddf290a9b2d7faccce`.

Saved Phase 4B2 queries were also reevaluated without collection: the known-parent
query retained four eligible action pairs but withheld all four for revision
uncertainty; the conflicting-context query retained ten eligible USA actions
without supported counterpart comparisons; the unknown-parent FPDS-only query
retained 30 scope-uncertain occurrences. Earlier scope and financial reports were
left unchanged.

On 2026-10-28, the explicit live path queried one previously studied native award
with **two actual HTTP requests total**: one USAspending and one FPDS, no retries,
redirect following, alternative endpoints or SAM access. Each preserved response
contained four rows; all eight occurrences verified in scope, representing four
native actions/modifications. Preserved fields included USA action_date, FPDS
signedDate/effectiveDate and transactionInformation createdDate, approvedDate and
lastModifiedDate. Four declared update tokens did not establish common revisions.
All four new revision-conditioned comparisons were withheld. Pagination could be
assessed for these bounded responses; all content freshness and historical
completeness remained unknown. No source/schema change required stopping this run.
Final saved-response analysis digest:
`53469b08053dbec8c122d18a4ceca3ea8aa40026fc4a33db44268480fbd75f61`.
All later checks reused saved responses; no further requests were made.

The existing C5 four saved-value equalities remain unchanged as narrower legacy
claims. The new layer authorizes zero new real-world revision-conditioned numeric
comparisons. This is stronger prerequisite accounting, not an increase in anomaly
detection. No downloaded responses, generated reports or credentials are committed.

## Remaining questions and Phase 4B4 recommendations

Establish primary-source revision lineage and correction/deletion visibility before
adding a production cross-source alignment rule. Research whether identifiers can
change under corrections and require explicit linkage rather than joining by money,
names or timestamps. Validate authorized SAM temporal/financial sections and the
meaning of transactionData.version, without assuming it is a revision certificate.
Resolve documented SAM pagination ambiguity and positive parent-absence rules.
Obtain source-specific criteria for historical coverage and content freshness,
including restricted/revealed data and publication delays; do not invent a fixed
staleness threshold. A future typed C6 historical-supplement binding could reuse
the existing reviewer workflow without broadening old packet claims. No such
Phase 4B4 work, aggregate financial totals or new matching heuristics is implemented.
