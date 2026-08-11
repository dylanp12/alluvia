"""The exporter compiles raw/derived/judgment rows into a portable graph
bundle: deterministic, provenance-preserving, product-neutral."""
import gzip
import json
from datetime import datetime, timezone

from alluvia import graph_export
from alluvia.models import (ExtractionRun, Link, Message, Note, Proposal,
                            RawSession, Theme, content_hash)

NOW = "2026-07-17T00:00:00+00:00"


def _seed(repo):
    msgs = [Message(role="user", text="hello world")]
    repo.upsert_session(RawSession(
        id="claude-code:s1", user_id="local", source="claude-code", native_id="s1",
        title="Session One", started_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        ended_at=None, messages=msgs, content_hash=content_hash(msgs)))
    repo.record_extraction_run(ExtractionRun(
        id="run:r1", user_id="local", session_id="claude-code:s1", stage="distill",
        model="m-live", pipeline_version=3, prompt_hash="ph", created_at=NOW))
    repo.upsert_notes([
        Note(id="note:a", user_id="local", session_id="claude-code:s1",
             span_ref="msg:0", kind="problem", text="upload trusts client id",
             created_at=datetime(2026, 6, 1, tzinfo=timezone.utc), run_id="run:r1"),
        Note(id="note:b", user_id="local", session_id="claude-code:s1",
             span_ref="msg:0", kind="insight", text="ownership must be server-side",
             created_at=datetime(2026, 6, 1, tzinfo=timezone.utc)),
    ])
    repo.replace_themes("local", [Theme(
        id="theme:0", user_id="local", label="auth", summary="s",
        note_ids=["note:a", "note:b"], session_count=1, source_count=1,
        status="open")])
    repo.replace_links("local", [Link(
        id="link:x", user_id="local", from_note_id="note:a", to_note_id="note:b",
        from_theme_id="theme:0", to_theme_id="theme:0",
        kind="cross_source_surprise", weight=2.5, why="same invariant")])
    repo.insert_proposal(Proposal(
        id="prop:1", user_id="local", created_at=NOW, kind="link",
        source_ref="link:x", source_hash="h", title="T", text="X", next_step="do",
        cites=["note:a"], novelty_sim=None, feasibility=None, risk=None,
        model="m-live", outcome="kept"))


def test_bundle_shape_and_provenance(repo):
    _seed(repo)
    manifest, nodes, events, judgments = graph_export.build_bundle(
        repo, "local", now_iso=NOW)
    assert manifest["contract_version"] == "0.1.0"
    assert manifest["generator"] == "alluvia" and manifest["created_at"] == NOW
    by_id = {n["id"]: n for n in nodes}
    assert by_id["claude-code:s1"]["type"] == "Session"
    assert by_id["note:a"]["type"] == "Problem"
    assert by_id["note:b"]["type"] == "Lesson"          # insight -> Lesson
    assert by_id["theme:0"]["type"] == "Theme"
    obs = [e for e in events if e["event_type"] == "observation"]
    assert {e["participants"][0][1] for e in obs} == {"note:a", "note:b"}
    a_obs = next(e for e in obs if e["participants"][0][1] == "note:a")
    assert a_obs["extraction"]["model"] == "m-live"
    assert a_obs["extraction"]["run_id"] == "run:r1"
    assert a_obs["evidence"] == ["claude-code:s1/msg:0"]
    b_obs = next(e for e in obs if e["participants"][0][1] == "note:b")
    assert b_obs["extraction"]["run_id"] is None        # legacy note, honest null
    link_ev = [e for e in events if e["relation"] == "open:cross-source-surprise"]
    assert len(link_ev) == 1 and link_ev[0]["attrs"]["weight"] == 2.5
    part_of = [e for e in events if e["relation"] == "PART_OF"]
    assert len(part_of) == 2
    assert judgments and judgments[0]["id"] == "prop:1"
    assert judgments[0]["outcome"] == "kept"


def test_judgments_can_be_excluded(repo):
    _seed(repo)
    *_, judgments = graph_export.build_bundle(repo, "local", now_iso=NOW,
                                              include_judgments=False)
    assert judgments is None


def test_write_bundle_is_deterministic(repo, tmp_path):
    _seed(repo)
    for d in ("x", "y"):
        manifest, nodes, events, judgments = graph_export.build_bundle(
            repo, "local", now_iso=NOW)
        graph_export.write_bundle(tmp_path / d, manifest, nodes, events, judgments)
    for fn in ("contract.json", "nodes.jsonl.gz", "events.jsonl.gz",
               "judgments.jsonl.gz"):
        assert (tmp_path / "x" / fn).read_bytes() == \
            (tmp_path / "y" / fn).read_bytes(), fn


def test_bundle_files_parse(repo, tmp_path):
    _seed(repo)
    manifest, nodes, events, judgments = graph_export.build_bundle(
        repo, "local", now_iso=NOW)
    graph_export.write_bundle(tmp_path / "b", manifest, nodes, events, judgments)
    with gzip.open(tmp_path / "b" / "nodes.jsonl.gz", "rt") as f:
        parsed = [json.loads(line) for line in f]
    assert [n["id"] for n in parsed] == sorted(n["id"] for n in parsed)
