# Prospective local pilot governance, version 1

**Preparation only. No recruitment, consent collection or actual human study has
occurred in Phase 4C5.** A future study requires separate owner authorization,
voluntary eligible participants and approved storage/governance. Software does
not authenticate participants, verify consent comprehension, certify legal or
institutional approval, or authorize production screening.

## Purpose, eligibility and voluntariness

Study whether 2–4 consenting adults familiar with procurement/evidence concepts
can locate evidence, identify uncertainty and record defensible decisions. It is
not an investigation of participants, award recipients or misconduct. No award
is labeled fraudulent and no participant is ranked. The coordinator must resolve
applicable institutional/ethics requirements before recruitment. Do not recruit
or contact anyone automatically. Do not use coercion, performance incentives,
workplace/student evaluation, or penalties for refusal/withdrawal.

Explain the precise purpose, tasks, data fields, timing option, limitations,
retention and withdrawal procedure before asking for consent. Participants may
stop, skip by stating insufficient evidence, or withdraw without giving a reason.
No finding of correctness is promised where reliable reference evidence is absent.

## Authorization and consent

The owner/coordinator must supply an explicit `StudyAuthorization` record bound to
the exact local protocol, task-set digest and this governance document. Actual
human enrollment requires the frozen mixed task plan, approved private storage
and voluntary recruitment readiness. This local record is an out-of-band approval
reference, not proof of an approving person's identity. It cannot be inferred
from a hash, simulation or a successful command.

Enrollment creates NOT_STARTED / NOT_REQUESTED only. The participant must
explicitly acknowledge voluntariness, purpose and withdrawal; opt-in timing needs
an additional acknowledgment. A consent receipt binds protocol/governance and is
labeled OBSERVED_HUMAN or SIMULATED. Simulations never create actual consent.
Declining creates no responses and ends the session. Any changed task-set,
governance, purpose, timing setting or protocol requires new authorization and
consent; no retrospective criteria changes or automatic migration.

Use the unfilled consent/instruction templates. No legal name or signature is
required. A local capability authorizes a write, not participant identity.

## Data minimization and access

Do not ask for or store legal names, email/contact details, student/employment IDs,
IP addresses, location, demographic details, device identifiers or recruitment
correspondence. Participants use an opaque `P-` plus 16 hexadecimal characters
with at least one a–f letter, chosen/supplied outside any identity lookup. Keep no
identity-to-label mapping in the software. Simulation labels use a distinct SIM-
prefix. No legal names/contact information are accepted as labels.

The terminal records only closed decision/rationale/follow-up choices, exact task
and citation IDs, uncertainty/proof acknowledgments, session state and optional
clock observations. It does not persist arbitrary typed explanations, raw invalid
input, keystrokes, terminal history or network identifiers. Closed choices reduce
unnecessary identifying information; they also limit nuanced explanations, a
known usability question for the future study. Do not paste personal information
into the interface. The application is not a general personal-information detector.
Existing source evidence is separate and unchanged; only lawfully preserved
public evidence and clearly labeled authored controls may be presented.

Private stores must be outside all git worktrees and managed source/report roots.
Directories must be owned by the current OS account and mode 0700; records and
local capability files mode 0600. Use an owner-approved encrypted local volume,
restricted supervised workstation and approved backup policy for real study data.
Encryption, physical access and same-account isolation cannot be verified by this
prototype. Different participants should use supervised sessions with access only
to their own local capability. Do not share the coordinator capability.

No external accounts, browser server, telemetry, analytics, cloud synchronization
or network calls are required. Possession of local files does not establish a
real person's identity. Same-UID or privileged actors can access/replace private
material; this is not a secure multiuser identity service.

## Withdrawal, incomplete sessions, retention and deletion

Withdrawal is explicit, append-only and terminal, including after completion.
All earlier responses from WITHDRAWN sessions are excluded from aggregate
performance statistics, not silently retained as completed responses. Invalidated
sessions are excluded separately. Incomplete sessions remain IN_PROGRESS and
must not be described as completed; missing timing remains unmeasured.

A participant may request deletion without identifying themselves beyond the
session capability/pseudonym. The coordinator must immediately record withdrawal,
stop further use and regenerate any permitted aggregates without that session.
Do not publish or keep using stale pre-withdrawal reports. The prototype preserves
immutable local logs; it does not claim selective secure erasure, remote recall
or automatic anonymization.

For this small prospective pilot, the approved deletion procedure is to close
and retire the **whole private batch**, export only any separately permitted
withdrawal-excluding aggregate, and remove the entire private environment,
capabilities and generated reports within **7 days of a deletion request**.
Coordinate deletion of approved backups within **30 days**. Other consenting
participants may continue only in a newly authorized batch with explicit consent;
do not silently migrate records, pool cohorts or discourage withdrawal. If this
batch-wide deletion rule is unacceptable, do not start a human study until a
separately reviewed selective-deletion design exists.

Absent an earlier request, delete raw pseudonymous session material/capabilities
within **30 days of pilot closure**. Retain only owner-approved aggregate summaries
for at most **90 days**, then delete them and their backups under the approved
policy. These are prospective coordinator obligations, not software-enforced or
verified deletion guarantees. Retention clocks and backup access must be agreed
before real participation. Never delete original project source evidence as a
participant-data deletion action.

## Reporting restrictions

Aggregate reporting contains no participant labels, session IDs, individual event
histories, rankings or personal performance profiles. Withdrawn/invalidated
sessions appear only as separate counts and never enter performance denominators.
SIMULATED and OBSERVED_HUMAN results are separate. Actual human cells with fewer
than two eligible sessions, and timing cells supported by fewer than two measured
sessions, are suppressed. Small-cell suppression is not proof of anonymity;
publication requires coordinator disclosure review and participant information.
Do not publish raw response/session records or granular timestamps.

Reference agreement applies only to an explicitly authored narrow-property
control, not award truth or reviewer correctness. Public-source/uncertain tasks
have no reference answer and no correctness statistic. No actual human usability,
accuracy, agreement or throughput result may be claimed from simulations.

## Incidents and operational limits

Stop the session on changed evidence, unexpected task order, capability/context
failure, partial publication, invalid receipts, timestamp anomalies or suspected
identifying input. Preserve source evidence. Quarantine private artifacts under
coordinator access; do not automatically erase/retry uncertain writes. A session
can be explicitly invalidated and excluded; a torn two-file event/receipt boundary
requires investigation/new authorized batch rather than silent recovery.

Local hashes and HMAC receipts bind preserved bytes and possession of a local
write capability, not source authenticity, consent legitimacy or participant
identity. Coherent privileged rewrites or removal of all matching suffixes need a
separately trusted tip/report inventory to detect. No legal/ethics, encrypted
storage, authentication, actual usability or deployment readiness is established
by passing software controls. Financial and frozen readiness gates are unchanged.
