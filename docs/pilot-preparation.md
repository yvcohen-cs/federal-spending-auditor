# Phase 4C5: local pilot preparation, privacy and session controls

**No actual human study has been conducted.** This opt-in offline preparation
layer provides a small terminal workflow, strict private sessions and aggregate
research reports. Simulations are not actual reviewer usability, accuracy,
agreement or throughput evidence. No financial authority, frozen readiness
upgrade, large-scale screening, live API collection, external account or
misconduct classification is introduced.

Baseline: merged PR #19, main `e3d6fd41f286520f158c509d9bbaf42d1ae37f81`.
[Preparation protocol v1](pilot-preparation-protocol-v1.json) was preregistered in
**1e8966b** before the evaluation. Its canonical SHA-256 is
`364b3ff0166b964b064aae4c1e5ff200bba947127201425cc5ff697c538094ef`.
Original 4B4/4C1/4C2/4C3/4C4 protocols, workflow/research documents and historical
source inventories remain unchanged. New documents are pinned separately;
criteria/version changes require new preparation/batch authorization, not edits
after observing performance.

## Experience audit and requirements

C4 already preserves precise claims, source citations, returned counterevidence,
unknown dimensions and append-only evidence-quality assertions. Its technical
JSON/Markdown reports do not establish a usable one-task experience. Free-text
labels/notes can collect unnecessary personal information; event timestamps do
not measure task durations. C4 has no consented session/withdrawal aggregation
contract. These are preparation gaps, not findings about reviewers or recipients.

[Usability requirements v1](pilot-usability-requirements-v1.json) separates essential
controls from optional presentation improvements. Essential: one task at a time,
exact scope/rules/citations, observed fields versus interpretation, parent/history/
pagination/revision uncertainty, retained counterevidence, five decisions,
structured rationale/proof acknowledgment, explicit save/resume, no source writes,
privacy minimization and optional valid timing. A GUI, richer layout and reviewed
selective deletion are optional/separate designs. Actual accessibility and human
usability remain UNKNOWN.

## Minimal offline interface

`src/pilot_review.py` uses the terminal, not a browser server. It opens no listener,
requires no accounts/network and embeds no external assets/telemetry. It displays
one task with its exact claim/rule versions, read-only source-root location,
artifact hashes/representations/record locators, packet citations versus additional
returned context, source-native fields versus derived interpretations, separate
evidence dimensions and all missing proof obligations. It never treats a missing
parent, terminal page or accepting decision as completeness/financial authority.

The reviewer explicitly selects:

1. One of the existing five evidence-quality decisions.
2. A closed interpretation/reason code.
3. A principal uncertainty from the displayed missing-proof list.
4. An exact citation.
5. A bounded follow-up (required for more evidence/escalation).
6. Acknowledgment of **all** missing proof obligations.

The resulting C4 `DecisionRationale` is labeled as derived from those choices,
not invented prose or verified understanding. Arbitrary free text is not persisted.
Invalid raw input is discarded; only a fixed diagnostic code/counter is recorded.
This minimizes personal information while limiting nuanced explanations, an
explicit question for future usability evaluation. Terminal/source text is
canonicalized/escaped; no arbitrary link is fetched or source editor invoked.
Source paths can reveal authored case names: a coordinator must review neutral,
byte-identical read-only packaging/blinding before interpreting real reference
agreement. Fixed controls are not real-world correctness ground truth.

`q` saves/stops and `w` withdraws, without asking for a reason. Resume requires the
exact private capability, task order, protocol and preserved evidence. An abandoned
presentation is retained but re-presented after explicit resume; its elapsed time
across processes is never invented. Terminal sessions cannot resume; completion
requires every planned task response. Withdrawal is permitted after completion
and removes prior responses from aggregate performance denominators.

## Typed session architecture

- `pilot_session_models.py`: strict version-1 `StudyProtocol`, `StudySession`,
  `TaskPresentation`, `ReviewerResponse`, `SessionEvent`, `SessionSummary`, plus
  task binding/set, authorization, consent and clock contracts. Unknown fields,
  versions, contradictory counts/states and financial overrides fail closed.
- `pilot_taskset.py`: frozen source/task selection, existing C4 primary rebuilding,
  inventory pinning and preparation/governance version checks.
- `pilot_session_rules.py`: deterministic action/state/consent/clock replay,
  exact next-task and structured-response validation, timing classification and
  aggregation eligibility.
- `pilot_session_store.py`: owner-only POSIX storage, local coordinator/resume
  capabilities, immutable records and HMAC-sealed global receipts.
- `pilot_study_reporting.py`: aggregate-only deterministic JSON/Markdown/escaped
  static HTML, independent source/session revalidation and withdrawal exclusion.
- `pilot_review.py`: coordinator preparation/enrollment, terminal review,
  withdrawal/invalidation, reports and explicitly synthetic demo.

Session states are NOT_STARTED, IN_PROGRESS, COMPLETED, WITHDRAWN and INVALIDATED.
Enrollment is NOT_STARTED / NOT_REQUESTED, never fabricated consent. An explicit
protocol/governance-bound receipt must acknowledge purpose, voluntariness and
withdrawal before START. Timing needs a separate acknowledgment; declining timing can continue an
untimed session. Declining the study is terminal without responses. WITHDRAWN/INVALIDATED/NOT_STARTED cannot contribute
performance statistics. In-progress and completed eligible sessions remain
separate completion-state counts; individual recorded task responses do not imply
that an entire session completed.

Session IDs bind exact protocol/batch/task-set and an opaque pseudonym. Duplicate
labels/IDs are rejected within an environment. A new authorized batch needs an
explicit new batch ID; copied environments are the same batch, not independent
participants/cohorts. No global identity registry, identity-to-label mapping or
cross-batch person inference exists. Task IDs remain existing C4 constructed IDs;
source-native identifiers/leading zeros and evidence bytes are unchanged.

## Frozen task plan and prospective authorization

[Future pilot plan v1](pilot-future-plan-v1.json) is NOT CONDUCTED. It fixes the
11 valid C4 authored controls in preregistered order and, for a human pilot, adds
one exact preserved-public task from the frozen C4 audit inventory. The public
claim is selected by sorted claim ID with no replacement. The tampered-citation
control must be blocked before valid task presentation; unavailable-source tasks
retain their uncertainty. No source API lookup or unavailable-case substitution
is permitted. Actual human mode requires the mixed plan, an explicit batch ID and
separate exact `StudyAuthorization`; controls-only runs are simulations.

The only reference answer is ACCEPT_EVIDENCE for the authored verified-identity
narrow property. All other references, including public and ambiguous monetary/
revision tasks, are NOT_MEASURED. Reference agreement is not award correctness,
fraud detection, human accuracy or proof of understanding. Expected software
controls, source versions, selection and criteria are frozen before any real
responses; any change needs new preregistration/authorization/consent.

A human `StudyAuthorization` record is an explicit local administrative reference,
not an authentication claim or automatic approval. The owner must separately
approve/institutionally clear the study, voluntary recruitment and private
storage policy. The unfilled template has null/false fields and is intentionally
invalid. No tool recruits, contacts, signs for or invents a participant.

## Private storage and integrity

Raw environments and reports must be outside git worktrees and managed evidence/
output stores. Empty sandbox `.git` sentinels are not treated as actual worktrees;
real gitdir files/HEAD markers are rejected. Source evidence may remain in its
preserved location and is only read. Private directories are mode 0700, records
and capabilities 0600, owned by the current OS account. Symlinks, traversal,
nonregular/hard-linked records, unsafe permissions and nested source/output
locations fail closed. Approved encrypted storage is a coordinator requirement,
not something this prototype certifies.

A coordinator capability permits enrollment/aggregate access and explicit
invalidation. A per-session resume capability permits that session's writes and
voluntary withdrawal. Capabilities are newly generated local random write tokens,
not external credentials or authenticated participant identities. Their values
are never printed or placed in reports. Participant labels are strict opaque
P-hex tokens; simulations use a distinct SIM-hex namespace. Numeric-only IDs,
legal-name/contact formats and unknown identifying fields are rejected.

Records and global HMAC receipts are append-only under an exclusive cooperative
root lock. They bind exact session context, global receipt sequence, per-session
event order/tips, task set, consent and state. Response IDs and expected tips
reject stale/replayed submissions. Two-file publication is not a whole-directory
transaction: an interruption between event/context and receipt remains preserved
but unreadable as complete. No blind retry, silent repair or overwrite occurs.
Session suffix truncation is detected against the separate receipt chain; removal
of all matching suffixes/coherent privileged rewriting still needs an external
trusted tip/report inventory. Local hashes/HMACs establish neither source
server authenticity nor a real person's identity. Same-UID/privileged access is
outside this supervised local prototype's isolation guarantees.

Sources/task projections are independently rebuilt before environment creation,
resume/report verification; exact source hashes are pinned on writes. Changed
source evidence blocks responses/resumption/positive reports. Withdrawal or
coordinator invalidation remains possible without repairing source evidence.
Excluded-session-only reports make no positive current-source assertion.

Bounds: 4 sessions, 12 tasks, 256 events/session, 64 KiB/event and 32 MiB logical
private-store/report budget, plus existing C4/parser limits. Reader/recheck bounds
can be stricter. No participant/session records, keys, datasets or reports belong
in repository commits. Original production flags, outputs, checkpoints, C4 logs,
financial rules and frozen readiness protocols are untouched. The existing broad
source fingerprint changes naturally; older legacy checkpoints still require a
new run across implementation changes, never silent migration.

## Opt-in timing and aggregate reports

Timing has four explicit categories: OBSERVED_HUMAN, SIMULATED, NOT_MEASURED and
INVALID. Without timing, no per-event timestamp/monotonic/epoch values are retained.
A real terminal consent decline records no timing. Task timing starts only after
explicit consent/optional-timing acknowledgment. The recorder uses process-relative
monotonic values and opaque clock epochs, not persisted device uptime/identity.

Presentation-to-begin-response measures a reading/exposure interval;
begin-response-to-save measures structured response entry. Neither establishes
comprehension, correctness or actual capacity. Missing/invalid/cross-epoch clocks
produce no fabricated zero duration. Resume discards an abandoned presentation
interval and starts a new one. UTC/monotonic reordering and undeclared epoch changes
are rejected; sequence/receipt order remains available when timing is off.

Aggregate reporting separates software controls, synthetic observations, actual
human observations, unmeasured outcomes, and excluded withdrawn/invalidated
sessions. It reports attempted/completed tasks, more-evidence/escalation counts,
invalid submissions, explicit uncertainty and appropriate authored-reference
agreement with denominators. It produces no participant labels/session IDs,
individual event histories, rankings or personal performance profiles. Actual
human cells below two eligible sessions and timing cells below two measured
sessions are suppressed. Small samples remain potentially identifiable; no
anonymity or publication permission is inferred.

Reports independently recompute from primary sources and sealed session logs.
JSON/Markdown/static escaped HTML and an exact commit marker must agree. Rehashed
forged summaries, changed sources, missing logs and stale pre-withdrawal reports
fail closed. Output location, execution keys and private labels do not enter
substantive aggregate results; actual measured timing stays observed data.
Repeated report digests and final evaluation/CI counts are recorded in the PR.

## Commands

Use a new private directory outside git and existing managed stores. For example,
reuse a preserved C4 synthetic study created by the documented C4 command:

```sh
python -m src.pilot_review --demo --study-root reports/SAVED_C4_STUDY \
  --store /tmp/NEW_c5_simulation --output /tmp/NEW_c5_simulation_report
```

This creates four explicitly simulated sessions: one completed, one in progress,
one withdrawn after a response and one invalidated. The expected aggregate has
12 eligible simulated responses and one excluded withdrawn response. There are
no actual participants, consent or human performance measurements.

Prepare a controls-only manual simulation and enroll a synthetic label:

```sh
python -m src.pilot_review --prepare --study-root reports/SAVED_C4_STUDY \
  --store /tmp/NEW_c5_private --timing
python -m src.pilot_review --enroll --store /tmp/NEW_c5_private \
  --coordinator-key /tmp/NEW_c5_private/coordinator.key --pseudonym SIM-aaaaaaaa00000001
# Use only the returned session ID and private resume-key path, never key values.
python -m src.pilot_review --review --store /tmp/NEW_c5_private \
  --session-id EXACT_SESSION_ID --resume-key /tmp/NEW_c5_private/EXACT_SESSION_DIRECTORY/resume.key
python -m src.pilot_review --report --store /tmp/NEW_c5_private \
  --coordinator-key /tmp/NEW_c5_private/coordinator.key --output /tmp/NEW_c5_aggregate
```

Explicit `--withdraw` uses the session capability; `--invalidate` additionally
requires `--coordinator-key`. Terminal `q`/`w` provide save/withdraw controls.
A future human preparation additionally requires `--public-root` matching the
frozen audit inventory, `--kind OBSERVED_HUMAN`, a new `--batch-id`, approved
storage, and a separately supplied private `--authorization` file at enrollment.
Do not execute a human pilot under the current preparation authorization.
Preparing configuration does not recruit anyone or establish participant consent.

Exit 0 means successful local preparation/enrollment/explicit state action or
session completion; 1 a saved/limited research report, demo or voluntary stop;
2 invalid/blocked; 130 interruption. Success is never production authorization.
Programmatic report verification is `read_report(output, store, coordinator_key)`.
No existing CLI behavior or defaults change.

## Governance, evaluation and next phase

[Governance v1](pilot-governance-v1.md), [unfilled consent template](pilot-consent-template-v1.md),
[participant instructions](pilot-participant-instructions-v1.md), and
[unfilled authorization template](pilot-authorization-template-v1.json) specify
voluntariness, minimal data, permissions, access, consent, withdrawal, incomplete
sessions, disclosure restrictions and 7/30/90-day prospective deletion/retention
obligations. The prototype does not automate selective erasure or promise secure
backup deletion. Its proposed procedure retires/deletes the entire private batch;
that policy must be approved, or a separately reviewed selective-deletion design
must precede real participation. Source evidence is never deleted for this purpose.

Separate C5 readiness covers offline interface controls, task completeness,
traceability, consent preparedness, privacy, session integrity, decision replay,
simulations and unmeasured actual usability/throughput. No 4B4 readiness upgrade or
100/500/5,000-award screening is authorized.

Phase 4C6 should run a coordinator-only governance/accessibility/resume/deletion
exercise, resolve storage/blinding/authorization concerns, then, **only with
separate authorization and voluntary consent**, conduct the small pilot. Actual
usability, accuracy, agreement and throughput remain UNKNOWN/NOT_MEASURED now.
Approved SAM access/source-validation evidence, authoritative revision-conditioned
financial prerequisites, authentication/privacy assurance and any future limited
production deployment each remain separate unresolved gates.
