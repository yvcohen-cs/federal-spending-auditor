# Phase 4C4: review workflow validation and operational evidence

This opt-in, entirely offline layer evaluates evidence traceability and review
workflow controls. It does not authorize production screening or change existing
collection, reconciliation, financial eligibility, review events or readiness.
No award or recipient is classified as fraudulent. An anomaly or a cross-source
disagreement is not an allegation of misconduct.

Baseline: merged PR #18, main `150a24f415394a88262c8c0c976ba5212cfbe825`.
The [preregistered protocol](review-validation-protocol-v1.json) was committed as
**8f540c6** before evaluation. Canonical SHA-256:
`499022ecd94bc5c0753ca3bacbddfa53659e498e0552bfc628fd6f829091fe8f`.
Its twelve controls, two scripted decision sequences and acceptance rules are
immutable in v1. The separate [existing-evidence audit plan](review-existing-evidence-plan-v1.json)
was committed as **fb85d56** before the preserved-public-evidence audit.

Frozen 4B4/4C1/4C2/4C3 protocols, the 4C3 documentation matrix, and original source
inventories remain byte-identical. No historical metric or readiness decision is
retroactively upgraded. No live requests, new credentials or network mode are
introduced. Simulations and preserved public evidence are evaluated separately.

## Audit findings and information needed by reviewers

Existing C6 packets already bind one exact C4/C5 claim to primary citations,
source-native identifiers, monetary inventory, ordinary alternative explanations,
limitations and next verification actions. Their generated summaries are exact
projections, and source bytes are independently checked. C6 workflow events are
append-only, source-separated assertions with context, sequence and time checks.

The audit identified these operational gaps:

| Reviewer question | Existing information / Phase 4C4 treatment |
|---|---|
| What exactly is claimed? | Original packet/claim ID, precise scope and existing automated result are retained; a saved value match is not full financial assurance. |
| Which primary source supports it? | Full C6 citations retain artifact path/hash/representation, record locator, request provenance, source URL where known and retrieval observation. No invented URL or source time. |
| What fields were observed? | Tasks expose exact native strings and field paths, original monetary lexemes, parent presence and temporal values separately from C4 interpretations. |
| What is unknown? | Claim, identity, parent, instrument, pagination, history, revision, money, financial authority and traceability are separate dimensions. Missing proof obligations cannot be removed. |
| Is identity/parent context established? | Existing C4 and experimental parent results remain distinct. A narrowly selected packet can omit a rejected candidate; tasks add separately labeled returned context rather than hiding counterevidence or changing the packet. |
| Is a financial comparison authorized? | Original C5 results are preserved. Review acceptance adds **no** permission for new arithmetic; history-conditioned authority remains insufficient/not evaluated. |
| Is the relevant revision established? | Existing history results/coverage remain visible; matching schema versions/times or accepting a packet proves no common revision. |
| Can evidence be reproduced? | Task creation, decision append/read and report write/read rebuild against primary source bytes; changed source snapshots invalidate prior bindings. |
| What could resolve uncertainty? | Structured rationale must acknowledge every missing obligation; unresolved/escalated decisions require a concrete follow-up. |
| What did the reviewer decide? | Evidence-quality decisions are separate from automated results and legacy workflow states; all contradictory assertions remain visible. |

Current C6 HTML is a future study's primary accessible packet view. The new static
reports are research/audit views and a worksheet, not proof of interface usability.
No actual reviewer accuracy, acceptance, efficiency or throughput has been measured.

## Versioned contracts and source boundaries

[Workflow specification v1](review-workflow-v1.json) is pinned by canonical hash
`cae0e8df3c73ac52f966c6eb233d485fd928c6c5884a0759377b2ff2f9b8549f`.
All new dataclasses/enums use explicit schema version 1; unsupported versions and
unknown fields fail closed. No automatic migration is performed.

- `review_validation_models.py`: typed `ReviewerTask`, `ReviewerTaskManifest`,
  `ReviewObservedField`, `ReviewDimension`, `DecisionRationale`,
  `ReviewerDecisionInput`, `ReviewerDecisionEvent`, evidence/decision/kind enums.
- `review_validation_tasks.py`: independently rebuilds C6, parent and history
  assessments from a single explicitly selected preserved C3 root; optional saved
  C6 bundles must exactly match the rebuilt source snapshot and claim selection.
- `review_validation_events.py`: append-only decision sidecars, existing C6
  envelope validation, frozen claim selections, independent decision chain and
  conservative all-history review-state projection.
- `review_validation_study.py`: author-generated source-shaped records, forced
  in-process fixture transport, two separately preregistered simulation sequences,
  immutable study inventory/commit and independent replay.
- `review_validation_reporting.py`: deterministic JSON, Markdown and escaped
  static HTML; source/log revalidation, operational assessment and commit readback.
- `review_validation.py`: separate opt-in demo, replay, source audit and explicit
  decision-input CLI. No network/live/credential option exists.

Constructed task IDs bind the original packet, primary snapshot and task rule;
they are not source-native or real-world identities. Snapshot manifests bind the
full financial/parent/history projections and exact source inventory. Task
creation is bounded to 100 tasks and one requested native award context. Source
files are read through descriptor-relative bounded readers; output never modifies
source. Sources and packets are not repaired to make an evaluation pass.

Task citation roles are explicit: `packet_citation_ids` identify the unchanged
original claim evidence; `context_citation_ids` add returned support/counterevidence
from independently validated parent/history readers. Their disjoint union must
match the task's full citation inventory. Additional context is not asserted to
be a verified match to the requested award. Missing, contradictory and unsupported
identity/parent fields remain so. Names, addresses, approximate dates and hashes
never infer real-world identity.

Monetary field observations retain raw lexemes as strings, with original paths;
the original packet also preserves C5 raw-kind/unit/interpretation metadata.
Canonical parsed JSON and derived context are labeled as such, never described as
byte-exact HTTP or wire captures. Original C3 artifact representations/provenance
remain unchanged. Retrieval time is not source freshness or revision time.

Evidence categories are **VERIFIED, CONFLICTING, INSUFFICIENT, UNSUPPORTED,
NOT_EVALUATED**, per dimension. They are not a confidence score. A positive
traceability assertion means checked local bytes/locators/provenance, not remote
source authenticity. A conflicting money dimension denotes existing unequal
saved C5 observations, not an established aligned-revision discrepancy.

## Decision protocol and append-only history

The only decisions are ACCEPT_EVIDENCE, REJECT_EVIDENCE, NEEDS_MORE_EVIDENCE,
NOT_APPLICABLE and ESCALATE_FOR_REVIEW. They concern evidence quality/interpretation,
not misconduct or financial authority. Each event requires:

- Exact task/snapshot/packet/claim references and rule versions.
- Interpretation, scope explanation and uncertainty as separate nonblank text.
- Known citation IDs and acknowledgment of **all** missing task proof obligations.
- Explicit reviewer-provided label, kind and UTC timestamp; no invented attribution.
- A concrete follow-up for evidence requests/escalation; optional otherwise.

Unreviewed task attribution/rationale/time remain null. Human labels are explicitly
self-reported and unauthenticated. Simulated labels must start `SIMULATED:` and
cannot be recorded as actual human assertions; human labels cannot impersonate a
simulation. The two modes cannot share one log. Actual self-reported events, if
later supplied, do not establish consent, participant identity or completed human
usability research.

Each decision wraps a legacy C6 `ReviewWorkflowEvent`. Its first event registers
`pending_review`; subsequent events use `reviewed` or `needs_more_evidence` under
unchanged C6 chain/context/time rules. It never closes an existing review. This
is a compatibility envelope, **not** the decision-derived review summary. New
structured decisions and their full returned-context follow-ups live in the
companion event; they are not silently converted into legacy C6 assertions or
written into a C6 log. The original C6 CLI/log format remains unchanged.

Global sequence, previous C6 event ID and previous companion decision ID bind both
histories. Exact duplicate submissions are rejected; distinct assertions remain
retained. Logs use exclusive `decision-NNNNNN.json` publication plus one-time
`review-context.json`, frozen task/claim selection and separate simulated/human
kind. A report reconstructs that exact selection rather than silently substituting
all currently available packets. Advisory locks reject concurrent cooperative
writers. Torn/extra/missing files and invalid contexts fail closed.

ACCEPT plus REJECT remains `CONFLICTING_REVIEW`, without a winner. Escalations and
other mixed decisions remain unresolved/needs-more-evidence as appropriate;
last-write-wins is never used. An independent adjudicator must cite new evidence
and preserve both earlier assertions. Source changes require a new task/snapshot,
not automatic annotation migration. Acceptance can never set financial authority,
rewrite a claim, erase an obligation or upgrade readiness.

Local labels/hashes are not signatures or authentication. An isolated, coherently
rewritten log or removed valid suffix cannot be detected without an external
trust anchor. `read_decisions(..., expected_tip=...)` supports a separately trusted
tip, and existing generated reports bind full event histories so a shortened log
invalidates their revalidated projection. This is not a tamper-proof multiuser
review service. Credential-like free text is rejected, not silently redacted;
this is a bounded guard, not comprehensive personal-information detection.

## Offline evaluation and interpretation

The preregistered authored controls cover:

1. Verified identity.
2. Ambiguous identity.
3. Missing parent context.
4. Contradictory parent evidence.
5. Unsupported instrument/schema attributes.
6. Incomplete pagination.
7. Duplicate source records.
8. Missing historical counterpart.
9. Unknown revision alignment.
10. Conflicting monetary observations.
11. Tampered primary evidence references inside a saved packet bundle.
12. Unavailable/incomplete source capture.

The invalid-citation case must be blocked before creating a task or reviewer
event; its valid primary baseline is checked independently. Thus the study
contains 12 attempted controls, 11 valid tasks and one blocked integrity control,
not twelve successfully reviewable tasks. The 11 valid tasks receive two scripted
decisions each. Sequence B reads no sequence-A result. A deliberately planted
ACCEPT/REJECT conflict on duplicate evidence tests preservation, not correctness
or human agreement. No actual reviewers, participants, acceptance rate, timing
or throughput are fabricated.

The separate preserved-evidence audit uses the lexicographically first original
frozen-pilot research source, `award-000/research/evidence/selected`, bound to
inventory `42a1abce2e6fa0eac26e751bfd2db5bea91eee42e7503db2cf114a6c142a49fd`.
It is a read-only usability/traceability audit, not a reclassification or sample
accuracy estimate. Its tasks/citations are reported separately from simulations;
no human review events or original-cohort metric changes are implied.

Task/claim inventories, exact evidence references, field observations, missing
proofs, parent/history context, all decision histories, contradiction flags and
outstanding blockers are included in deterministic reports. Counts distinguish
tasks, citation occurrences, unique citation IDs and events. Reproducibility means
independent source/event replay, not inter-reviewer reliability. Output hashes
exclude execution locations/clocks; actual source and reviewer-entered timestamps
remain substantive evidence. Final counts/digests and CI results are in the PR.

## Commands and reusable worksheet

Create a new entirely synthetic study and report:

```sh
python -m src.review_validation --demo --study-dir reports/NEW_c4_study \
  --run-dir reports/NEW_c4_evaluation
python -m src.review_validation --study-root reports/NEW_c4_study \
  --run-dir reports/NEW_c4_replay
```

Audit preserved evidence without recording review:

```sh
python -m src.review_validation --root data/raw/c3/SAVED_COLLECTION \
  --run-dir reports/NEW_c4_source_audit
# Optional: --packet-bundle reports/SAVED_C6_BUNDLE freezes its exact selection.
```

Fill [decision template v1](reviewer-decision-template-v1.json) using exact task,
citation and missing-obligation IDs; placeholders/nulls are intentionally invalid
until completed. Then append an explicit reviewer assertion and rebuild:

```sh
python -m src.review_validation --root data/raw/c3/SAVED_COLLECTION \
  --decision-log reports/NEW_c4_decisions --append-input /tmp/completed-decision.json
python -m src.review_validation --root data/raw/c3/SAVED_COLLECTION \
  --decision-log reports/NEW_c4_decisions --review-kind ACTUAL_HUMAN_REVIEW \
  --run-dir reports/NEW_c4_review_report
```

Do not copy simulation labels into actual human logs. The append command prints
only the event ID, not private input/rationale/labels. The output reader is
`read_report(output, study_root=...)` or
`read_report(output, source_root=..., decision_log=..., kind=...)` and independently
revalidates all primary evidence. Output is commit-marked JSON/Markdown/static
HTML and never overwrites an existing directory. Interrupted writes may leave a
partial new directory; inspect it and use a new path, never delete source evidence.
Exit 1 means completed research with operational limitations, 2 invalid/blocked,
130 interruption, and 0 a successfully published explicit decision only.

Bounds: 100 tasks, 1,000 decisions, 64 KiB per decision, 16 MiB per log, 32 MiB
study/source inventory and report/output budgets. C6's 4,096-character envelope
notes limit can be stricter than individual structured-field bounds. Native
source/existing packet limits remain in force. Output is static, escaped and has
no scripts, remote assets, tracking or automatic link requests. JSON/Markdown/HTML
and their hashes are regenerated on write/read; rehashed forged summaries fail.
Source mutation, symlinks, traversal and outputs nested inside protected roots
are rejected. Hash/race checks do not provide an atomic global filesystem snapshot.

## Separate operational readiness and Phase 4C5

The new operational assessment distinguishes demonstrated **offline** traceability,
task completeness, decision replay, contradiction retention and structural
integrity from real-world assumptions. It is not frozen 4B4 readiness. Actual
reviewer attribution assurance, human usability, actual throughput and source
history completeness remain UNKNOWN. Financial comparison authorization remains
`NOT_AUTHORIZED_BY_REVIEW`. No 100-, 500- or 5,000-award screening is authorized.

[Future human-study specification v1](human-review-study-v1.md) defines recruitment,
consent, purposive selection, instructions, blinded independent decisions,
worksheet/timing, ground-truth limits, error classes, disagreement handling,
acceptance criteria, privacy and retention. **The study has not been conducted.**
Phase 4C5 should establish study governance and execute that small consented study,
then evaluate observed usability/timing before proposing broader operations.
Authentication, revision/history/freshness and monetary proof obligations require
separate evidence and approval; review acceptance substitutes for none of them.

## Compatibility and self-review

Only companion modules/docs/tests and README are added. Existing source files,
flags, outputs, C6 schemas/logs, financial decisions, production defaults and CI
matrix are unchanged. The existing all-source implementation fingerprint naturally
changes when companion modules are added; old legacy checkpoints still fail
closed across implementation changes and require a new run, not silent migration.
Saved C1/C2/C3 research reports remain readable. No dependencies are added.

Self-review checks source/snapshot binding, returned counterevidence, nested
schema versions, attribution kinds, event order/duplicates, partial publication,
forged statuses/authority, unknown completeness, credential-like text, static
escaping, source races and report recomputation. It does not claim external
review approval, authenticated reviewer identity or exhaustive security proof.
No datasets, source captures, generated reports, credentials or private reviewer
information are committed.
