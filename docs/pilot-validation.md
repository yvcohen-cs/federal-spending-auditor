# Phase 4A pilot protocol (v1)

This protocol is fixed before inspecting pilot results. This is a deliberate
diversity sample, never a probability sample or an estimate of misconduct.
Target 24 awards, hard cap 30. No anomaly flags or recipient characteristics
enter selection. Public oversight findings are optional context, not labels.

## Predeclared selection and measurement

The bounded USAspending frame consists of sorted Award-ID prefixes from eight
queries: FY2024/FY2025 crossed with contract award types A/B/C/D, at most 10 rows
per query and one page. Period filters describe the search endpoint's award
activity semantics, not necessarily original award dates. No population counts
or inclusion probabilities are established. Agencies/value bands/modifications
are observed diversity dimensions, not guaranteed coverage.

Eligible rows require an original nonblank generated_internal_id string and
source provenance. Deduplicate by that identifier; conflicting frame rows are
excluded rather than arbitrarily resolved. Preserve exclusions and frame hashes.
Within observed agency, type, query period, amount band and known/unknown
modification strata, rank by SHA-256 of seed + original generated identifier;
cycle canonical strata until the target or frame exhaustion. Empty quotas are
not evidence of absent contracts. Missing agency/value/modification stay unknown.
Selection order, seed, target, frame and rule versions are recorded before C7 runs.

The evaluation unit is a selected award slot; per-source rates use two expected
source tasks per slot (USAspending and FPDS), including unavailable/skipped tasks.
Award/action identity rates use C4 decisions of each claim kind separately,
not selected awards. Financial comparability uses C5 results with an authorized
numeric delta divided by all C5 results; exact agreement and unequal-value rates
use only those authorized numeric comparisons. Insufficient finance uses all C5
results. Evidence validation uses C2 entries, with verified/invalid/incomplete/
unsupported counts alongside the rate; record provenance uses verified C2 row
occurrences over all C2-enumerated row occurrences. C4 distinct record contents
are a separate count, never divided by physical row occurrences. Percentages are null when denominators are
zero. Counts are never population weights. Missing processing results are not
assumed zero anomalies or successful verification.

Historical completeness and source freshness remain unknown for every selected
slot unless a future version adds authoritative supporting criteria. Terminal
pagination and a recent retrieval do not establish either. Technical success,
source availability and evidentiary outcomes are reported separately.

## Implementation plan and boundaries

1. Add strict pilot config/frame/sample contracts and deterministic selection.
2. Add an opt-in pilot CLI that invokes existing C3/C4/C7 contracts per award,
   preserving append-only plans, inputs, partial work and explicit resume/retry.
3. Add deterministic count/rate reports, reason-code lanes and C6 packet links;
   use a small deterministic diverse outcome subset for human inspection.
4. Add authored synthetic controls and offline adversarial tests, then execute
   the controls twice and a bounded live subset if official access permits.
5. Document observed bottlenecks, run full regression/CI, open a draft PR.

Live collection is explicitly authorized only with --live. Search uses the
official fixed USAspending endpoint, existing bounded TLS/proxy-aware C3 transport,
no redirects, no automatic search retries and no alternative endpoint fallback.
At most eight frame requests plus three requests per award, 98 total for 30 slots;
per-award transaction discovery is one page, followed by at most one page per
source through C7. Native PIID/agency/parent context may be taken only from
unambiguous supported C4 parsing of preserved discovery transaction identifiers,
never by splitting award IDs or inferring names/addresses. Missing context stays
unknown and the discovery-only evidence can be evaluated without an FPDS request.
Empty feeds remain inconclusive; source query support and full scope are not
established by emptiness. No synthetic fallback is permitted in live mode.

Research lanes are **financial question**, **identity clarification**, and
**coverage/data quality**; reason codes are independent, without fraud scores,
weighted rankings or misconduct labels. Unequal saved values invite checks for
modifications, signed/effective dates, incremental/cumulative scope, source
revision and reporting lag. Deobligations, zero amounts and large award values
alone do not escalate a financial question. Unknown histories/freshness invite
more evidence, not an allegation. C6 remains the review architecture.

## Commands and artifacts

Install the existing requirements, then from the repository root on Linux/WSL:

```sh
mkdir -p reports
python -m src.pilot_pipeline --synthetic --run-dir reports/NEW_controls
python -m src.pilot_pipeline --live --target 24 --run-dir reports/NEW_public_pilot
```

The synthetic mode contains six known-answer cases from C7, rather than pretending
to be 24 real awards. Both completed modes exit 1: this pilot never establishes
broad evidentiary completeness. Exit 2 means no eligible selections or a processing
failure; 130 means interruption. A complete evaluation may still describe failed
or unavailable source tasks. No live access occurs without --live. The CLI has
no configurable endpoint, arbitrary URL or automatic network fallback.

The frame uses existing C3 HTTPTransport (one-MiB response bound, ten-second
connect/read inactivity timeouts, no redirects). Search has no automatic retries;
401/403/429, TLS/connection/timeouts or an uncertain reservation stop further
unsent frame requests. Other unsupported responses are retained as exclusions.
Retrieval times, request JSON and original application response bodies are
preserved separately; these are not byte-exact HTTP wire captures. A timeout is
an inactivity bound, not a whole-run deadline. Search fields follow the existing
Phase 3B contract. Live behavior must still be checked against saved responses.

Each selected award has at most one ten-record USA discovery page. C4 extracts
only an unambiguous supported native transaction context; its matching digest and
record references are preserved in bridge.json. With sufficient context, C7 live
collects a fresh bounded two-source collection; discovery bytes are not rewritten
or silently grafted into a C3 journal. Otherwise C7 processes the original
discovery collection offline and FPDS remains missing. There is no inference
from the display Award ID, agency display names or generated award-ID splitting.
Source search agency names are sampling labels only. No conflicting bridge is
arbitrarily chosen. Requests are paced both between stages and within C3.

Pilot directory contents:

| Artifact | Meaning |
|---|---|
| pilot-plan.json | Immutable config, implementation fingerprint, protocol and query plan |
| frame-NNN.request.json | Durable search-attempt reservation, written before access |
| frame-NNN.body / .response.json | Original application body and sanitized status/time/hash context |
| sample.json | Frozen sample, original frame rows, exclusions, strata and selection references |
| award-NNN/discovery | Immutable C3 USA discovery evidence (live only) |
| award-NNN/bridge.json | C4-supported source-native selection rationale (live only) |
| award-NNN/research | Existing C7 plan, commits, diagnostics, C3 evidence and C6 packets |
| pilot-report-NNN.json / .txt | Append-only deterministic evaluation and readable summary |

All generated contents remain ignored under reports/. Nothing is published.
The pilot JSON references C6 HTML paths and source records; it creates no competing
HTML renderer or reviewer-note system. Review candidates are automatically chosen
up to three diverse reason-code signatures in selected order. They are prompts
for manual inspection, not assertions that a human has verified the case.

## Metric definitions and interpretation

Every rate contains count, denominator and a two-decimal string percentage; a zero
denominator gives JSON null, never 0% or 100%. Rounding uses Decimal half-even;
no monetary tolerance or financial comparison is introduced here.

| Measurement | Numerator / denominator |
|---|---|
| Two-source nonempty collection | Slots with at least one returned row from each source / selected slots |
| Source retrieval success | Expected source tasks with at least one successfully parsed page / twice selected slots; partial pages count as retrieval success, not history completeness |
| HTTP response success | Expected source tasks with preserved complete 2xx response bytes / twice selected slots; unsupported parsing can still count here while failing technical processing |
| Row provenance sufficient | C2 verified observation row occurrences / all C2 enumerated row occurrences; failed responses can enumerate no rows and remain visible separately |
| Evidence integrity | Verified C2 entries / all C2 entries (controls, responses and metadata); incomplete/invalid entries do not pass |
| Award/action match | verified_match C4 claims of that kind / all emitted claims of that kind; neither is a unique-award coverage estimate |
| Financial comparability | C5 claims with authorized numeric delta / all emitted C5 claims; compatible field names without identity/date prerequisites do not qualify |
| Observed agreement / unequal values | Exact saved equalities / authorized numeric comparisons; nonzero deltas / that same denominator |
| Insufficient finance | insufficient_evidence C5 claims / all emitted C5 claims |
| Unknown history/freshness | Selected slots / selected slots in v1; no broad completeness claim is possible |
| Technical completion | C7 slots completing required stages / selected slots |

Separate counters retain ambiguous/insufficient/unresolved identity statuses,
observed row occurrences, per-case distinct record contents, observation contexts,
packets, evaluated slots and missing processing results. C4 content deduplication
and physical row enumeration intentionally use different units. C4 identities
are evaluated per collection, not merged across awards. Missing records are not
presumed nonexistent. No real-world fraudulent/nonfraudulent labels are supplied.

Resources include reserved search/C3 attempt slots (including discovery, retry or
uncertain reservations) and managed byte counts, excluding invocation reports.
Synthetic reservations are counted as fixture activity with zero live slots.
No execution clock enters the substantive digest. OS CPU, memory and elapsed time
are not instrumented; this resource report must not be read as those measurements.

## Recovery and integrity limits

```sh
python -m src.pilot_pipeline --synthetic --run-dir reports/EXISTING_controls --resume
# Only after inspecting failed/partial C7 stages, with unchanged original flags:
python -m src.pilot_pipeline --synthetic --run-dir reports/EXISTING_controls --resume --retry-failed
```

Resume requires the same config/code/query/sample. Replays saved search responses
after checking body digests; it never reissues an uncertain search reservation.
Failed completed searches are not retried automatically; use a new pilot for a
new frame. C3/C7 revalidate discovery, evidence, dependencies and stage commits.
Explicit retry uses C7's new attempt directories, preserving partial outputs.
A failed slot is reported separately rather than silently dropped from selection
or denominators; other slots may still finish. C7 invocation reports are excluded
from the pilot substantive inventory so validated successful resume is stable.

Files use exclusive append-only creation, fsync and cooperative POSIX locking,
descriptor-based bounded reads and symlink/hardlink rejection. Individual files
are published atomically; the whole pilot is not atomic, authenticated or signed.
Hashes do not defend against a privileged coordinated rewrite of all evidence and
declarations. An interrupted report pair or plan initialization can require a new
run; preserve partial work rather than repairing hashes or deleting files. Native
Windows is unsupported for this opt-in layer; legacy commands remain unchanged.

## Synthetic evaluation limits

Known-answer controls test observed equalities, one unequal compatible value that
remains insufficient, parent ambiguity, positive/negative/zero modifications,
FY/signed-date incompatibility and duplicate observations. Regression expectations
are fixed against these authored outcomes, including refusal to escalate ordinary
deobligations or incompatible fields. These checks measure contract behavior on
fixtures, not detection accuracy or false-positive prevalence in real contracts.

## Manual inspection during the live pilot

The initial three-slot bounded probe retrieved USAspending and FPDS records for
all three selections; it did not establish FPDS query-wide completeness. A new
24-slot run then used the unchanged eight-query selection protocol. The probe
and main pilot are separate observations, not independent random samples.

Three diverse outcomes in the main pilot were inspected through the preserved
C4/C5 JSON and existing C6 packet bundles (paths below are within the ignored run):

| Slot | Selection reason and retrieved evidence | Inspection / next action |
|---|---|---|
| 000 | HHS, type D, FY2024 query membership, under-100k band; six transaction rows from each source | C4 reported multiple plausible award candidates; C5 withheld monetary deltas despite compatible field semantics. Inspect parent-absence semantics and modification/action context before any numerical conclusion. |
| 002 | HUD, type C, FY2024 query membership, 1m-plus band; four transaction rows from each source | Eight identity claims and four exact observed financial claims passed. The saved obligations include zero and a negative amount, both ordinary action values; no financial escalation. Obtain source revision/history evidence before any broader award-finance statement. |
| 004 | Diverse selected award slot retained despite an unsupported response | USA discovery reached its ten-record/page bound. The FPDS body had an official-host next link containing VERSION, which the existing allowlist rejects. C7 blocked downstream stages; no C6 packet was generated for this failed slot. Verify documented VERSION semantics and scope preservation before changing that allowlist. |

For slots 000/002, the review files are
award-NNN/research/artifacts/packets/attempt-000/selected/review.html, with source
locators/identifiers, matching rationale and monetary definitions in packets.json.
For slot 004, use the verify-stage evidence.json and preserved FPDS body. The
VERSION parameter was observed in these saved responses; this is not validation
of arbitrary parameter values, all FPDS feed versions or a universal API contract.
No unsupported next link was followed or access restriction bypassed.

These are authored inspection notes, not automated source facts, ground-truth
fraud labels, or a human certification of the entire sample. Generated per-case
review summaries likewise retain explicit uncertainty and next verification steps.

## Observed validation results and evaluation correction

The live run selected **24 awards** from **80 observed search rows / 53 eligible
unique IDs**, with 27 duplicate frame occurrences and no conflicting-ID exclusions.
It covered nine observed agency labels, all four queried contract types (A:6,
B:5, C:6, D:7), two query periods (2024:17, 2025:7), and three Award Amount bands
(under-100k:6, 100k–1m:11, 1m-plus:7). These bands describe the search Award Amount
field for selection, not contract ceilings, payments or action obligations.
Modification history was unknown at selection for all 24. Agency balance was
uneven: ten selections had the GAO agency label. This is an observed sampling
limitation, not a population distribution or an oversight finding.

The 24-slot run reserved **80 live request slots** (eight frame queries plus
three per award). A separate earlier three-slot probe used 17 slots. No live
requests were made by subsequent read-only re-evaluation. Generated evidence,
source selections, JSON/HTML reports and scratch outputs remain outside Git.

| Derived result | Count / denominator | Meaning |
|---|---|---|
| Complete 2xx source responses | 48/48 expected final source tasks | HTTP availability, not parsing or query-scope verification |
| Successfully parsed source tasks | 36/48 | Twelve FPDS responses were unsupported by the existing next-URL allowlist |
| C7 technical completion | 12/24 slots | Remaining twelve stopped before identity/finance/packets |
| Verified C2 entries | 156/168 (92.86%) | Twelve unsupported bodies; no assertion of byte tampering |
| C2 enumerated rows with provenance | 229/229 | Excludes unparsed FPDS bodies; not a rate for all real source records |
| Award association verified | 16/61 emitted claims (26.23%) | 45 other award claims were ambiguous |
| Action equivalence verified | 16/61 emitted claims (26.23%) | 45 other action claims were insufficient |
| Authorized numeric comparisons | 16/61 financial claims (26.23%) | Compatible field names alone do not authorize comparison |
| Exact saved agreements | 16/16 authorized comparisons | Selected supported subset only; no whole-award or current-finance assurance |
| Unequal comparable observations | 0/16 | No claim about unevaluated/insufficient cases |
| Insufficient financial claims | 45/61 (73.77%) | Unverified action identity prevents arithmetic |
| Unknown history and freshness | 24/24 slots, each dimension | Bounded retrieval and old award dates cannot establish either |
| C6 packets | 183 | Covers emitted identity/financial claims in twelve supported slots |

The first evaluator mistakenly dropped unsupported-response slots from its
evidence-quality denominator, showing 84/84 verified entries. Self-review fixed
this: all 24 slots now contribute their available C2/C3 measurements, while
unsupported bodies still cannot authorize matching or financial comparison.
Regression tests cover the distinction between 2xx retrieval, parsed pages,
evidence validation, processing completion and monetary authorization. A second
fix ensures explicit retry of an interrupted pilot can start previously unstarted
awards without passing an invalid C7 retry flag to a new child run.

### Re-evaluate saved evidence without live access

```sh
python -m src.evaluate_pilot --source reports/EXISTING_public_pilot --run-dir reports/NEW_evaluation
```

This command never calls collection or resumes C7 execution. It validates the
original sample, stored frame/body hashes, typed C7 manifests, available stage
commits and dependency semantics; then derives current evaluation metrics from
preserved evidence. C1–C7 contracts/rules must remain supported. It preserves
the source tree byte for byte and writes to a new directory. The original run's
execution fingerprint stays unchanged; the new evaluator fingerprint is recorded
separately. This is remeasurement of saved observations, not another retrieval or
permission to reuse C7 stages under changed execution code. Invalid/missing child
artifacts remain failed slots. Packet paths resolve beneath the source root,
whose physical location is in separate evaluation-source.json metadata.

## Recommended Phase 4B priorities

1. **Validate FPDS VERSION pagination semantics against authoritative documentation
   and bounded tests.** The observed allowlist block prevented twelve complete
   slot evaluations despite preserved 2xx bodies. Do not simply follow arbitrary
   next URLs or declare missing records from these failures.
2. **Resolve authoritative absent-parent and repeated-modification identity
   semantics.** Forty-five award claims were ambiguous; keep conservative refusal
   until supported rules and adversarial tests justify a narrower interpretation.
3. **Obtain revision/modification history and refresh evidence.** Current limits
   cannot justify lifetime totals or turn saved differences into current claims.
4. **Broaden and rebalance the frame.** Sorted prefixes, overlapping periods and
   the observed agency imbalance limit research coverage. Verify source counts
   and sampling support before proposing statistical inference.

Additional oversight sources, search/comparison UI and evidence-grounded AI
summarization could help later; this pilot provides stronger evidence for fixing
parsing, identity prerequisites and coverage first. No ML scoring is warranted.
