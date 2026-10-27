"""Separate append-only reviewer assertions and validated state transitions."""
from dataclasses import replace

import pytest

from src.evidence import ComparisonStatus as S
from src.evidence_io import EvidenceError, canonical, strict_json
from src.review_events import WorkflowState as W, append_event, main, read_events
from src.review_packet_builder import build_packets
from src.review_packet_html import render_html
from src.review_packet_io import read_bundle, write_bundle
from src.review_packet_models import RecommendedVerificationAction
from tests.financial_fixtures import financial_scenario
from tests.test_matching_ingestion import collection, snapshot


def setup(tmp_path):
    root = collection(tmp_path, financial_scenario("100.01", "100.00"))
    manifest = build_packets(root)
    packet = next(p for p in manifest.packets if p.claim.financial_result)
    return root, manifest, packet


def append(path, manifest, packet, state, **kw):
    return append_event(path, manifest, packet_id=packet.packet_id, state=state,
        reviewer=kw.pop("reviewer", "Synthetic reviewer label"), notes=kw.pop("notes", "Inspect source revisions."),
        timestamp_utc=kw.pop("timestamp_utc", "2026-10-27T00:00:00Z"), protected=kw.pop("protected", ()), **kw)


def test_append_only_full_workflow_and_separate_automated_status(tmp_path):
    root,m,p = setup(tmp_path)
    before = snapshot(root)
    log = tmp_path/"notes"
    previous_files = {}
    for state in (W.PENDING_REVIEW, W.NEEDS_MORE_EVIDENCE, W.REVIEWED, W.CLOSED):
        event = append(log,m,p,state,protected=(root,))
        for name,raw in previous_files.items():
            assert (log/name).read_bytes() == raw
        previous_files = snapshot(log)
    history = read_events(log,m)
    assert len(history) == 4 and history[-1].event_id == event.event_id
    assert all(e.assertion_kind == "reviewer_entered_unverified_assertion" for e in history)
    assert p.claim.status is S.INSUFFICIENT_EVIDENCE and snapshot(root) == before
    html = render_html(m,history)
    assert "Workflow state: closed" in html and "insufficient_evidence" in html


@pytest.mark.parametrize("initial", [W.REVIEWED, W.CLOSED, W.NEEDS_MORE_EVIDENCE])
def test_bad_initial_state_does_not_initialize_or_write(tmp_path, initial):
    _,m,p = setup(tmp_path)
    with pytest.raises(EvidenceError, match="transition"):
        append(tmp_path/"log",m,p,initial)
    assert not (tmp_path/"log").exists()


@pytest.mark.parametrize("target", [W.PENDING_REVIEW, W.NEEDS_MORE_EVIDENCE, W.REVIEWED, W.CLOSED])
def test_closed_is_terminal_and_history_unchanged(tmp_path, target):
    _,m,p = setup(tmp_path)
    log = tmp_path/"log"
    for state in (W.PENDING_REVIEW,W.REVIEWED,W.CLOSED):
        append(log,m,p,state)
    before = snapshot(log)
    with pytest.raises(EvidenceError, match="transition"):
        append(log,m,p,target)
    assert snapshot(log) == before


def test_reviewed_can_request_more_evidence(tmp_path):
    _,m,p = setup(tmp_path)
    log = tmp_path/"log"
    for state in (W.PENDING_REVIEW,W.REVIEWED,W.NEEDS_MORE_EVIDENCE,W.PENDING_REVIEW):
        append(log,m,p,state)
    assert len(read_events(log,m)) == 4


def test_notes_markup_is_plain_text_and_optional_follow_up(tmp_path):
    _,m,p = setup(tmp_path)
    notes = '<script>alert(1)</script>\n<img src="https://evil.test/x">'
    action = RecommendedVerificationAction(instruction="Check the signed date.", citation_ids=(p.citations[0].citation_id,))
    append(tmp_path/"log",m,p,W.PENDING_REVIEW,notes=notes,follow_up=(action,))
    events = read_events(tmp_path/"log",m)
    assert events[0].notes == notes
    html = render_html(m,events)
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert 'src="https://evil.test/x"' not in html


@pytest.mark.parametrize("changes", [{"notes":""}, {"notes":"x\x00y"}, {"reviewer":"\n"}, {"timestamp_utc":"2026-10-27T00:00:00+03:00"}, {"reviewer":"x"*129}])
def test_invalid_event_metadata_no_write(tmp_path, changes):
    _,m,p = setup(tmp_path)
    with pytest.raises((ValueError,EvidenceError)):
        append(tmp_path/"log",m,p,W.PENDING_REVIEW,**changes)
    assert not (tmp_path/"log").exists()


def test_backdated_event_rejected_without_write(tmp_path):
    _,m,p = setup(tmp_path)
    log = tmp_path/"log"
    append(log,m,p,W.PENDING_REVIEW)
    before = snapshot(log)
    with pytest.raises(EvidenceError, match="time_order"):
        append(log,m,p,W.REVIEWED,timestamp_utc="2025-01-01T00:00:00Z")
    assert snapshot(log) == before


def test_modified_event_or_missing_history_detected(tmp_path):
    _,m,p = setup(tmp_path)
    log = tmp_path/"log"
    append(log,m,p,W.PENDING_REVIEW)
    append(log,m,p,W.REVIEWED)
    first = log/"review-event-000000.json"
    doc = strict_json(first.read_bytes())
    doc["notes"] = "Changed history"
    first.write_text(canonical(doc))
    with pytest.raises(ValueError):
        read_events(log,m)
    first.unlink()
    with pytest.raises(EvidenceError):
        read_events(log,m)


def test_partial_event_remains_and_blocks_append(tmp_path):
    _,m,p = setup(tmp_path)
    log = tmp_path/"log"
    append(log,m,p,W.PENDING_REVIEW)
    (log/"review-event-000001.json.partial").write_text('{"partial":')
    before = snapshot(log)
    with pytest.raises(EvidenceError):
        append(log,m,p,W.REVIEWED)
    assert snapshot(log) == before


def test_oversized_serialized_event_cannot_corrupt_journal(tmp_path):
    _,m,p = setup(tmp_path)
    follow_up = tuple(RecommendedVerificationAction(instruction="文"*4096) for _ in range(8))
    with pytest.raises(EvidenceError, match="event_size_limit"):
        append(tmp_path/"log",m,p,W.PENDING_REVIEW,follow_up=follow_up)
    assert not (tmp_path/"log").exists()


def test_unknown_follow_up_citation_and_incompatible_manifest(tmp_path):
    _,m,p = setup(tmp_path)
    action = RecommendedVerificationAction(instruction="Inspect",citation_ids=("unknown",))
    with pytest.raises(EvidenceError):
        append(tmp_path/"bad",m,p,W.PENDING_REVIEW,follow_up=(action,))
    log = tmp_path/"log"
    append(log,m,p,W.PENDING_REVIEW)
    other = replace(m,generated_at_utc="2026-10-27T00:00:00Z")
    assert read_events(log,other)
    subset = build_packets(tmp_path/"collection",claim_ids=[p.claim.claim_id])
    with pytest.raises(EvidenceError,match="context"):
        read_events(log,subset)


def test_symlink_and_protected_dirs_no_mutation(tmp_path):
    root,m,p = setup(tmp_path)
    before = snapshot(root)
    with pytest.raises(EvidenceError):
        append(root/"notes",m,p,W.PENDING_REVIEW,protected=(root,))
    log = tmp_path/"log"
    log.mkdir()
    link = tmp_path/"linked"
    link.symlink_to(log,target_is_directory=True)
    with pytest.raises(EvidenceError):
        append(link,m,p,W.PENDING_REVIEW)
    assert not list(log.iterdir()) and snapshot(root) == before


def test_cli_revalidates_bundle_and_regenerates_notes_separately(tmp_path, capsys):
    root,m,p = setup(tmp_path)
    bundle = tmp_path/"bundle"
    write_bundle(bundle,m,render_html(m),protected=(root,))
    original = snapshot(bundle)
    args = ["--root",str(root),"--packet-bundle",str(bundle),"--review-dir",str(tmp_path/"log"),
            "--packet-id",p.packet_id,"--state","pending_review","--reviewer","Label","--note","Inspect","--timestamp","2026-10-27T00:00:00Z"]
    assert main(args) == 0
    assert snapshot(bundle) == original
    from src.build_review_packets import main as build
    assert build(["--root",str(root),"--output-dir",str(tmp_path/"with-notes"),"--review-dir",str(tmp_path/"log")]) == 1
    new,history = read_bundle(tmp_path/"with-notes")
    assert new == m and len(history) == 1


def test_cli_stale_bundle_rejected_and_interruptions(tmp_path, monkeypatch):
    root,m,p = setup(tmp_path)
    bundle = tmp_path/"bundle"
    write_bundle(bundle,m,render_html(m),protected=(root,))
    (root/"c3_attempt_000000.body").write_text("changed")
    args = ["--root",str(root),"--packet-bundle",str(bundle),"--review-dir",str(tmp_path/"log"),
            "--packet-id",p.packet_id,"--state","pending_review","--reviewer","Label","--note","Inspect"]
    assert main(args) == 2
    assert not (tmp_path/"log").exists()


def test_existing_empty_dir_inside_evidence_not_a_review_log(tmp_path):
    root,m,p = setup(tmp_path)
    empty = root/"existing-empty"
    empty.mkdir()
    with pytest.raises(EvidenceError,match="existing_evidence"):
        append(empty,m,p,W.PENDING_REVIEW)
    assert not list(empty.iterdir())


def test_review_context_change_during_validation_rejected(tmp_path,monkeypatch):
    from src.evidence_io import EvidenceRoot
    _,m,p = setup(tmp_path)
    log = tmp_path/"log"
    append(log,m,p,W.PENDING_REVIEW)
    original = EvidenceRoot.read
    def mutate(self,relative,**kw):
        result = original(self,relative,**kw)
        if relative == "review-context.json" and not kw.get("recheck"):
            (log/relative).write_text("{}")
        return result
    monkeypatch.setattr(EvidenceRoot,"read",mutate)
    with pytest.raises(EvidenceError,match="review_log_changed"):
        read_events(log,m)


def test_concurrent_review_writer_lock_refused(tmp_path):
    import fcntl
    from src.evidence_io import EvidenceRoot
    _,m,p = setup(tmp_path)
    log = tmp_path/"log"
    append(log,m,p,W.PENDING_REVIEW)
    before = snapshot(log)
    with EvidenceRoot(log) as root:
        fcntl.flock(root.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            append(log,m,p,W.REVIEWED)
    assert snapshot(log) == before


def test_log_capacity_checked_before_publishing_next_event(tmp_path,monkeypatch):
    import src.review_events as module
    _,m,p = setup(tmp_path)
    log = tmp_path/"log"
    append(log,m,p,W.PENDING_REVIEW)
    before = snapshot(log)
    monkeypatch.setattr(module,"MAX_LOG_BYTES",sum(len(v) for v in before.values())+100)
    with pytest.raises(EvidenceError,match="review_log_size_limit"):
        append(log,m,p,W.REVIEWED)
    assert snapshot(log) == before
