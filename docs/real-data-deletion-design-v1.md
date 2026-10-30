# Prospective participant withdrawal and deletion design v1

Status: **DOCUMENTATION ONLY — NOT IMPLEMENTED OR AUTHORIZED**. No real participant
data, identity collection, real deletion execution or compliance certification is
introduced by Phase 4C7. Existing destructive operations remain explicitly
simulated and manifest-bound. External privacy, institutional and security review
must precede any production design or actual pilot.

| Stage | Existing evidence | Required prospective design and responsible role |
|---|---|---|
| Authoritative intake | Local capabilities only | Privacy coordinator approves an accessible intake channel and request receipt; do not infer identity from names, source records or hashes. |
| Request authentication | Not implemented | Independent authority defines proportional authentication and handling of lost capabilities, representatives and disputes. Software must not guess an identity. |
| Pseudonym mapping | Opaque local labels; no person lookup | Where lawful/approved, coordinator holds the minimum separate request-to-session mapping, encrypted and access controlled. Do not add that mapping or identity collection to this repository. |
| Request scope | No real requests observed | Capture authorized request scope, consent/version, primary sessions, copies/releases and deadline obligations; conflicting requests require external review, not a latest-wins rule. |
| Retirement | Synthetic namespace rename | Stop active sessions and writers through a trusted supervisory service; invalidate future grants, record an authenticated retirement receipt and preserve failures for incident review. |
| Access revocation | Local path change only | Authoritative access control must revoke every managed capability, cached authorization and copy; a file rename is not global revocation. |
| Primary deletion | Synthetic v2 dev/inode+hash checks | Independently evaluate filesystem semantics, trusted namespace, protected process credentials and per-object durable intent/commit receipts. Never retrofit absent object identity into an old capture. |
| Managed copies | No discovery/registry | Establish a consented copy inventory and deletion scope before data creation; owner verifies completeness and preserves uncertainty about unmanaged copies. |
| Backup tracking | UNKNOWN | Storage administrator documents locations, snapshot schedules, immutability constraints, legal/institutional retention conflicts, expiry and authorized deletion methods. |
| Backup confirmation | No confirmation channel | Obtain authenticated administrator confirmations and independent spot checks. A local success flag or elapsed deadline is not confirmation. Unresolved backups remain blockers. |
| Completion receipt | Simulated local tombstone | Record minimal scope, authorization reference, actions, outcomes, missing obligations and verification provenance; avoid retaining raw histories or reidentifying mappings unnecessarily. External approval determines permitted receipt retention. |
| Partial failure | Simulated fail-closed recovery | Preserve exact original survivors and failed-transition evidence. Resume only documented supported states; unknown target, missing audit history or forged receipts must stop. Never silently reconstruct/repair records. |
| Published aggregates | Copies cannot be revoked | Before release, approve small-cell and differencing review plus consent/publication rules. After release, coordinator assesses correction/retraction and explains limits; do not promise erasure of recipients' copies. |
| Storage erasure | Unlink only | Assess encrypted storage/key management, snapshots, SSD behavior and backups independently. Do not call namespace unlink secure erasure or certify legal compliance. |
| External sign-off | None established | Privacy officer, institutional authority, security/storage and accessibility specialists verify their respective requirements independently. Software test success does not replace them. |

Frozen C5 prospective policy describes seven-day local withdrawal-batch deletion,
thirty-day backup handling and raw retention after closure, and up to ninety days
for approved aggregates. These are existing prospective obligations, not observed
participant outcomes or automatic enforcement. Conflicts with approved retention,
backup immutability or already released aggregates require external resolution
before recruitment. No new request intake, identity registry, participant
mapping, remote revocation or real-data erasure path is implemented here.

Local device/inode observations are not cryptographic object identity. Version-2
synthetic captures reduce accidental/static substitution acceptance, but inode
reuse, hostile races, snapshots, shared-user access and privileged coherent
rewrites remain outside their guarantee. Future real-data implementation requires
a separately reviewed protocol and independently testable authorization boundary.
