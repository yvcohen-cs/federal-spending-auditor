"""Escaped, standalone HTML. No network, JavaScript or remote assets."""
from __future__ import annotations

import base64
import hashlib
import re
from html import escape
from urllib.parse import urlsplit
from .evidence_io import EvidenceError


CSS = """body{font:16px/1.6 system-ui,sans-serif;margin:auto;max-width:1100px;padding:1.5rem;color:#172638;background:#f4f6fa}a{color:#164994}article{background:white;border:1px solid #cdd7e5;border-radius:8px;padding:1.5rem;margin:2rem 0}h1,h2,h3{line-height:1.3}table{border-collapse:collapse;width:100%;display:block;overflow:auto}th,td{border:1px solid #cdd7e5;padding:.5rem;text-align:left;vertical-align:top}pre,code{white-space:pre-wrap;overflow-wrap:anywhere}dt{font-weight:700}dd{margin-bottom:.7rem}summary{cursor:pointer;font-weight:600}.status{font-weight:700;border-left:4px solid #315f91;padding:.5rem}.muted{color:#44566b}*:focus-visible{outline:3px solid #b05b00;outline-offset:3px}@media print{body{background:white}article{break-before:page}a{color:inherit}}"""
HOSTS = {"api.usaspending.gov", "www.usaspending.gov", "usaspending.gov", "www.fpds.gov", "fpds.gov",
         "sam.gov", "www.sam.gov", "www.gao.gov", "gao.gov", "www.oversight.gov", "oversight.gov"}


def safe_source_url(value):
    if not isinstance(value, str) or not value.isascii() or len(value) > 4096 or "\\" in value or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        return None
    if re.search(r"%(?:0[0-9a-f]|1[0-9a-f]|7f|5c)", value, re.IGNORECASE):
        return None
    try:
        u = urlsplit(value)
        if u.scheme != "https" or u.hostname not in HOSTS or u.username is not None or u.password is not None or u.port not in (None, 443):
            return None
    except ValueError:
        return None
    return value


def text(value):
    return escape("Unknown" if value is None else str(value), quote=True)


def link(value, label="Source record"):
    safe = safe_source_url(value)
    return f'<a href="{text(safe)}" rel="noreferrer noopener">{text(label)}</a>' if safe else text(value)


class _BoundedHTML(list):
    def __init__(self, limit):
        super().__init__()
        self.limit, self.size = limit, 0

    def append(self, value):
        self.size += len(value.encode())
        if self.size > self.limit:
            raise EvidenceError("review_html_size_limit")
        super().append(value)

    def extend(self, values):
        for value in values:
            self.append(value)


def render_html(manifest, events=(), *, max_bytes=32*1024*1024):
    if type(max_bytes) is not int or not 1024 <= max_bytes <= 32*1024*1024:
        raise EvidenceError("invalid_review_html_limit")
    from .review_events import validate_events
    validate_events(manifest, events)
    css_hash = base64.b64encode(hashlib.sha256(CSS.encode()).digest()).decode()
    csp = f"default-src 'none'; style-src 'sha256-{css_hash}'; img-src 'none'; script-src 'none'; base-uri 'none'; form-action 'none'"
    out = _BoundedHTML(max_bytes)
    out.extend(['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           f'<meta http-equiv="Content-Security-Policy" content="{text(csp)}">',
           '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer">',
           '<title>Federal spending — evidence review</title>', f'<style>{CSS}</style></head><body>',
           '<a href="#main">Skip to claims</a><header><h1>Evidence review</h1>',
           '<p>Saved observations for independent human review. Findings are claim-specific and do not establish misconduct or complete award finances.</p>',
           f'<p>{len(manifest.packets)} selected of {manifest.total_available_claims} available claims. Human review does not change automated statuses.</p>',
           f'<p class="muted">Packet rules: {text(manifest.rule_version)} · schema {manifest.schema_version}</p>'])
    counts = {status: sum(p.claim.status.value == status for p in manifest.packets) for status in sorted({p.claim.status.value for p in manifest.packets})}
    latest = {e.packet_id: e.state.value for e in events}
    workflow_counts = {s: sum(latest.get(p.packet_id, "pending_review") == s for p in manifest.packets)
                       for s in ("pending_review", "needs_more_evidence", "reviewed", "closed")}
    out.append(f'<p>Claim status counts: {text(", ".join(f"{k}={v}" for k,v in counts.items()))}</p>')
    out.append(f'<p>Workflow counts: {text(", ".join(f"{k}={v}" for k,v in workflow_counts.items()))}. Unrecorded packets count as pending, not as actual review events.</p>')
    out.append('<p>Historical completeness, source freshness and revision alignment remain unknown. Verified results concern only their stated saved observations.</p>')
    out.append(f'<p>Substantive packet snapshot: <code>{text(manifest.substantive_sha256)}</code></p>')
    if manifest.generated_at_utc:
        out.append(f'<p>Optional report-generation time (not source retrieval): {text(manifest.generated_at_utc)}</p>')
    out.append('</header><nav aria-label="Claims"><ul>')
    for p in manifest.packets:
        anchor = p.packet_id.split(":")[-1]
        out.append(f'<li><a href="#p{anchor}">{text(p.comparison.scope)} — {text(p.claim.status.value)}</a></li>')
    out.append('</ul></nav><main id="main">')
    for p in manifest.packets:
        anchor = p.packet_id.split(":")[-1]
        out.extend([f'<article id="p{anchor}" aria-labelledby="h{anchor}"><h2 id="h{anchor}">{text(p.comparison.scope)}</h2>',
                    f'<p class="status">Automated status: {text(p.claim.status.value)}</p>',
                    f'<p>Claim: <code>{text(p.claim.claim_id)}</code></p><p>Packet: <code>{text(p.packet_id)}</code></p>',
                    '<h3>What is being checked</h3>', f'<p>{text(p.comparison.agreement)}</p>',
                    f'<p>Compatibility: {text(p.comparison.compatibility)}</p><ul>'])
        out.extend(f'<li>{text(reason)}</li>' for reason in p.comparison.reasoning)
        out.append('</ul><h3>What each source reports</h3>')
        for s in p.sources:
            r = s.identity
            out.append(f'<h4>{text(r.source)} — source-native identifiers</h4><dl>')
            for i in r.native_identifiers:
                out.append(f'<dt>{text(i.namespace)}</dt><dd><code>{text(i.value)}</code></dd>')
            for name in ("piid", "agency", "parent_piid", "parent_agency", "modification", "transaction"):
                v = getattr(r, name)
                out.append(f'<dt>{text(name)} ({text(v.basis)})</dt><dd>{text(v.value)} — {text(v.state.value)}</dd>')
            out.append('</dl>')
            out.append(f'<details><summary>Uninterpreted source date/type context (not freshness assurance)</summary><pre>{text(r.context_json)}</pre></details>')
            if s.monetary_observations:
                out.append('<table><caption>Preserved monetary observations; inventory is not a financial comparison</caption><thead><tr><th scope="col">Field</th><th scope="col">Original value</th><th scope="col">Interpretation</th><th scope="col">Signed date</th></tr></thead><tbody>')
                for o in s.monetary_observations:
                    out.append(f'<tr><td>{text(o.original_field)}</td><td><code>{text(o.value.raw_text)}</code> ({text(o.value.raw_kind.value)}, {text(o.value.state.value)})</td><td>{text(o.semantics.measure.value)}; {text(o.semantics.basis.value)}; {text(o.semantics.scope.value)}; currency {text(o.currency)}; normalized {text(o.value.normalized)}</td><td>{text(o.action_date_raw)}</td></tr>')
                out.append('</tbody></table>')
        out.append('<h3>Comparison result</h3>')
        out.append(f'<p>USA minus FPDS: <code>{text(p.comparison.difference_usa_minus_fpds)}</code>. Tolerance: {text(p.comparison.tolerance)}. Unknown means no numerical comparison was authorized.</p>')
        identity = p.claim.identity_result
        if identity is None:
            identity = next(d for d in manifest.financial_run.identity_run.decisions if d.claim_id == p.claim.financial_result.identity_claim_id)
        candidates = identity.award_candidates + identity.action_candidates
        if candidates:
            out.append('<table><caption>Candidate groups, including rejected contexts; retrieval records are not independent payments</caption><thead><tr><th scope="col">Constructed candidate ID</th><th scope="col">Relation and rationale</th><th scope="col">Constructed retrieval record IDs</th></tr></thead><tbody>')
            for c in candidates:
                out.append(f'<tr><td><code>{text(c.candidate_id)}</code></td><td>{text(c.relation.value)}: {text(", ".join(c.reasons))}</td><td><code>{text(", ".join(c.record_ids))}</code></td></tr>')
            out.append('</tbody></table>')
        out.append('<h3>Alternative explanations</h3><ul>')
        out.extend(f'<li><strong>{text(a.code)}: {text(a.state.value)}</strong> — {text(a.rationale)}</li>' for a in p.alternatives)
        out.append('</ul><h3>Evidence limitations</h3><ul>')
        out.extend(f'<li>{text(l.code)}: {text(l.detail)}</li>' for l in p.limitations)
        out.append('</ul><h3>Unresolved questions</h3><ul>')
        out.extend(f'<li>{text(q)}</li>' for q in p.unresolved_questions)
        out.append('</ul><h3>Next verification checks</h3><ul>')
        out.extend(f'<li>{text(a.instruction)}</li>' for a in p.recommended_actions)
        out.append('</ul><h3>Primary evidence citations</h3>')
        for c in p.citations:
            e, a = c.evidence, c.evidence.artifact
            out.append(f'<details id="c{anchor}{c.citation_id.split(":")[-1]}"><summary>{text(a.source)} — {text(a.relative_path)} {text(e.reference.locator)}</summary><dl>')
            for name, value in (("Citation", c.citation_id), ("Content artifact", a.artifact_id), ("Retrieval observation", e.observation_id),
                                ("Retrieved UTC", a.retrieved_at_utc), ("Source update UTC", a.source_updated_at_utc),
                                ("Representation / hash basis", a.representation.value + " / " + a.hash_basis),
                                ("Source-record URL", e.reference.source_record_url), ("Query URL", e.reference.query_url),
                                ("Endpoint", a.endpoint), ("Method", a.method), ("HTTP status", a.http_status),
                                ("Metadata paths", ", ".join(e.metadata_paths))):
                out.append(f'<dt>{text(name)}</dt><dd>{link(value, name) if name in ("Source-record URL", "Query URL", "Endpoint") else text(value)}</dd>')
            out.append(f'<dt>Preserved request parameters</dt><dd><pre>{text(a.request_json)}</pre></dd></dl></details>')
        history = [e for e in events if e.packet_id == p.packet_id]
        out.append('<h3>Separate human-review workflow</h3><p>Reviewer assertions are not authenticated or cryptographically signed and do not change automated findings.</p>')
        out.append(f'<p>Workflow state: {text(history[-1].state.value if history else "pending_review (no event recorded)")}</p>')
        for e in history:
            out.append(f'<details><summary>Event {e.sequence}: {text(e.state.value)} — {text(e.timestamp_utc)}</summary><p>Reviewer-entered label: {text(e.reviewer)}</p><pre>{text(e.notes)}</pre><ul>')
            out.extend(f'<li>{text(a.instruction)}</li>' for a in e.follow_up)
            out.append('</ul></details>')
        out.append('</article>')
    out.append('</main><footer><p>Offline report. Source links require an explicit user action; no remote assets or scripts are loaded.</p></footer></body></html>')
    return "".join(out)
