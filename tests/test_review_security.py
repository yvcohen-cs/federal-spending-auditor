"""HTML and output adversarial tests; synthetic sources only."""
import hashlib
from html.parser import HTMLParser
from unittest.mock import Mock

import pytest

from src.build_review_packets import main
from src.evidence_io import EvidenceError, canonical, strict_json
from src.review_packet_builder import build_packets
from src.review_packet_html import render_html, safe_source_url
from src.review_packet_io import read_bundle, write_bundle
from tests.financial_fixtures import financial_scenario
from tests.test_matching_ingestion import collection, snapshot


class Tags(HTMLParser):
    def __init__(self, html):
        super().__init__(); self.tags = []; self.ids = []
        self.feed(html)
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        self.ids.extend(v for k,v in attrs if k == "id")


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<script/>", "//www.fpds.gov/x", "http://www.fpds.gov/x",
    "https://www.fpds.gov.evil.test/x", "https://www.fpds.gov@evil.test/x", "https://evil.test@www.fpds.gov/x",
    "https://www.fpds.gov:22/x", "https://www.fpds.gov\\evil/x", "https://www.fpds.gov/%0aX", "https://[invalid/x",
    "https://www.fpds.gov/\n", "https://127.0.0.1/x", "https://www.fpds.gov./x", "https://www.fpds.gov/%09", "https://www.fpds.gov/%5c"])
def test_unsafe_urls_never_hyperlinked(url):
    assert safe_source_url(url) is None


def test_safe_official_https_links():
    assert safe_source_url("https://www.fpds.gov/ezsearch/FEEDS/ATOM")
    assert safe_source_url("https://www.usaspending.gov/award/example")


def test_source_injection_escaped_and_no_external_assets(tmp_path):
    root = collection(tmp_path, financial_scenario(right_text='</td><script>alert("x")</script><img src="https://evil.test/x">'))
    m = build_packets(root)
    html = render_html(m)
    tags = Tags(html)
    assert not {t for t,_ in tags.tags} & {"script", "img", "iframe", "object", "embed", "form"}
    assert all(not any(k.lower().startswith("on") for k in attrs) for _,attrs in tags.tags)
    assert "&lt;script&gt;" in html
    assert len(tags.ids) == len(set(tags.ids))
    assert any(t == "meta" and a.get("http-equiv") == "Content-Security-Policy" for t,a in tags.tags)
    assert "caption" in {t for t,_ in tags.tags} and 'lang="en"' in html


def test_deterministic_bundle_and_readback(tmp_path):
    root = collection(tmp_path, financial_scenario())
    m = build_packets(root)
    for name in ("one", "two"):
        write_bundle(tmp_path/name, m, render_html(m), protected=(root,))
    assert snapshot(tmp_path/"one") == snapshot(tmp_path/"two")
    assert read_bundle(tmp_path/"one") == (m, ())


def test_coordinated_html_hash_tamper_still_rejected(tmp_path):
    root = collection(tmp_path, financial_scenario())
    m = build_packets(root)
    out = tmp_path/"out"
    write_bundle(out,m,render_html(m),protected=(root,))
    raw = b"<script>alert(1)</script>"
    (out/"review.html").write_bytes(raw)
    commit = strict_json((out/"output-manifest.json").read_bytes())
    commit["files"]["review.html"] = hashlib.sha256(raw).hexdigest()
    (out/"output-manifest.json").write_text(canonical(commit))
    with pytest.raises(EvidenceError, match="safe_projection"):
        read_bundle(out)


def test_output_limits_and_existing_paths_do_not_overwrite(tmp_path):
    root = collection(tmp_path, financial_scenario())
    m = build_packets(root)
    before = snapshot(root)
    with pytest.raises(EvidenceError, match="size_limit"):
        write_bundle(tmp_path/"small",m,render_html(m),protected=(root,),max_output_bytes=1024)
    assert not (tmp_path/"small").exists()
    with pytest.raises(EvidenceError):
        write_bundle(root/"out",m,render_html(m),protected=(root,))
    write_bundle(tmp_path/"out",m,render_html(m),protected=(root,))
    original = snapshot(tmp_path/"out")
    with pytest.raises(OSError):
        write_bundle(tmp_path/"out",m,render_html(m),protected=(root,))
    with pytest.raises(EvidenceError):
        write_bundle(tmp_path/"out"/"nested",m,render_html(m),protected=(root,))
    assert snapshot(root) == before and snapshot(tmp_path/"out") == original


def test_symlink_and_traversal_output_refused(tmp_path):
    root = collection(tmp_path, financial_scenario())
    m = build_packets(root)
    (tmp_path/"link").symlink_to(tmp_path, target_is_directory=True)
    for path in (tmp_path/"link"/"out", tmp_path/"x"/".."/"out"):
        with pytest.raises((EvidenceError,OSError)):
            write_bundle(path,m,render_html(m),protected=(root,))


def test_interrupted_output_is_preserved_and_not_complete(tmp_path, monkeypatch):
    import src.review_packet_io as io
    root = collection(tmp_path, financial_scenario())
    m = build_packets(root)
    original = io.atomic_create
    def interrupt(fd, name, raw):
        if name == "review.html":
            raise KeyboardInterrupt
        original(fd,name,raw)
    monkeypatch.setattr(io,"atomic_create",interrupt)
    with pytest.raises(KeyboardInterrupt):
        write_bundle(tmp_path/"out",m,render_html(m),protected=(root,))
    assert (tmp_path/"out"/"packets.json").exists()
    assert not (tmp_path/"out"/"output-manifest.json").exists()
    with pytest.raises(EvidenceError):
        read_bundle(tmp_path/"out")


def test_cli_outputs_and_interruption(tmp_path, monkeypatch, capsys):
    root = collection(tmp_path, financial_scenario())
    args = ["--root",str(root),"--output-dir",str(tmp_path/"out")]
    assert main(args) == 0
    assert strict_json(capsys.readouterr().out.encode())["selected_claims"] == 3
    assert main(args) == 2
    assert main(["--root",str(root),"--output-dir",str(tmp_path/"other"),"--max-claims","1"]) == 2
    import src.build_review_packets as module
    monkeypatch.setattr(module,"build_packets",Mock(side_effect=KeyboardInterrupt))
    assert main(args) == 130


def test_html_budget_enforced_during_render(tmp_path):
    m = build_packets(collection(tmp_path,financial_scenario()))
    with pytest.raises(EvidenceError,match="html_size_limit"):
        render_html(m,max_bytes=1024)


def test_evidence_mutation_during_projection_is_rejected(tmp_path,monkeypatch):
    import src.review_packet_builder as module
    root = collection(tmp_path,financial_scenario())
    original = module.project_packets
    def mutate(*args,**kw):
        result = original(*args,**kw)
        (root/"c3_attempt_000000.body").write_text("changed")
        return result
    monkeypatch.setattr(module,"project_packets",mutate)
    with pytest.raises(EvidenceError,match="review_source_evidence_changed"):
        build_packets(root)


def test_evidence_mutation_during_html_is_rejected_before_output(tmp_path,monkeypatch):
    import src.build_review_packets as module
    root = collection(tmp_path,financial_scenario())
    original = module.render_html
    def mutate(*args,**kw):
        html = original(*args,**kw)
        (root/"c3_attempt_000000.body").write_text("changed")
        return html
    monkeypatch.setattr(module,"render_html",mutate)
    assert main(["--root",str(root),"--output-dir",str(tmp_path/"out")]) == 2
    assert not (tmp_path/"out").exists()


def test_symlink_in_bundle_or_missing_commit_refused(tmp_path):
    root = collection(tmp_path,financial_scenario())
    m = build_packets(root)
    out = tmp_path/"out"
    write_bundle(out,m,render_html(m),protected=(root,))
    html = out/"review.html"
    copy = tmp_path/"html"
    copy.write_bytes(html.read_bytes())
    html.unlink()
    html.symlink_to(copy)
    with pytest.raises(EvidenceError):
        read_bundle(out)


def test_optional_generation_time_does_not_change_packet_hash(tmp_path,capsys):
    root = collection(tmp_path,financial_scenario())
    assert main(["--root",str(root),"--output-dir",str(tmp_path/"a")]) == 0
    first = strict_json(capsys.readouterr().out.encode())
    assert main(["--root",str(root),"--output-dir",str(tmp_path/"b"),"--generation-time"]) == 0
    second = strict_json(capsys.readouterr().out.encode())
    assert first["substantive_sha256"] == second["substantive_sha256"]


def test_post_publish_output_change_detected_before_commit(tmp_path,monkeypatch):
    import src.review_packet_io as module
    root = collection(tmp_path,financial_scenario())
    m = build_packets(root)
    out = tmp_path/"out"
    original = module.atomic_create
    def mutate(fd,name,raw):
        original(fd,name,raw)
        if name == "packets.json":
            (out/name).write_text("changed")
    monkeypatch.setattr(module,"atomic_create",mutate)
    with pytest.raises(EvidenceError,match="review_output_changed"):
        write_bundle(out,m,render_html(m),protected=(root,))
    assert not (out/"output-manifest.json").exists()


def test_public_bundle_writer_refuses_arbitrary_html_before_creation(tmp_path):
    root = collection(tmp_path,financial_scenario())
    m = build_packets(root)
    with pytest.raises(EvidenceError,match="safe_projection"):
        write_bundle(tmp_path/"out",m,"<script>alert(1)</script>",protected=(root,))
    assert not (tmp_path/"out").exists()
