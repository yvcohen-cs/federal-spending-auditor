# Future human-review usability study, version 1

**Design only. NOT CONDUCTED. No participants or results exist for this study.**
The software simulation measures deterministic workflow controls, not human
accuracy, acceptance, time or throughput. This study cannot authorize screening
or alter financial/readiness gates.

## Recruitment, consent and selection

Recruit 2–4 consenting reviewers with familiarity with contract records and
source limitations. Record expertise in broad optional categories, not employer,
identity documents or sensitive personal information. Reviewers choose local
pseudonyms; labels are self-reported and unauthenticated. A study coordinator
must establish consent, access and storage controls outside this prototype.
No participant identity is invented by software.

Before collecting responses, freeze a study version, selection seed, source/task
inventory hashes, rubric and exclusions. Select 12–18 tasks purposively across
the twelve preregistered software-control cases: exact/ambiguous identities,
missing/conflicting parents, unsupported instruments, partial pagination,
duplicates, missing history, unknown revisions, conflicting monetary observations,
invalid citations and unavailable capture. Keep synthetic controls and lawfully
preserved public cases separate. Do not replace difficult or unavailable cases.
Use one unscored practice task; randomize the remaining order with a frozen seed.
The same evidence is independently assigned to each reviewer. Neither reviewer
sees another's decisions or the simulation's expected answers before submission.

## Instructions and presentation

1. Read the precise claim, rule version and saved automated result. Identify its
   scope before inspecting dollar values. A narrow saved match is not a statement
   about complete award finances, recipients or misconduct.
2. Use the existing accessible C6 static packet alongside the new task report and
   worksheet. Inspect **both** packet citations and separately labeled additional
   returned context. Review original field values/presence, exact source path,
   locator, artifact hash, request/representation and retrieval timestamp.
3. Check identity and parent context independently. Missing/null/empty fields do
   not establish absence. Inspect rejected candidates and contradictory evidence.
4. Distinguish saved C5 numerical observations from authorization for a new
   historical/revision-conditioned financial comparison. Review acceptance cannot
   authorize financial arithmetic, completeness, freshness or production use.
5. Record every unresolved proof obligation. Choose ACCEPT_EVIDENCE,
   REJECT_EVIDENCE, NEEDS_MORE_EVIDENCE, NOT_APPLICABLE or ESCALATE_FOR_REVIEW.
   These choices concern evidence quality only. No fraud label or probability is
   available. Uncertainty is a valid result, not a failure to find a discrepancy.
6. Supply structured interpretation, scope, uncertainty, valid citation IDs and
   acknowledgment of every missing proof obligation. Give a concrete follow-up
   when evidence is needed or escalation is requested. Do not enter personal
   information, credentials or unrelated allegations.

Use locally saved evidence; the study requires no network access. Official source
links are references, not verified current content. Additional external research
requires separate lawful authorization and must not silently replace the frozen
study evidence. Do not open untrusted arbitrary links or bypass access controls.

## Worksheet and recording

Copy [decision template v1](reviewer-decision-template-v1.json) for each task.
It is an **unfilled template**, not a valid event: nulls/placeholders must be
replaced by reviewer-provided values, exact task/citation IDs and the complete
missing-obligation list. Add typed `RecommendedVerificationAction` entries to
`follow_up` for NEEDS_MORE_EVIDENCE or ESCALATE_FOR_REVIEW. Use explicit UTC time.
The append CLI validates and stores a separate immutable event; it cannot modify
source bytes or automated results. Keep human and simulated logs separate.

Separately record, in a private coordinator worksheet:

| Field | Required value |
|---|---|
| Study version and frozen selection digest | Exact registered values |
| Task ID / source packet ID | Exact report references |
| Reviewer pseudonym / event ID | Reviewer-provided label and append result |
| Start/end UTC / elapsed seconds | Actual observations, never generated estimates |
| Pause/interruption seconds and reason | Optional bounded nonpersonal description |
| Citation located / hash check completed | yes / no / unavailable, with reason |
| Decision and unresolved obligations | Exact event references |
| Interface difficulty / accessibility barrier | Reviewer-provided observation |
| Error class and adjudication reference | Coordinator assessment with evidence |

Measure elapsed task time using a local monotonic stopwatch where possible;
record wall times separately and explain inconsistencies. Include pauses,
incomplete tasks and withdrawals explicitly. A 45-minute session cap is an
ethical/ergonomic stop rule, not an efficiency benchmark. Do not infer completion
times from event timestamps alone. The current software does not instrument a
human throughput study or authenticate participants.

## Ground truth, disagreement and errors

Authored controls have known field/integrity properties, not known real-world
award truth. Public records do not establish complete histories, corrected
revisions or misconduct ground truth. Rubric adherence and source traceability
are assessed separately from agreement with an automated status. Do not require
acceptance merely because an automated result says verified.

Preserve all independent decisions. Report exact decision agreement and the full
confusion table descriptively; do not treat agreement as correctness. An
independent adjudicator reviews both rationales and citations, records the scope
of disagreement, and requests additional primary evidence where necessary.
Adjudication is a new append-only assertion, never deletion or majority-based
replacement of prior decisions. A changed evidence snapshot requires a new task;
there is no silent annotation migration or winner selected by the software.

Classify errors separately: wrong claim scope; missing/incorrect citation;
missed counterevidence; unknown interpreted as complete/absent; unsupported
identity or instrument inference; version/timestamp mistaken for revision;
monetary inventory mistaken for authorized comparison; attribution/privacy error;
invalid workflow action; interface/accessibility failure. Preserve unresolved
cases instead of assigning speculative error labels.

## Prespecified acceptance criteria and analysis

These criteria are prospective and have **not** been measured:

- 100% of stored decisions pass structural/context/citation validation and all
  financial-override and tampered-citation controls remain blocked.
- At least 95% of submitted worksheets contain required scope, uncertainty,
  timing and citation fields; missing/abandoned tasks remain in denominators.
- At least 90% of observations on authored uncertainty controls explicitly
  identify the seeded missing proof/counterevidence. Report counts and small
  sample limitations; this is not accuracy on actual contract outcomes.
- 100% of disagreements remain preserved and receive documented adjudication or
  an explicit unresolved follow-up. No unanimity target replaces evidence review.
- Report actual completion times, median/range and interruptions by task type
  only after collection. No assumed throughput target, population extrapolation
  or conversion into authorization for 100/500/5,000-award screening.
- Resolve critical integrity/privacy defects and material accessibility blockers
  before proposing a larger usability study. Failure is reported, not repaired
  by post-hoc threshold changes or case replacement.

Report participant count, task/response denominators, exclusions, uncertainty,
worksheet completeness, traceability, disagreement patterns and timing separately.
No weighted confidence score is produced. Preregister any protocol changes before
new responses; retain the prior version and distinguish cohorts.

## Privacy, security and retention

Only lawfully accessible source evidence and consented minimum reviewer metadata
may be used. Store source snapshots separately from private pseudonymous response
logs and consent records. The latter are not repository content. Restrict local
filesystem access, use approved encrypted storage where available, establish a
retention/deletion schedule with participants, and avoid publishing identifying
free text. Never commit credentials, datasets, generated reports or real reviewer
information. Local hashes/labels are not signatures, authentication or access
control for a multiuser service.

Phase 4C5 should execute this small consented study only after study governance
and storage are established. Human usability, attribution assurance and actual
throughput remain UNKNOWN until measured. Frozen Phase 4B4 readiness and all
existing production financial gates remain unchanged.
