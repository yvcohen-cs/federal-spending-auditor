# Phase 4B1: FPDS continuation compatibility

## Baseline and original security rationale

Work begins from main 518f81b, containing merged Phase 4A PR #11. The original
validator parses Atom next links at collection_sources.safe_next; it rejects any
query key outside q/FEEDNAME/length/start/index/s and restricts s to FPDSNG.COM.
An authored fixture with VERSION=1.5.3 therefore reproduces
unsupported_fpds_next_parameters before a second request is possible. The saved
Phase 4A failures also contain s=FPDS, a second incompatibility hidden by the first.

The original restriction is intentional: untrusted next links must not redirect
collection, change source/identity/filter scope or consume unbounded resources.
The fix must preserve that boundary. C3 creates requests from validated parameters
on its fixed HTTPS endpoint, never by blindly fetching an href.

## Source-contract research (consulted 2026-10-27, Pacific time)

### Authoritative historical material

- [FPDS FAQ revision, July 2025](https://www.fpds.gov/wiki/index.php?diff=cur&oldid=4028&title=ATOM_Feed_FAQ):
  indexed official material distinguishes feed versions 1.5.2/1.5.3, describes
  1.5.3's Consortia fields, ten records per request and daily updates. These are
  historical statements, not a present-day completeness or refresh guarantee.
- [FPDS 1.5.3 release announcement](https://www.fpds.gov/fpdsng_cms/index.php/en/newsroom/177-atom-feed-decomm-2.html):
  indexed official notice describes introduction in October 2022 and retirement
  of 1.5.2 in 2023. Direct access now redirects to SAM.gov; indexed historical
  text is not a newly downloaded current specification.
- [Official 2024 DoD training](https://www.acq.osd.mil/asda/dpc/ce/p2p/docs/training-presentations/2024/P2P%202024%20-%20FPDS%20Reporting%20Basics%20-%20Procurement%20Awards.pdf):
  identifies the FPDS Atom feed as XML and 1.5.3 as the then-current version.

### Current authoritative availability guidance

[SAM.gov FPDS transition page](https://sam.gov/fpds) says ezSearch was
decommissioned February 24, 2026 and the Atom feed is being replaced by the
Contract Awards API. [SAM.gov contracting](https://sam.gov/contracting) also
describes the legacy feed retirement. The former
[usage page](https://www.fpds.gov/wiki/index.php/Atom_Feed_Usage) redirects there;
the old 1.5.3 specification is not reliably accessible. These facts limit present
contract research; no authenticated replacement API or automatic fallback is
introduced in this workstream.

### Preserved Phase 4A observations

The original 24-award evidence is available locally in ignored reports/. Its
twelve rejected FPDS next links use the fixed official HTTPS Atom endpoint,
FEEDNAME=PUBLIC, VERSION=1.5.3, s=FPDS, the original decoded q string and start=10.
This justifies those exact strings for bounded compatibility, not arbitrary
versions or search backends. VERSION is consistent with the documented feed
version marker; no evidence supports treating it as an opaque arbitrary token.
The precise formal semantics and future stability of s and VERSION remain
unresolved until separately documented or observed. No query rewrite is assumed.

### Implementation plan

1. Permit only the exact observed 1.5.3 marker and FPDS backend value, retain the
   legacy value, reject transitions after a token is established and keep q exact.
2. Version new C3 plans so old request journals cannot silently acquire the new
   protocol. Keep prior evidence readable; new C7 processing uses new run roots.
3. Record accepted href/request context and validation rationale; preserve raw
   bytes and distinguish link acceptance, page retrieval, terminal pagination
   and unknown history.
4. Add deterministic attacks/recovery tests, then perform a separately explicit
   small live probe (at most three queries, two continuations/query, twelve HTTP
   requests total). Stop on unexpected scope/schema/parameters.
5. Replay the original frozen sample offline into a new pilot/C7 output tree;
   compare identical metric definitions against the preserved baseline. Do not
   edit or resume the original pilot's old evidence or stage commits.

## Exact acceptance policy

VERSION accepts only the literal string **1.5.3**. It is treated as the observed
feed-version marker, not a wildcard token. The legacy s=FPDSNG.COM remains valid;
the new s=FPDS spelling requires VERSION=1.5.3. Once established, an explicit
backend/version change fails. An omitted marker inherits the established request
value; it cannot silently negotiate a new feed. Other versions require separate
research and a new reviewed rule. No query-representation transformation is
implemented or inferred from the samples.

The decoded q string, if present in the href, must exactly equal the current
original q, including whitespace, quoting, PIID, agency and any original filters.
FEEDNAME must remain PUBLIC and length must remain 10. Omitted scope parameters
are rebuilt from the original request; they are never removed. The builder
accepts only validated offset/backend/version fields, never a replacement query.
Only one offset protocol (start or the previously supported index) is allowed;
offsets advance exactly ten and cannot switch protocols. Request/page limits and
repeated-body detection remain independent safeguards.

The resolved URL must have the exact HTTPS scheme, official www.fpds.gov host,
no credentials or explicit port, and /ezsearch/FEEDS/ATOM path. Fragments,
backslashes, controls, dot segments, malformed percent encoding, encoded parameter
names, invalid UTF-8, duplicate keys (even identical values), unknown keys and
scope changes fail closed. Relative references are accepted only when they resolve
to that same endpoint; this is parser support, not an observed promise that all
servers issue relative links. XML is parsed with existing DTD/entity protections.
Ambiguous, missing or foreign-namespace next relations cannot become terminal
success. A missing next relation on an otherwise supported feed is terminal only
for that executed response/query; an empty feed remains inconclusive.

The production query currently sends PIID plus CONTRACTING_AGENCY_ID. Parent
identifiers are **local record guards**, not invented verified FPDS query fields.
No new date/type/parent filters or agency crosswalks are introduced. Unit tests
also demonstrate that any restrictions already present in a caller's original
q cannot be removed by a next link. Exact client request preservation does not
prove that the remote search engine interprets fields as exact identity predicates.

## Versioning, evidence and completeness

New C3 plans record collector_version=3. The plan/checkpoint/response JSON envelope
schema remains v1: its existing parameter dictionary can represent the exact new
tokens. New request validation permits them only under the v3 protocol. V1/v2
evidence remains readable without rewriting it; the current collector refuses
to resume a v1/v2 plan as v3, before any recovery write. There is no in-place
migration. Use a new collection/research directory. C7's compatibility/rule tags
are unchanged; the actual input collector version remains explicit in its scope,
so saved v2 evidence is never relabeled as v3.

On read, each v3 FPDS continuation request must match a validated preceding
successful page, including its declared body/metadata/checkpoint hashes and the
derived continuation parameters. Individual request hashes alone cannot authorize
a different backend or an unissued continuation. Earlier raw response bytes,
native strings, status/time provenance and content/observation identities remain
unchanged. Application response bytes are not HTTP wire captures or authenticity
signatures. Old bytes can acquire a new parser interpretation only in a new C7
run, never by adopting stale identity/financial/packet outputs.

Collection summaries record accepted decoded Atom hrefs, source-page/response
sequence, pinned query hash, validated next parameters and fpds-continuation-v1
rationale. The href text is a decoded XML attribute; the original escaped XML is
still preserved in the body. Summary validation rejects contradictory terminal
or unsupported continuation declarations. These references distinguish:

| Observation | What it establishes |
|---|---|
| Accepted continuation | A next request satisfies the client allowlist and lexical scope rules |
| Retrieved next page | A separate preserved HTTP observation, with its own status/time/hash |
| Terminal response | No supported next relation for the executed query; not necessarily a nonempty result |
| Complete action history | **Not established** by any of the above |

Pagination bounds, repeated pages, malformed XML, unsupported schemas/versions,
empty-with-next feeds, HTTP errors/Retry-After, timeouts and partial bodies retain
failure/partial/unknown states. No totals are inferred from unverified result-count
metadata. Existing transport retries, redirects prohibition, proxy/CA/TLS settings
and response-size bounds are unchanged. The probe uses zero retries.

Interrupted C3 reservations are never silently reissued. Complete orphan metadata
can be adopted only after existing hash/request checks; a body without metadata
or a partial filesystem write is preserved and refused, requiring a new run.
Tests cover interruptions before/after reservation, retrieval, body/metadata
publication and checkpoint commit, plus predecessor tampering and duplicate
modification observations. C4 content deduplication remains responsible for
preventing duplicate financial actions; no reconciliation algorithm changed.

## Bounded live probe and observed limitations

```sh
mkdir -p reports
python -m src.fpds_probe --live --selection work/explicit-native-awards.json --run-dir reports/NEW_fpds_probe
```

The selection uses the existing awards JSON format with exact PIID/agency and
paired parent context if supplied. At most three queries, three pages/query
(first page plus two continuations), nine HTTP attempts total, one MiB/response,
ten-second connect/read inactivity timeouts, pacing and no retries. The cap is
stricter than the requested twelve attempts. No source switch or fallback occurs.
Probe plans, child C3 journals and append-only reports stay in the ignored root.
--resume requires the same selection, code/configuration and plan. Exit 1 denotes
a bounded observational report, not universal verification; exit 2 is invalid
input/storage failure and 130 interruption.

The initial validation used three distinct PIID/agency queries, each with two
continuations: **nine HTTP 200 responses / 90 row occurrences**. Across requested
pages 2/3, VERSION remained 1.5.3 and s remained FPDS; decoded q was unchanged.
Each third page still advertised start=30, which was not followed. No query was
observed terminal; pagination stayed partial and history/freshness unknown.

The first query had only 28/30 exact PIID/agency matches; the second and third
had 30/30 each. The first two probes also failed their supplied local parent
guards. Thus **full selected-award scope was not confirmed**, despite exact URL
query preservation. The third query explicitly requested PIID/agency scope only,
with parent unknown; that is not an assertion of parent absence. All raw records
remain preserved, without changing C4 association rules or accusing any party.

These initial observations exposed a probe-hardening gap: record-context checks
were performed after each bounded query. The final probe now requests an explicit
v3 stop_on_context_mismatch policy from C3 and stops **before another page** after
any selected-context mismatch, preserving the first response. This policy is
recorded in the child plan and tested offline. Normal C3 legacy defaults retain
their existing observe-and-report behavior. No further live requests were made
after hardening; it is not presented as a repeated live validation of that guard.
The nine requests were split into an initial query and two supplemental single
queries; a planned extra query was not sent after a context failure. No broader
pilot rerun is performed automatically.

## Frozen pilot recovery

```sh
python -m src.recover_pilot --source reports/ORIGINAL_phase4a --baseline-report reports/ORIGINAL_baseline/pilot-report-000.json --run-dir reports/NEW_recovery
```

The source pilot and baseline report must actually exist. The command verifies
the baseline digest, original plan, frozen sample and entire substantive source
inventory before creating outputs. It uses new C7 existing-evidence runs for the
same award slots, never network collection, old stage adoption, sample replacement
or original evidence edits. Full source inventory is rechecked before final report
publication. A separate evaluator/code fingerprint identifies the new processing.
--resume and --retry-failed follow C7 rules; retries create new attempts and do not
overwrite review records. A C7 interruption now propagates instead of continuing
to later award slots. Unknown history/freshness remain independent dimensions.

The Phase 4A metrics retain the same units and denominators. Parsed source tasks
are measured from currently usable C2 observations (including valid inconclusive
empty feeds); frozen C3 collection summaries remain historical facts, not rewritten
to claim successful old processing. Current parsed rows and historical collected
rows are distinct fields. This implements the same parsed-task definition for
recovered evidence; it is not a new HTTP response or a history-completeness claim.
Financial rates still use emitted claims and authorized numeric comparisons;
newly processable claims legitimately change those denominators, which are shown
alongside counts. Invocation reports are excluded from substantive hashes so a
validated successful recovery resume remains deterministic.

For a broader **new** live pilot, the existing separately opted-in command remains:

```sh
python -m src.pilot_pipeline --live --target 24 --run-dir reports/NEW_public_pilot
```

It retains the Phase 4A eight-query sampling protocol and conservative one-page
per-source limits. A fresh frame or observation is not recovery of the original
sample. If the old local artifacts are unavailable, do not claim the comparison
was reproduced; use only an explicitly labeled new run.
