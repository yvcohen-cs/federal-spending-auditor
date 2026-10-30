# Phase 4C7 engineering assessment

This is an independent technical challenge of earlier implementation claims,
**not an independent human audit, accessibility certification, privacy decision,
institutional approval or completed human study**. No external reviewer or
participant is fabricated. Actual accessibility performance, human usability and
throughput remain UNKNOWN. No production screening or real-data deletion is enabled.

Starting main, merged PR #21: `6ad1fb872e38c8c1a1fb7ba7ae6761cd3e0f0993`.
[Preregistered protocol](technical-assessment-protocol-v1.json) was committed in
`0b9b8e6` before adversarial evaluation; canonical SHA
`3e54d41cf582cfb7506d747618950f9a60e14147f7a6e0ce8d087f529ce57c30`.
It records twelve reviewed baseline module hashes, all prior frozen document
hashes, historical inventories, fault boundaries and twelve separate readiness
dimensions. The findings register separates CONFIRMED_DEFECT, DESIGN_LIMITATION,
UNVERIFIED_ASSUMPTION, VERIFIED_CONTROL and NOT_EVALUATED. No combined score is used.

## Review method and findings

The engineering inspection reads C5/C6 creation, typed consent/replay, capability
checks, receipt chains, expected tips, source/task inventory binding, aggregate
suppression, report primary projection, permissions, path checks, locks,
retirement/deletion and terminal presentation. Supporting code claims are tied to
the exact starting commit and the preregistered module hashes; conclusions are
challenged with temporary authored fixtures. No live API or participant records
are accessed. The complete existing suite exercises the earlier controls too.

[Findings register v1](technical-findings-v1.json) provides stable IDs, affected
functions, exact claim/code evidence, severity, practical impact, assumptions,
safe reproduction, remediation, verification and residual limits. Severity is
local engineering triage, not a misconduct assessment or external risk certification.

Two confirmed defects have focused remediations:

- TA-001: DELETED namespace validation used `exists()`, so an allowed dangling
  symlink could be ignored. `lexists()` now detects the entry and fails closed.
- TA-002: the original manifest checked exact bytes and directory names/modes but
  not the captured object identities. A moved-aside original followed by an
  identical copy could satisfy that content check. New captures use context v2
  with file/directory device, inode and kind in the sealed manifest. Surviving
  objects, opened parents, files and removal targets are checked before mutation.
  Same-byte replacement therefore stops without deleting the replacement.

This does not eliminate hostile same-user races or inode recycling. Cooperative
locks are advisory and cannot authenticate actors. Real-data deletion remains
blocked; generation-safe filesystem operations, trusted namespace/access design,
backup/copy governance and independent inspection remain external requirements.

## Lifecycle compatibility and interruption boundaries

New captures remain exactly the existing simulated twelve-task environment; no
additional delete target is accepted. Source evidence is never a deletion target.
Capture schema v2 preserves the v1 field set but changes manifest semantics to add
`identity:` entries for every file/directory, including each managed root. These
are local object observations, not award/person identities. Lifecycle event schema
remains v1 and MAC/context/sequence binding remains mandatory.

Old v1 captures remain readable, with original evidence and reports unchanged.
New retire/delete transitions from a v1 capture are blocked because missing
historical identity metadata cannot be fabricated. Create a new simulated run;
there is no silent migration or resealing. A v1 DELETED tombstone may be read and
have its already-authorized private manifest cleanup completed, without opening
new deletion scope. Frozen C6 documents are not rewritten to claim v2 existed.

Fault tests cover before/after retirement begins, each rename, before/after
DELETE_BEGIN, individual unlinks, before/after directory removal, and after the
terminal event before manifest cleanup. Supported recovery preserves the exact
survivors, date, reason, expected tip and original object identities. Unknown or
changed files/directories, links, copied stores, wrong capabilities, duplicate or
missing events, invalid versions and partial publication artifacts fail closed.
Forensic copies/original moved-aside objects in tests are retained until explicit
test cleanup; software never guesses replacements or repairs missing histories.

Recovery still accepts missing manifest members once DELETING is durable; there
is no per-object intent journal proving who removed them. This is a documented
limitation of the simulated rehearsal, not real-data deletion assurance. Existing
C5 direct commands, copied stores and static report copies are not globally revoked.

## Governance and privacy assessment

All seven prospective approval categories remain externally unverified.
`ApprovalDossier` is a separate strict schema-v1 immutable tuple of the unchanged
C6 checklist snapshots. It binds every snapshot to the same protocol, task set,
governance and document digest; rejects exact duplicate snapshots and scope
expansion; preserves conflicting declarations and blocks shared references across
scopes. Unknown, stale, future, simulated or rejected records cannot disappear
behind a favorable declaration. There is no most-recent winner or automatic
resolution. The assessment never authorizes actual enrollment or financial work.

A dossier can only assess declarations actually supplied: an independent authority
must verify authenticity, completeness and omitted conflicts in an approved
registry/intake process. Local references are not authentication. No real approval
record is generated. Synthetic DTOs in tests are explicitly not approvals.

[Pre-pilot checklist](pre-pilot-checklist-v1.json) covers consent, eligibility,
withdrawal, minimization, pseudonymity, timing, access, encryption, backups,
retention/deletion, suppression, publication, institutional authority and support.
Each item records REQUIREMENT, CURRENT_EVIDENCE, EVIDENCE_GAP, RESPONSIBLE_ROLE,
VERIFICATION_METHOD and STATUS. SATISFIED_BY_SOFTWARE means only the narrow named
schema/aggregation control; it does not approve privacy, law, accessibility or
human participation. Other requirements remain BLOCKED,
REQUIRES_EXTERNAL_VERIFICATION or NOT_EVALUATED.

[Prospective real-data deletion design](real-data-deletion-design-v1.md) is
**documentation only**: request intake/authentication, minimal separate mapping,
retirement/revocation, primary deletion, copy/backup tracking, authenticated
confirmations, failure handling, receipts and published aggregate limits. No
identity collection, participant request intake or real-data deletion is added.

## Accessibility technical assessment

The opt-in simulated adapter has linear keyboard numbered choices, explicit
save/resume/withdraw instructions, plain decision labels, no color-only cues and
recovery after invalid input. Added instructions explain that declining timing
continues untimed, and distinguish source observation from automated inference.
Unknown proof stays unresolved. Control/format characters, bidi controls and
Unicode line separators are visibly escaped; only exact numbered menu lines may
be relabeled, never longer source claims or evidence text.

Long listings/citations, technical JSON labels, closed response choices and source
paths revealing control names remain limitations. No terminal/screen-reader
combination, real accessibility performance or WCAG conformance is established.

Prospective specialist steps, requiring separate approval and no fabricated results:

1. Record terminal, operating system, assistive technology/version, configuration
   and nonparticipant test environment; approve privacy-safe test artifacts.
2. Navigate with keyboard only, read the introduction and exact claim, find source
   references, distinguish observation/inference and identify every unknown.
3. Evaluate long citation reading, wrapping, interruption/repetition, presentation
   order and recovery without color or cursor assumptions.
4. Check timing refusal, save/explicit resume, consent decline and withdrawal
   prompts, including alternate input and accessible support arrangements.
5. Document actual observations, failures, accommodations and retests honestly;
   do not extrapolate unit-test success to compatibility or standards conformance.

## Reproducible assessment reports

`technical_assessment.py` validates the pinned protocol, dossier and versioned
assessment documents. `technical_assessment_reporting.py` generates deterministic
JSON/Markdown/escaped static HTML with a restrictive CSP. Reports separate
AUTOMATED_TEST_RESULT, TECHNICAL_CODE_REVIEW, DOCUMENTED_REQUIREMENT,
EXTERNAL_APPROVAL, ACTUAL_HUMAN_OBSERVATION and UNKNOWN. External approval and actual
human observation arrays remain empty. All twelve readiness dimensions are
independent; no aggregate readiness score or real-study authority is produced.

A report without JUnit input labels test evidence NOT_EVALUATED. Optional offline
JUnit is normalized to sorted case outcomes, excluding timestamps, durations,
paths, output and user text. The test suite records a digest of all source/test Python files, requirements and
assessment inputs;
stale-source receipts, duplicate cases, malformed XML, DTD/entity declarations,
missing binding and contradictory outcomes fail closed. Findings show local
regression verification only when their referenced tests occur and pass. A local
receipt is **not authenticated CI provenance**: a local owner can forge it, and it
never becomes an external approval or independent security certification.

Reports include starting commit, reviewed baseline/current module hashes, input
hashes, findings and severity, software test counts, requirements, unknowns,
blockers and remediation priorities. They contain no private paths, capabilities,
participant labels or raw histories. Readback checks exact file inventory/hashes
and independently regenerates every representation; rehashing a forged summary
cannot make it valid. Report generation never mutates a study store or deletes data.

```sh
python -m pytest -q --junitxml=/tmp/C7_TEST_RESULTS.xml
python -m src.technical_assessment_reporting \
  --test-results /tmp/C7_TEST_RESULTS.xml --output /tmp/NEW_C7_ASSESSMENT
```

The full offline run includes the source-binding fixture in the C7 test module.
Use a fresh output outside Git/managed roots. Exit1 is limited research output,
not authorization; exit2 is invalid/blocked. Test receipts/generated reports stay
outside Git. No live collection, external credentials or new dependencies.
Repeated output digests, exact final head, full-suite/smoke and Python3.11/3.12 CI
results are recorded in the completion PR.

Frozen protocols/inventories, collection defaults, financial reconciliation and
eligibility, checkpoint schemas and Phase4B4 readiness decisions remain unchanged.
The usual broad implementation fingerprint changes with companion/security module
edits; old checkpoints require a fresh run across implementations, no silent migration.

Phase4C8 should obtain independent external governance/security/accessibility and
real-data deletion-design inspection, then resolve storage/backup/authentication
and participant-support obligations. A separately authorized voluntary pilot could
only follow those gates. Authorized source validation and revision-conditioned
financial evidence remain separate unresolved work; no production screening is enabled.

Accessibility reference principles are drawn from [W3C WCAG 2.2](https://www.w3.org/TR/WCAG22/):
keyboard operation (2.1.1), meaningful sequence (1.3.2), focus order (2.4.3),
non-color-only information (1.4.1), error identification (3.3.1), labels/instructions
(3.3.2), and adjustable timing (2.2.1). These guide technical questions only;
WCAG is a web-content standard, and this terminal inspection is neither an
applicability determination nor a conformance evaluation. No live assistive-
technology testing or external accessibility approval was conducted.
