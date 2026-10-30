# Phase 4C6: offline coordinator rehearsal

This layer rehearses software operations using four **explicitly simulated
sessions**, never people. No recruitment, real enrollment, observed human consent,
accessibility compliance, financial authorization or production screening is
established. Actual human usability and throughput remain UNKNOWN.

Baseline main is `3f31c437bfe961a64725cf122366a79b4ebf97d7`, merged PR #20.
[Protocol v1](coordinator-rehearsal-protocol-v1.json) was committed in `66afa63`
before evaluation; canonical SHA-256
`c8e54d22a0b459cd0b2a6a9d586d0d527c7ebf5c1749b383c4e95fb940b8683f`.
It pins all earlier frozen protocols, the eight C5 documents and two historical
inventories. Criteria are not adjusted after observing outcomes.

## Governance checklist and scope

[Checklist v1](coordinator-checklist-v1.json) is an **unapproved specification**,
not completed consent, an institution's decision or an identity record.
`pending_checklist(study_protocol)` creates seven explicit UNKNOWN approvals.
`ApprovalRecord` and `CoordinatorChecklist` use strict stdlib dataclasses/enums and
schema-v1 JSON. They reject unknown fields/versions, unsupported scopes, missing or
contradictory metadata, copied scope references, invalid dates and fabricated
unknown-state metadata. Approval records are separately scoped to consent
documents, study authorization, storage, retention, deletion responsibilities,
participant eligibility and privacy/disclosure. The enclosing checklist binds the
exact study protocol, task set, frozen governance and document bundle.

The prospective gate requires every scope's distinct opaque administrative
reference to declare external approval, already effective and unexpired on the
explicit assessment date. Simulated approvals, rejected/UNKNOWN records, future
or expired approvals cannot pass. A successful administrative completeness check
**does not verify who approved, institutional authority, independent judgment,
participant eligibility, encryption, consent comprehension or voluntariness**.
No approvals were supplied or fabricated in this phase. All seven remain blockers.
A coordinator must independently check the out-of-band records and responsibilities
before considering real recruitment or enrollment. C6 intentionally has no actual
human enrollment command and never converts a checklist into C5 authorization.
Legacy opt-in C5 commands remain unchanged; they are not a bypass authorized by C6.

## Architecture and exact task plan

Six companion modules provide separate responsibilities:

- `coordinator_governance.py`: pinned preregistration, strict approval contracts,
  exact scope/date checks and a separate machine-readable governance assessment.
- `coordinator_accessibility.py`: optional linear safe terminal adapter and bounded
  software audit, reusing C5 decisions, prompts and session machinery.
- `coordinator_rehearsal.py`: deterministic clock and scripted API workflow with
  exact C5 `pilot-mixed-v1` selection, one task at a time, evidence inspection,
  proof acknowledgment, pause/resume, completion, withdrawal and invalidation.
- `coordinator_lifecycle.py`: dedicated private simulated-batch capture, local
  capability, append-only HMAC lifecycle journal, retirement and bounded deletion.
- `coordinator_reporting.py`: aggregate-only primary-checked deterministic JSON,
  Markdown and escaped static HTML, with stale/forged report rejection.
- `coordinator_review.py`: explicit opt-in offline commands. It opens no server,
  fetches no URL and does not load external credentials or contact anyone.

The exact mixed plan comprises the eleven valid frozen C4 authored controls plus
one exact preserved public task from the C5 plan. The original public inventory
must match `42a1abce2e6fa0eac26e751bfd2db5bea91eee42e7503db2cf114a6c142a49fd`;
no available alternative is silently substituted. Tampered citation controls stay
blocked. Source-native identifiers, values, unknowns, historical records and
original bytes remain unchanged. Every cited artifact is read and checked against
its supporting hash, while the existing C4 builder checks task/provenance/locator
scope. Hash verification establishes preserved local bytes, not remote authenticity.

Four simulated workflows produce one completed 12-task session, one withdrawn
after a response, one in progress after a response, and one invalidated. Expected
eligible responses: **13**; excluded withdrawn responses: **1**. The completed
session pauses with an abandoned presentation and resumes in a new authored clock
epoch. No elapsed pause duration is invented. All missing obligations are retained
and acknowledged. Accepting a narrow evidence claim cannot authorize arithmetic.

## Accessibility audit and bounded improvements

The optional adapter uses keyboard choices and Enter, `q` to save and `w` to
withdraw. It preserves a linear numbered order, provides plain-language decision
labels and instructions, has no cursor repositioning, requires no mouse or color,
and re-prompts after invalid choices without retaining raw input. It visibly
escapes terminal controls, embedded line breaks, bidi/format controls and Unicode
line separators rather than executing them or letting them forge screen content.
The underlying C5 interface and default behavior are unchanged.

Automated checks cover predictable labels/order, invalid input recovery,
pause/resume, no color-only cues and control injection. **Screen-reader compatibility,
standards compliance and actual accessibility remain untested** until independent
assistive-technology and human evaluation. Long JSON/source-field listings, verbose
citations, closed choices and visible control-case path names remain usability and
blinding limitations. Do not claim WCAG or other standards conformance.

## Managed retirement and deletion rehearsal

The only writable/deletable objects are an explicitly created private C6 workspace,
its captured simulated C5 `batch`, and captured `outputs` containing two identical
C5 reports. Capture requires the exact 12 logical slots, four simulated sessions,
preregistered state/counts and a real pause/resume history. Actual-human stores
are refused. Workspace and files are owner-only POSIX 0700/0600 outside Git and
existing managed evidence. A distinct local random coordinator capability gates
operations; it is not an external credential or person authentication.

Capture independently replays C5 primary evidence and reports under a shared C5
writer lock, then seals a private exact file/directory manifest and aggregate
snapshot. A context-bound, HMAC-sealed append-only lifecycle history uses exact
expected tips and nondecreasing explicit dates. Workspace inode/device binding
rejects a copied control store; copying is not interpreted as a new independent
study. This does not discover or revoke previously copied C5 stores.

States and interruption boundaries are explicit:

1. ACTIVE: captured bytes and namespaces must match exactly.
2. RETIRING: append RETIRE_BEGIN before renaming `batch` and `outputs` to their
   retired names. An interrupted rename remains visible; publishing is blocked.
   Explicit resume requires the same reason/date/tip and exact original bytes.
3. RETIRED: original resume and report paths no longer exist; previous C6 aggregate
   reports are stale. Captured event bytes are preserved without editing decisions.
4. DELETING: append DELETE_BEGIN before unlinking any file. Only manifest-bound
   exact surviving files/directories may be removed, without following symlinks.
   Changed/unexpected survivors, links, traversal and concurrent cooperative writers
   block continuation. Interrupted deletion cannot publish a complete report.
5. DELETED: append DELETE_COMMIT after local namespaces disappear, then remove the
   private deletion manifest. An interruption before manifest cleanup can be
   explicitly resumed. No private session paths/IDs or event histories remain in
   retained control data; only aggregate simulated observations, dates and digests.

The root and C5 writer locks exclude cooperating tools; files are accessed and
removed descriptor-relatively with no-follow checks. The tool does not accept an
arbitrary deletion target. It does not repair evidence, reconstruct missing events,
select a winner between conflicting decisions or resume a retired session.
Incomplete atomic writes remain evidence of an interruption and fail closed.

A withdrawal-request rehearsal records the frozen prospective seven-day local
batch deletion deadline and thirty-day backup obligation. Expired raw retention
cannot be asserted before thirty days after closure. Earlier deletion of the
simulated aggregate is permitted; frozen approved-aggregate retention remains a
maximum ninety days, not a requirement to retain. Backup state remains UNKNOWN:
there is no inventory, deletion receipt or fabricated backup approval.

**Limits:** unlinking is not secure erasure. SSD behavior, snapshots, backups,
previous copies, same-account or privileged coherent rewriting and actual physical
access are outside local assurance. Local inode checks are not global revocation.
Legacy C5 direct commands are unchanged and do not universally enforce C6 retirement;
using a renamed/copied store directly is outside the approved workflow. This is a
simulated-data deletion rehearsal, not an approved real-participant erasure tool.
Independently review the real-data deletion design and policy before recruitment.

## Reports and reproducibility

Reports distinguish verified local software controls, captured simulated
observations, prospective approvals, human measurements and unknown outcomes.
They include task/evidence digests, state/counts, exclusion, governance blockers,
accessibility limits, lifecycle/deadline/backup status and separate source/financial/
production blockers. No labels, session IDs, capabilities, source-root paths,
private response histories, arbitrary notes or personal profiles enter aggregates.
HTML is static, escaped and has a restrictive no-network CSP.

Readback verifies the four-file report inventory, byte hashes and exact independent
primary projection; recomputing outer hashes cannot legitimize a changed summary.
Public source hashes and frozen documents are rechecked. While ACTIVE/RETIRED,
private bytes must match the sealed capture. After deletion, the captured aggregate
is expressly a **pre-deletion simulated snapshot**, not a claim that deleted private
histories can still be replayed. Deleted data are not silently reconstructed.
Retirement/deletion make earlier reports stale. Same inputs, explicit assessment
date and lifecycle state produce the same digest; wall-clock execution time,
capability values and private root location do not enter aggregate output.

CI never downloads the frozen public dataset. Its labeled synthetic surrogate
exercises the twelve-slot control machinery and real primary task rebuilds, with
one explicit test-only trust-boundary substitution for the public inventory check.
A separate local end-to-end completion run uses the exact frozen public inventory
without mocks; its digests/results are recorded in the PR. Missing real public
capture blocks the real command instead of falling back to the surrogate.

## Offline commands

Use fresh private directories outside Git. The C4 study and public capture must
already exist; these commands perform no collection.

```sh
python -m src.coordinator_review --rehearse \
  --study-root reports/SAVED_C4_STUDY \
  --public-root reports/p4a-live-24/award-000/research/evidence/selected \
  --store /tmp/NEW_C6_PRIVATE --as-of 2025-03-01 \
  --output /tmp/NEW_C6_ACTIVE_REPORT
```

The coordinator capability is `/tmp/NEW_C6_PRIVATE/coordinator.key`. Never print
or share its value. To inspect the current tip, use
`src.coordinator_lifecycle.tip(store, key_path)` locally; do not infer it from a
stale report. Retire then delete using each operation's exact current tip:

```sh
python -m src.coordinator_review --retire --store /tmp/NEW_C6_PRIVATE \
  --coordinator-key /tmp/NEW_C6_PRIVATE/coordinator.key \
  --expected-tip EXACT_CURRENT_TIP --reason WITHDRAWAL_REQUEST --as-of 2025-03-01
python -m src.coordinator_review --delete --store /tmp/NEW_C6_PRIVATE \
  --coordinator-key /tmp/NEW_C6_PRIVATE/coordinator.key \
  --expected-tip EXACT_NEW_TIP --as-of 2025-03-01
python -m src.coordinator_review --report --store /tmp/NEW_C6_PRIVATE \
  --coordinator-key /tmp/NEW_C6_PRIVATE/coordinator.key --as-of 2025-03-01 \
  --output /tmp/NEW_C6_DELETION_REPORT
```

The optional `accessible_terminal` adapter supports simulated sessions only and
should be exercised before sealing a capture. Captured batches are read-only
through the C6 CLI; it offers no enrollment or review mutation command. Direct
legacy writes change captured bytes and fail verification rather than silently
resealing. Optional `--checklist` reads a separately prepared private strict
administrative checklist; it never enables enrollment.
Exit 1 means limited research/preparation output; 2 invalid/blocked; 130 interruption.

## Validation, compatibility and next phase

Adversarial tests cover missing/forged/stale approvals, capabilities, replayed tips,
copied roots, tampered evidence/events, invalid JSON/versions, symlinks/hardlinks/
traversal, file/directory injection, cooperative locks, interrupted retirement and
deletion, expired retention, withdrawal exclusion, terminal injection, report
truncation/rehashed forgery and attempts to manufacture financial authority.
Full offline suites and explicit smoke tests run on Python 3.11 and 3.12.
Completion counts, exact head, report digests and CI links belong in the PR.

No existing production module, legacy flag/output/checkpoint schema, financial
eligibility or frozen readiness decision is changed. New companion modules change
the existing broad implementation fingerprint; old checkpoints require a new run
across implementation changes, never silent migration. No datasets, generated
reports, private study artifacts or capability values are committed.

Phase 4C7 should obtain independent governance/accessibility/deletion-design
inspection and resolve the seven approval scopes and storage/blinding concerns.
Only separately authorized voluntary participation could then establish human
usability or throughput evidence. Authenticated SAM validation, authoritative
revision/history/monetary proof and limited deployment each remain separate gates.
Independent exact-head full-diff/evidence/privacy inspection is also a condition
of this phase's merge policy; a self-report or green CI is not that inspection.
