"""Bundle builder: policy-filtered, secret-scrubbed derived memory."""
from datetime import datetime, timezone

from alluvia.cloudsync.bundle import build_bundle, preview
from alluvia.cloudsync.policy import Policy
from alluvia.models import Link, Message, Note, RawSession, Theme, content_hash


def _seed(repo):
    for src, nid in [("claude-code", "s1"), ("chatgpt-export", "s2")]:
        msgs = [Message(role="user", text="secret " + "sk_live_" + "A" * 24 + " and an idea")]
        repo.upsert_session(RawSession(id=f"{src}:{nid}", user_id="local",
            source=src, native_id=nid, title="t", started_at=None,
            ended_at=None, messages=msgs, content_hash=content_hash(msgs)))
    repo.upsert_notes([
        Note(id="note:1", user_id="local", session_id="claude-code:s1",
             span_ref="msg:0", kind="idea", text="rotate the " + "sk_live_" + "A" * 24 + " key",
             created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        Note(id="note:2", user_id="local", session_id="chatgpt-export:s2",
             span_ref="msg:0", kind="idea", text="chatgpt idea", created_at=None)])
    repo.set_embedding("local", "note:1", [0.1] * 8)
    repo.set_embedding("local", "note:2", [0.2] * 8)
    repo.replace_themes("local", [Theme(id="theme:0", user_id="local",
        label="Keys", summary="", note_ids=["note:1"], session_count=1,
        source_count=1, status="open")])
    repo.replace_links("local", [])


def test_derived_bundle_scrubs_secrets_and_carries_embeddings(repo):
    _seed(repo)
    p = Policy(default="derived_only", per_source={})
    b = build_bundle(repo, "local", p)
    texts = {n["id"]: n["text"] for n in b["notes"]}
    assert ("sk_live_" + "A" * 24) not in texts["note:1"]       # scrubbed
    assert "note:1" in b["embeddings"] and len(b["embeddings"]["note:1"]) == 8
    assert {s["id"] for s in b["sessions"]} >= {"claude-code:s1"}
    assert all("messages" not in s for s in b["sessions"])   # metadata only
    assert b["themes"][0]["label"] == "Keys"


def test_none_mode_excludes_a_source(repo):
    _seed(repo)
    p = Policy(default="derived_only", per_source={"chatgpt-export": "none"})
    b = build_bundle(repo, "local", p)
    note_ids = {n["id"] for n in b["notes"]}
    assert "note:1" in note_ids and "note:2" not in note_ids
    assert all(s["source"] != "chatgpt-export" for s in b["sessions"])


def test_excerpt_mode_adds_scrubbed_excerpts(repo):
    _seed(repo)
    p = Policy(default="excerpt", per_source={})
    b = build_bundle(repo, "local", p)
    assert "note:1" in b["excerpts"]
    assert ("sk_live_" + "A" * 24) not in b["excerpts"]["note:1"]    # scrubbed


def test_preview_summarizes_counts(repo):
    _seed(repo)
    b = build_bundle(repo, "local", Policy(default="derived_only", per_source={}))
    text = preview(b)
    assert "notes" in text and "2" in text
    assert "raw sessions" in text.lower() or "0 raw" in text.lower()
