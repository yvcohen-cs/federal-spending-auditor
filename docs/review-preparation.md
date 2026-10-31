# Phase 4C8: review-ready software evidence and synthetic workflow hardening

Main was synchronized after independently verifying merged PR #22 at
`cd7c0d493fa1099505b1584262a3039eced78606`. PR #22 is not recreated or remerged.
[Protocol v1](review-preparation-protocol-v1.json), committed in `44012d9` before
evaluation, pins the merged dependency, 26 prior frozen documents and historical
inventories. Its canonical SHA is
`7f627ef251d66f272abea7bcf5a444b4daa7af7f9a41d2a683328ef2ad08122b`.

This phase implements bounded software preparation, not external approval,
participant enrollment, real-data deletion, production screening or certification.
No participant identities, real approval records or external credentials are added.
There is no live API collection. Financial eligibility/reconciliation, collection
defaults and frozen readiness decisions remain unchanged.

## C7 limitations addressed and retained

| C7 concern | C8 implementation | Remaining limit |
|---|---|---|
| TA-007: missing objects accepted during partial deletion without per-file history | Context-v3 simulated captures require a context/MAC/order-bound INTENT before each unlink/rmdir and COMMIT afterward. Missing objects without intent and reappeared committed objects fail closed. | An absent pending-intent target is explicitly recorded as ABSENCE_OBSERVED_AFTER_INTENT, not proof of actor attribution. Same-key coherent rollback and malicious suffix removal cannot be authenticated without an external anchor. |
| TA-008/009: namespace races and inode reuse | Retains identity/hash/no-follow and parent checks plus cooperative locks; object journal binds the original manifest and exact order. | No atomic generation-safe object handle, hostile same-user/privileged defense or secure erasure claim. Real-data operations remain unauthorized. |
| TA-006/019: copies, backups and released reports | Strict scope-bound copy/backup/snapshot declarations retain contradictions and require an evidence hash for deletion claims. Unknown verified/unmanaged counts remain null. | No discovery, global revocation, backup deletion, external authentication or assurance that unpublished declarations are complete. |
| TA-014: long evidence and uncertain AT behavior | Opt-in keyboard browser separates summary, citations, observed fields, assessments, unknowns and limitations into bounded pages. | No real assistive-technology test, accessibility performance measurement or WCAG conformance. |
| TA-015/020: approval authenticity and workflow bypass | Independent-review evidence package binds the exact clean Git commit, source hashes/links and both test/input receipts. Five external review roles remain NOT_ESTABLISHED; actual enrollment is always disabled. | A public package and local test receipt are not signatures, authority authentication or institutional approval. Legacy direct tools are not globally access-controlled by this layer. |

## Durable synthetic deletion progress

`deletion_progress.py` creates an immutable deterministic plan from the sealed
manifest: outputs then batch; files first, child directories before parents, roots
last. Each object has a constructed local journal ID bound to context, index,
original device/inode/kind and expected bytes. These identify filesystem evidence,
not people, awards or real-world identity inferred from names/hashes.

New capture schema **v3** uses the existing simulated twelve-task/four-session
constraints. Capture/lifecycle MACs, original evidence, source hashes, permissions,
no-follow traversal, expected tips and nonblocking cooperative locks remain.
V1/v2 captures and reports are still readable. They cannot start new destructive
transitions because historical per-object progress cannot be invented; use a fresh
simulated run. Legacy partial v2 deletion without the new journal fails closed;
there is no migration or silent reconstruction.

After DELETE_BEGIN, each object follows:

1. Validate the exact original survivor and journal prefix.
2. Atomically publish INTENT before mutation.
3. Recheck the parent/target and bytes, unlink or rmdir, then fsync the parent.
4. Atomically publish COMMIT with REMOVED if this call returned successfully.
5. On explicit recovery, an absent target with a valid pending INTENT is recorded
   as ABSENCE_OBSERVED_AFTER_INTENT. An absent target without intent is an error.
   Recovery does not assert who removed the object or reconstruct an earlier event.

Duplicate, missing interior, reordered, malformed, partial or forged journal
records stop progress. A committed object that reappears is rejected even before
further deletion. Original modified/replaced survivors are retained on failure;
unknown files/links are never added to scope. Object entries store only constructed
IDs/indexes, not source paths or session values. The original private manifest
remains necessary for replay until deletion completes.

DELETE_COMMIT event schema2 seals entry hashes/counts and the explicit absence-
recovery count. Cleanup can resume against that sealed receipt if interrupted,
without pretending missing progress entries remain replayable. Journal files and
the manifest are then removed; retained receipt data contain no raw session paths,
responses, capabilities or histories. Aggregate reports expose counts/scope only,
not object IDs/MAC histories. Original v1 lifecycle event/report projections remain
unchanged for earlier v1/v2 data.

A matching pending-intent prefix cannot distinguish a crash-before-COMMIT from a
same-key actor removing a final commit. This is explicitly observational recovery,
not trusted historical repair or proof of deletion authorship. Independent review
must evaluate external anchors, protected execution, filesystem semantics, copy
registry, backups and request authentication before any real-data design.

## Evidence navigation and privacy

`evidence_browser.py` is read-only. Commands are s/c/o/a/u/l for sections, n/p for
pages, b to return to structured response entry, ? for help, q to save/stop and w
to withdraw. Page order/position is explicit, no mouse/color/cursor movement is
required, and invalid input is not echoed or retained. Full claim strings, citation
hashes/locators/representations/URLs, original JSON values, observation basis and
unknown proof remain visible without truncating source evidence. No URL or source
file is automatically fetched, opened in an editor or modified.

The existing terminal receives an optional presenter callback; its default display,
CLI flags and event semantics are unchanged. `accessible_terminal(...,
paged_evidence=True)` is opt-in and remains simulated-only. Browser q/w reuse the
existing append-only SUSPEND/WITHDRAW behavior; navigation cannot create a decision,
authorize arithmetic, fill missing proof or suppress source counterevidence.
Exercise interactive sessions before sealing a capture, as in C6/C7.

Timing remains optional, with original C5 schema enforcement and no fabricated
pause duration. Control/bidi/format characters are visibly escaped. Long individual
source values can still be burdensome; source-path blinding and actual AT/terminal
behavior require specialist evaluation. No participant or tester is fabricated.

## Copy and backup governance

`CopyInventory` and `CopyDeclaration` are strict stdlib schema-v1 dataclasses/enums.
An inventory is scoped to the exact review-input digest. Opaque copy references
carry only kind, declared state and optional evidence hash; there are no names,
participant mappings, storage paths or credentials. A deletion claim requires
referenced evidence, which is still **not authenticated proof**.

Unknown completeness never defaults to complete; verified/unmanaged counts remain
unknown even when no copies are declared. DECLARED_COMPLETE is a claim, not a
verified observation. Conflicting PRESENT/CLAIMED_DELETED or kind declarations for
the same reference are preserved and block favorable interpretation. Duplicate
identical records and scope replay are refused. No real inventory/approval record
is generated by the CLI; packages start with an explicit UNKNOWN inventory.
External privacy/storage authorities must verify managed copies, snapshots,
retention, deletion confirmations and public-release limits independently.

## Independent-review evidence package

`review_evidence.py` produces owner-only JSON, Markdown and escaped static HTML,
with restrictive CSP and exact readback/primary recomputation. It accepts no
arbitrary attachments, study stores, raw histories, raw JUnit output or credentials.
Only repository source/test Python, Markdown/JSON documentation, README and
requirements are allowlisted for hashes and immutable GitHub source links.

A package requires:

- An explicit exact HEAD and source bytes matching Git blob objects at that commit,
  including rejecting uncommitted, missing, symlink or extra allowlisted source.
- A passing normalized C7 test receipt bound to current source/test/requirements.
- A separate C8 test-suite property bound to all package source/document inputs.
- The C7 engineering findings/readiness assessment, frozen document hashes,
  normalized outcomes/counts and explicit current source manifest.
- Separate NOT_ESTABLISHED requirements for independent security, privacy,
  accessibility, institutional and storage review. Existing seven approval scopes
  remain external obligations; no package status authorizes a real study.

A separate C8 change record maps implemented controls and exact regression references
to the frozen C7 concerns. C7 findings remain historical and are not rewritten;
new mitigations and residual risks are independently visible.

The package contains hashes and public repository links, not raw code copies,
local paths, capabilities, participant identifiers, raw logs or histories. It is
review-ready evidence, not an assertion that independent review occurred. Local
receipts and manifests are not authenticated external attestations. A reviewer
must independently match the PR head, recompute hashes/run tests and inspect the
actual controls and residual limitations.

## Reproduce offline

```sh
python -m pytest -q --junitxml=/tmp/C8_RESULTS.xml
python -m src.review_evidence --test-results /tmp/C8_RESULTS.xml \
  --expected-head EXACT_PR_HEAD --output /tmp/NEW_C8_REVIEW_PACKAGE
```

Use a fresh private output outside Git and managed roots. Exit1 means limited
preparation/research evidence, never production readiness; exit2 is blocked.
No package can be published from an uncommitted source snapshot. Generated
receipts/packages and synthetic study artifacts remain outside Git.

For synthetic evidence navigation, call the existing adapter on a valid unsealed
simulated C5 session with `paged_evidence=True`; the old default is unchanged.
Existing coordinator rehearsal/retire/delete commands operate on new v3 captures
with exact current tips and explicit dates. Do not run them on participant data.

The C8 test module records the package-input digest property. Tests cover object
intent/commit boundaries, unexplained disappearance, reappearance, forged/truncated
journals, interrupted cleanup, legacy read-only behavior, links and replacement,
unknown/conflicting inventory, browser navigation/save/withdraw/control injection,
source/commit/receipt mismatch and package tampering. Full offline Python3.11/3.12
CI and explicit pipeline smoke results, source preservation and repeated package
hashes are recorded in the PR completion report.

Frozen C5–C7 protocols and historical financial/readiness outputs remain unchanged.
New code changes the existing broad implementation fingerprint; old checkpoints
require a fresh run across implementation changes, never silent migration.
No real enrollment, real-data deletion, production screening, source collection or
new external credentials are introduced. High-risk external sign-off, host
isolation, copy/backup authenticity, inode generation/races and actual accessibility
remain blockers. Phase4C9 should obtain and independently verify those external
review inputs before considering any separately authorized voluntary pilot.
