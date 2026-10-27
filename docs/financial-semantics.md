# Phase 3C5: financial semantics and conservative reconciliation

Workstream C of [Issue #1](https://github.com/yvcohen-cs/federal-spending-auditor/issues/1).
Design boundary: a separate offline C3/C4 adapter, versioned typed monetary
observations, exact Decimal rules, and an opt-in report CLI. No C6 packets,
network collection, changes to legacy defaults, or misconduct inference.

## Research and conflicts identified before implementation

The [official USAspending transaction contract](https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/transactions.md)
(blob `246a2639368fd8908be232a25bbe25fb3e1c9720`) describes the transaction's
`federal_action_obligation` and nullable loan fields. It does not make that
amount a cumulative award value or an outlay.

The [Treasury Broker mapping](https://github.com/fedspendingtransparency/data-act-broker-backend/blob/bed939e6e51e5b31cac4ece7e3389a7464e6e78a/doc/fpds_elements.csv)
(blob `6093496ddca0806e277a57c91a5ba4a537291531`) maps:

- `federal_action_obligation` to `dollarValues/obligatedAmount`;
- `action_date` to `relevantContractDates/signedDate`;
- cumulative `total_obligated_amount` to `totalDollarValues/obligatedAmount`.

The [official FPDS data dictionary](https://www.fpds.gov/downloads/Version_1.5_specs/FPDS_DataDictionary_V1.5.pdf)
defines action obligations as this transaction's net obligation or deobligation,
including zero. [DoD reporting instructions](https://www.acquisition.gov/dfarspgi/pgi-204.606-reporting-data.)
specify U.S. dollars/cents and distinguish funded amounts from exercised and
potential contract values. These instructions and the Broker's direct field
mapping support a USD field-unit interpretation, not a claim that each payload
contains an explicit currency code. No currency conversion is supported.

The [FPDS dictionary's date definitions](https://www.fpds.gov/downloads/FPDS-DES-SDD-data_dictionary-DES_version1.0.pdf)
distinguish signed date from effective date. Publication/update/retrieval times
are not action dates. Source-specific refresh/revision guarantees remain unknown;
simultaneous retrieval would not establish synchronized source versions.

**Existing-code conflicts:** legacy reconciliation/C3 parsing uses effectiveDate
as action context and reads `totalDollarValues/totalObligatedAmount`. The
researched Broker paths instead use signedDate and cumulative obligatedAmount.
Legacy reconciliation also calculates a provisional award-total difference and
selects latest effective-dated modifications; reporting already warns that
definitions may differ. C5 does not inherit those financial claims or overwrite
old data. Its separate adapter reads the documented paths directly from the
preserved source bytes. Legacy code/output/checkpoints remain unchanged.

**Numeric representation conflict:** C2/C3/C4 JSON inspection uses ordinary
JSON floats for structural checks/content IDs. C5 must never derive money from
those parsed values. It reparses original JSON number tokens losslessly and
checks every retained C4 occurrence, including possible float-content-ID
collisions. Decimal arithmetic is isolated from the ambient Decimal context.

No new government API collection is needed or performed for this phase.
Historical public documentation/source mappings establish their inspected
semantics; they do not establish current API availability or complete history.

## Field-semantics and compatibility matrix

`field-semantics-v1` is a closed registry. Similar labels do not confer
compatibility. Original field paths and values always remain visible.

| Field/interpretation | Documented facts | C5 treatment | Observation/assumption boundary |
|---|---|---|---|
| USA transaction `federal_action_obligation` | Transaction obligation; Broker maps the FPDS action field | Incremental federal obligation, action scope, reporting USD | Not paid/outlay, award value, FY total or lifetime total |
| FPDS `dollarValues/obligatedAmount` | This transaction's net funds obligated/deobligated; zero allowed | Sole supported cross-source action-obligation counterpart | Exact action identity and compatible signed date required |
| FPDS `totalDollarValues/obligatedAmount` | Broker maps cumulative total dollars obligated | Cumulative award obligation, inventory only | No current-total comparison or historical completeness claim |
| FPDS `totalDollarValues/totalBaseAndExercisedOptionsValue` | Current exercised contract value can include unfunded value | Separate current/exercised contract-value measure, inventory only | Never substituted for federal obligation |
| FPDS `totalDollarValues/totalBaseAndAllOptionsValue` | Potential value includes unexercised options/ceilings | Separate potential contract-value measure, inventory only | Ceiling change is not inferred to be an obligation |
| FPDS `totalDollarValues/totalObligatedAmount` | Not the researched Broker cumulative field path | Unknown semantics; preserved, never substituted | Historical adapter alias is not asserted valid |
| Award amounts, FY/lifetime aggregates, outlays, loan fields, unknown XML fields | Outside this supported C3 contract-action pair | Unknown/unsupported monetary observations; no arithmetic | No automatic scope inference from a field name |
| USA `action_date` / FPDS `signedDate` | Broker maps these fields | Signed-action date, independent of retrieval/publication | Supports date-only or explicit midnight representation subset |
| FPDS effectiveDate / Atom updated / retrieval time | Distinct temporal definitions | No signed-date fallback or version-alignment inference | Identical retrieval times do not prove source synchronization |
| Field-unit currency | FPDS dictionary/DoD reporting plus direct Broker mapping support U.S. reporting dollars | `semantics.currency: USD`, separately labeled `documented_field_unit` | Not fabricated per-record currency metadata; explicit absent/blank/conflicting declarations stay separate |
| Precision | FPDS instructions specify dollars and cents | Exact Decimal comparison with zero tolerance | No published cross-source rounding rule verified; nonzero sub-cent values withheld |

Supported comparison: USA action obligation **versus** FPDS action obligation
for a C4-verified specific action, in the same signed-date scope, with known USD
field units and valid cent-exact values. Cumulative/incremental, current/potential,
obligation/outlay, award/action, fiscal-year/lifetime and different-modification
values are not interchangeable. No currency conversion, inflation adjustment,
unit scaling or field-label guessing is performed.

Research categories are deliberately separate:

- **Documented:** the official API contract, pinned Broker mapping, FPDS
  dictionary/reporting instructions and [Treasury fiscal-year definition](https://uscode.house.gov/view.xhtml?req=%28title%3A31+section%3A1102+edition%3Aprelim%29).
  Fiscal years start October 1 and end September 30. The derived action FY is
  context only; it never turns one action amount into an FY aggregate. Pre-October
  1976 dates retain unknown FY because older calendars/transitions need separate rules.
- **Saved observations:** C3 representations inspected during preceding work
  contain USA JSON numeric obligations and FPDS textual action/cumulative
  amounts and signed/effective dates. C5 uses the raw evidence paths, not an
  assumption that earlier parsed financial values retained exact tokens.
- **Synthetic fixture assumptions:** authored IDs, dates, USD values, midnight
  date representations, selected actions and invented revision sequences are
  test inputs. Their `synthetic_fixture_only` provenance remains in reports.
- **Unresolved/live limits:** no new live financial comparison or refresh timing
  was validated. Source mappings are not an assurance of every deployment,
  historical format, global uniqueness, complete history or current availability.

USAspending's [official update description](https://www.usaspending.gov/data/about-the-data-download.pdf)
describes staged publication and exceptions, including delayed DoD/USACE data.
It supports reporting lag as an ordinary possible explanation, not a per-record
freshness deadline or proof that a specific observed difference has that cause.
No fixed lag threshold is invented or used to dismiss differences.

## Schemas, exact values and claim boundaries

All companion schemas are version 1; `financial-v1` identifies the comparison
rules. Existing C1–C4 schemas/wire formats, models and golden fixtures do not
change. Unsupported versions fail without automatic migration. Models reuse C1
statuses/schema validation and C4 evidence/identity references.

| Model | Meaning |
|---|---|
| `MonetaryValue` | Original number token/decoded XML text or missing value; representation kind; valid/missing/invalid/unsupported state; exact fixed Decimal text and normalized comparison text only when valid |
| `FieldSemantics` | Versioned measure, incremental/cumulative basis, scope, reporting currency and documented/unknown distinction; observations must agree with the registry |
| `FinancialObservation` | C4 action-record reference, original field/value, semantics, evidence locator/provenance, signed-date raw/parsed values, effective currency interpretation and derived action FY |
| `FinancialComparison` | Narrow claim/identity IDs, status, field compatibility, all contributing observation IDs, exact values/difference if allowed, zero tolerance/rule version, explanation checks and next verification step |
| `ExplanationCheck` | Structured ordinary-explanation code and checked/unknown/possible/not-applicable assessment; a possible explanation is not an established cause |
| `FinancialLimits` / `FinancialRun` | Explicit bounds, complete C4 identity/coverage context, sorted observations/results, mandatory limitations and separate optional execution timestamp |

Numeric JSON tokens are read with a dedicated lossless parser from actual C3
body bytes; parsed C4 values are used for identity only. Tokens such as
`100.0100`, `1.2300e+2` and a cent beyond binary-float precision retain their exact
spelling. XML values retain decoded text, including leading/trailing decimal
zeros. The preserved artifact remains the authority for original byte syntax,
escaping and surrounding formatting; extracted XML text is not labeled a
byte-exact HTTP value. C3 representation/processing limitations stay attached.

JSON numeric strings are unsupported rather than silently coerced. XML accepts
a conservative plain signed decimal subset; currency symbols, grouping commas,
outer whitespace, exponent strings and unsupported attributes are withheld.
Although some FPDS input screens accept additional formats, universal XML
normalization rules were not established. Missing/null/empty elements are not
zero; invalid/nonfinite values cannot acquire a parsed monetary value.

Bounded Decimal conversion is exact. Fixed comparison text removes only
insignificant trailing fractional zeros and normalizes signed zero; original
precision/sign remains preserved. Scientific JSON notation is expanded only
within explicit bounds. No quantization or rounding occurs. Every arithmetic
operand must be bounded decimal text, including public helper calls; binary
floats, booleans and integers cannot enter the subtraction helper. A dedicated
256-digit Decimal context/traps makes arithmetic independent of ambient process
precision, rounding and exponent settings. Nonzero sub-cent precision does not
round into a match. Tolerance is exactly zero, with its basis serialized.

Constructed observation IDs refer to the C4 retrieval record, artifact, locator,
field, path and observation. Claim IDs bind the C4 action-identity claim, narrow
scope and rule version, excluding outcome, execution time and input ordering.
They identify observed snapshot claims, not independent payments or stable
real-world financial events. Substantive hashes exclude optional execution
timestamps, including nested C4 execution timestamps, but retain actual retrieval
provenance. Declared IDs, units, FY interpretations and outcomes are checked on
readback; outcomes are recomputed rather than trusted.

## Conservative decisions and ordinary explanations

The claim is **equality of compatible saved action-obligation observations**,
not correctness of current award finances. C4 award association alone is
insufficient. Specific action identity, field meaning, basis, signed-date scope,
currency and precision must all be supported before a delta can be calculated.

| Status | C5 v1 meaning |
|---|---|
| `verified_match` | Exact equality between compatible saved values with verified specific action identity; no assertion about current source revisions, global completeness or actual liability |
| `ambiguous_match` | Multiple plausible action identities; candidates retained without arithmetic |
| `insufficient_evidence` | Unsupported/missing/conflicting prerequisites, or unequal compatible observed values with unknown revision/refresh alignment |
| `unresolved_discrepancy` | Reserved and rejected for emission in v1: C3 provides no independently certified revision/refresh alignment supporting this stronger finding |
| `explainable_difference` | Reserved and rejected for emission in v1: possible benign explanations are not established causes, and no researched adjustment/rounding rule is applied |

For unequal compatible values, a serialized exact observed delta is useful
evidence, but is explicitly **not an established discrepancy**. Missing or
conflicting semantics prevent even that numerical comparison. Numerically equal
representations such as `1.2300` and `001.23` are an exact match; no money has been
adjusted to explain them away. Schema validation rejects unsupported stronger
statuses, invented tolerances and forged numerical outcomes.

Each result records checks for agency/parent/action identity, incremental versus
cumulative definitions, signed versus effective/publication/retrieval dates,
fiscal-year scope, precision, duplicate retrievals, missing modifications or
corrections, and reporting lag/source refresh. Unknown checks remain unknown.
Negative and zero obligations are normal supported observations; they are not
classified as misconduct or used to infer revision precedence.

Histories are never summed in v1. Individual modifications remain individual
claims; award ceilings/current values are separate inventory observations.
Pagination, action-history completeness, source-wide completeness, query scope
and freshness remain distinct C4 dimensions. Terminal pagination is not complete
history. Repeated rows/observations retain every locator and raw value without
double counting. Contradictory action versions remain ambiguous/insufficient.
If C4's older parsed-content IDs collapse distinct raw monetary tokens, C5
checks every occurrence and withholds a result instead of choosing one.

The next verification action is a concise instruction to check official action,
field, signed-date and revision/refresh evidence. It is not a C6 investigation
packet. There are no probability scores, accusations or inferred wrongdoing.

## Offline command, validation and portability

```sh
mkdir -p data/raw/c3
.venv/bin/python -m src.collect_evidence --selection tests/fixtures/c4_selection.json --fixture tests/fixtures/c5_scenario.json --run-dir data/raw/c3/NEW_C5_SYNTHETIC --retries 0
# C3 exits 1 because FPDS query scope is unknown; its saved records are usable.
.venv/bin/python -m src.reconcile_evidence --root data/raw/c3/NEW_C5_SYNTHETIC
.venv/bin/python -m src.match_evidence --root data/raw/c3/NEW_C5_SYNTHETIC --output reports/NEW_c4_identity.json
.venv/bin/python -m src.reconcile_evidence --root data/raw/c3/NEW_C5_SYNTHETIC --identity-report reports/NEW_c4_identity.json --output reports/NEW_c5_finances.json
```

The command never calls APIs or follows saved URLs. It consumes one flat C3
collection and recomputes C4 identity against preserved evidence. Optional prior
C4 output is securely read, schema/wrapper-checked and compared substantively to
the recomputed result, using its declared bounded matching configuration.
Stale/tampered identity results cannot authorize financial claims. C3 controls,
hashes, source request context and record locators are revalidated; all financial
bytes are independently reread and checked again after comparison. Unknown
namespaces, duplicate/compound monetary fields, linked/nonregular files and
concurrent changes fail closed. A coordinated rewrite of evidence plus hashes
is not prevented by hashes; neither source authenticity nor an atomic upstream
snapshot is established.

Stdout contains deterministic JSON, or `--output` exclusively creates a new
report outside evidence. A concise summary goes to stderr. Output parents must
already exist. Existing files, symlinks and evidence-directory outputs are
refused; source evidence is never written. `--execution-time` adds only actual
run time, not missing source metadata. No generated report/data is committed.

Exit 0 means nonempty observed-value claims all match with no excluded source
artifacts; it is not financial-history assurance. Exit 1 means uncertainty,
ambiguity, unequal values, exclusions or no claims. Exit 2 means invalid input,
limits, evidence or output. Exit 130 means interruption, with no trusted partial
report. C4-missing action counterparts remain insufficient; empty FPDS feeds
never become evidence of source absence.

Defaults are 5,000 financial observations and 20,000 charged comparison-work
units; hard caps are 20,000/100,000. The engine charges
`16 * (1 + left occurrences + right occurrences)` per subject, including schema
revalidation/check passes, and fails the whole run on exhaustion. C4's matching
bounds and C2's 8 MiB/file, 64 MiB/input and 4,096-entry bounds also apply. Raw
field text is capped at 4,096 characters, numeric text at 128, Decimal coefficient
at 80 digits, exponent from -18 to 60 and adjusted exponent at most 60, before
expansion. Limits never select a convenient partial candidate set.
Prior C4 reports have a separate 16 MiB input cap. Original field names/currency
declarations are capped at 256 characters and raw dates at 4,096; exceeding a
bound fails explicitly while the preserved evidence remains unchanged.

The secure filesystem workflow supports POSIX/Linux/WSL; native Windows has no
insecure fallback. Pure models/rules use only the standard library. Existing
Windows/legacy pipeline behavior, flags, reports, checkpoints and collection
defaults are unchanged. No old data is migrated or relabeled, and no C1–C4
production file is modified.

## Validation and unresolved questions

Offline tests cover numeric tokens, missing/malformed/nonfinite values, Decimal
context attacks, cents/sub-cents, unit/currency conflicts, signed-date and FY
boundaries, action/award identity prerequisites, alternate measures, revision
ambiguity, incomplete histories, duplicates/repeated observations, raw-token
collisions, stale identity reports, integrity mutations, safe IO, no network,
determinism and schema versions. The legacy full suite/smoke test and Python
3.11/3.12 CI remain required.

Open questions: deployment equivalence to pinned Broker mappings; historical
XML variants and accepted formatting; independently verifiable source revisions,
correction/deletion precedence and refresh alignment; a documented cross-source
rounding rule; authoritative parent-absence rules; complete action histories;
award-total and FY/lifetime/outlay/loan comparisons. These require separately
researched evidence and versioned rules. Until then v1 deliberately cannot emit
an established discrepancy or causally explain a monetary difference.
