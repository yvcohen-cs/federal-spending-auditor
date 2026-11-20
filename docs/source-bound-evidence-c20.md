# Phase 4C20: source-bound evidence progress

## Scope and reproducibility

Starting main: `4062f5a46a158301a1f0143d0e8acb8ee3568e48` (merged PR #34).
The preregistered [protocol](source-bound-evidence-protocol-v1.json) binds the original
1,570 requirement identifiers, six previously resolved real-source requirements,
1,564 unresolved requirements, the prior package, and 75 frozen documents (the
previously frozen 72 plus C19's three documents). Baseline C19 replay reproduces
the full report digest `903f641b648a1523bf7eb21c3314bbd3711c8b67f2a512910d3fdf51404fa475`
and package digest `5fe0cf51b1c829904a47ebceaf58d12401807dff224acccaa23704d14129901d`.

This opt-in tool reads preserved primary captures and documentation. It has no
network mode, credential lookup, financial calculation, production integration,
or participant operations. No datasets or generated evaluation reports belong
in Git. The source-semantics assessment is a curated account of observations,
not a replacement for the separately preserved primary evidence.

## Architecture and trust boundaries

`source_reference_semantics` validates exact metadata, URLs, entity hashes and
reviewed document bytes. It preserves original entity bytes, decodes only an
explicit supported charset (or ASCII-only bytes), and records visible-text
character spans separately from byte offsets. Conflicting/unknown encodings,
unreviewed document versions and unavailable captures cannot establish authority.
FPDS's captured HTML declares Windows-1252; decoding it as assumed UTF-8 would
lose evidence. These are HTTP entity bytes after content decoding, not wire-exact
HTTP responses. Publisher versions and historical applicability remain unknown.

`evidence_dependency_triage` defines a versioned typed `RequirementDependency`
and deterministically classifies the actual original proof obligations. It
retains source-native strings, original requirement JSON, original status,
case digest, exact missing dependencies, blocker and prospective acquisition
path. An unknown reason remains unsupported. `NOT_EVALUATED` entries remain
outside the requested native context rather than becoming discrepancies.
There are no identity inferences, confidence scores or inferred absence claims.

`source_bound_reporting` independently verifies the C19 package and every saved
evidence role before processing at most two separately registered C20 targets.
It reuses C17 planning and C14 qualification without changing either. Added
captures cannot rebind prior C17/C18/C19 acquisition roles. Qualification is
restricted to the exact original USA parent-primary requirement and native
context. Monetary preflight must report integer zero calculations and
comparisons, and false authorization. Five historical proof levels remain
separate; documentation cannot manufacture the missing effective rule.

C20 package support is explicit. C14–C19 recipes reject C20 fields, retain their
original defaults, file bounds and replay rules. C20 allows at most eight cases
with a verified C19 baseline. Each report and package is reconstructed from
primary inputs; re-signing a modified summary is insufficient. Static HTML
escapes untrusted content and disables network/script execution with CSP.
Execution time is not part of substantive report output. Source retrieval
timestamps remain preserved evidence, not freshness certificates.

## Historical finding and actual acquisitions

The official FPDS Glossary instructs: “Report the Modification number of the IDV
against which the order is placed.” Together with the selected FPDS reference,
this supports a documented source-native interpretation. It does **not** establish
that the unversioned guidance applies to the historical schema, a cross-source
parent-action mapping, retained revision coverage or an effective interval.
For child `00001`/`8600`, parent `DU100G16D01`/`8600`, modification `0`, transaction
`0`, levels 1–3 remain observed; level 4 is unsupported and level 5 insufficient.
Zero authoritative correction edges and zero historical intervals are admitted.
`oldContractId`, publication/update labels and matching modification labels do
not prove predecessor direction or historical authority.

The supported `SAM_GOV_API_KEY` setting was not configured; no credential search
or protected SAM request occurred. Four bounded public documentation GETs and
ten separately preregistered USAspending data requests were performed. Normal
TLS/proxy controls were retained, redirects/retries disabled, pacing one second,
timeout ten seconds, maximum one MiB per response and five data requests per case.

Two exact original parent-primary requirements resolved:

| Child / agency | Parent / agency | Original requirement suffix |
| --- | --- | --- |
| `0001` / `6800` | `EPW13006` / `6800` | `624256863be3731784140bc2e42581337b07051f950a8938169989b4297dff61` |
| `0001` / `1145` | `PC189003` / `1145` | `2831ff526539c5f2b251bd8fa633ffa38f391f0f671c28efb5f4618e9335843f` |

Both identifiers retain the prefix `evidence-resolution:v1:`. There are 18
child transaction observations and 18 parent-action observations: ten EPA and
eight Peace Corps parent actions. EPA's parent chain remains **nonterminal at
the budget cap**. Peace Corps's observed chain is terminal. Neither proves
historical/source-wide completeness, a common as-of snapshot, or independent
corroboration from duplicate observations. Parent-primary existence does not
require complete history under the unchanged original rule. Six prior plus two
new real resolutions leave **1,562** of the original 1,570 unresolved.

## Literal dependency assessment

The baseline 1,564 obligations partition as follows; the two current resolutions
remain visible in that baseline and are separately excluded from current totals.

| Missing dependency | Baseline count |
| --- | ---: |
| Parent-primary existence | 9 |
| Historical parent applicability | 110 |
| Source-native crosswalk | 125 |
| Revision/correction authority | 264 |
| History completeness | 132 |
| Financial semantics | 0 |
| Other unsupported dependencies | 924 |

Original statuses are 772 `INSUFFICIENT_EVIDENCE` and 792 `NOT_EVALUATED`.
The latter dominate the “other” group; the remaining 132 concern freshness.
All 88 currency and 88 monetary-semantics unresolved entries are outside the
requested native context. A zero financial group does **not** mean financial
eligibility. The report preserves a dimension/status cross-tab to make this
explicit. Six of the nine parent-primary obligations have an existing USA
query plan; three are FPDS-native and require validated source-native retrieval
or crosswalks. USA access cannot silently satisfy FPDS-native proof.

The deterministic next shortlist is child `0001`/`6800` → `EPC17008`/`6800`
(`140225679eaffd3a8c3192bcabb490404c3f084a840d681f27d4e61e50040cdf`)
and child `0001`/`6920` → `DTFAWA11A00237`/`6920`
(`ed25336764203d9fc45a4ece18775a7e5e14250bdaa8176526495587d73d8ba8`).
These are **not tested in the current context**. Original child query evidence
does not admit a bounded terminal contract; validate pagination and budget
before preregistering another acquisition. No further collection is performed
by the offline shortlist or implied by its ordering.

## Offline use

```sh
python -m src.source_bound_reporting --cases /path/cases.json --baseline-package /path/c19.zip --source-documents /path/documents --output /path/new-report
python -m src.source_bound_reporting --cases /path/cases.json --baseline-package /path/c19.zip --source-documents /path/documents --verify-report /path/new-report
python -m src.evidence_package --build-from /path/explicit-stage --phase C20 --output /path/c20.zip
python -m src.evidence_package --verify-package /path/c20.zip
```

Cases use the prior C19 case format, plus optional `c20_parent_capture` and
`c20_parent_history` roots. The package recipe is exactly
`{"schema_version":1,"cases":[...],"baseline_package":"baseline-package.zip"}`
with package-relative paths. Stage only the selected eight cases, their explicit
primary roots, unchanged C19 ZIP, four documentation body/metadata pairs from
`DOCUMENTS`, pinned original `usa-award-detail` body/metadata, and `report/`.
Never export a workspace. Recompute the staged report using staged absolute
roots before export. A full 24-case assessment covers all 1,564 baseline
obligations; the portable eight-case package explicitly covers included cases
only and must not be described as packaging the full cohort.

Fresh report directories contain JSON, Markdown, escaped static HTML, a plan
and a commitment. Compare both report digests and every output byte hash across
two independent writes. Export twice and require byte-identical ZIPs. Verify
again from primary inputs. The selected-case receipt and full-cohort digest
are intentionally different. Primary capture timestamps affect provenance;
wall-clock execution timestamps do not affect deterministic output.

## Validation and next phase

The 111 added deterministic tests cover native-context conflicts, wrong/reused
modification references, unsupported mappings/predecessors, document encoding,
unavailable/partial retrieval, nonterminal history, provenance/profile confusion,
frozen documents, prior role substitution, re-signed false reports/packages,
false finance flags, exact dependency partitions and offline-only behavior.
Existing package compatibility and pipeline tests remain mandatory. Run:

```sh
python -m pytest -q
python -m pytest -q -p no:cacheprovider tests/test_federal_spending_auditor.py::test_pipeline_writes_cleaned_flagged_and_summary_outputs
```

The completion receipt records exact final-head Python 3.11/3.12 CI outcomes,
repeated report/package digests and primary-replay results. Test results and
primary observation results are distinct; synthetic fixtures establish no real
source fact. No historical intervals, correction edges, financial calculations,
readiness upgrades, production screening or real participant operations result.

Recommended C21: first validate preserved child pagination contracts and a
bounded acquisition budget for the shortlist; then preregister exact original
requirements. Seek version-specific FPDS parent-reference applicability and
documented cross-source parent-action/revision binding, or legitimate SAM
authorization through supported configuration. Continue to report unresolved
history and financial obligations explicitly; do not manufacture completeness.
