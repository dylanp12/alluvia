"""Recall hits carry receipts — the verbatim quote behind each cite — and
every surface that renders hits can show them."""
from __future__ import annotations
from datetime import datetime
from types import SimpleNamespace

from alluvia.models import Message, Note, RawSession
from alluvia.recall import build_handoff, recall

BASE = datetime(2026, 1, 1)


class AuthEmbedder:
    dim = 8

    def embed(self, texts):
        return [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                if ("auth" in t.lower() or "token" in t.lower())
                else [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                for t in texts]


def _seed(repo):
    repo.upsert_session(RawSession(
        id="claude-code:s1", user_id="local", source="claude-code",
        native_id="n1", title="auth debugging", started_at=BASE, ended_at=BASE,
        messages=[Message(role="user", text="two tabs race the refresh", ts=BASE),
                  Message(role="assistant",
                          text="fixed by pinning clock skew in auth/refresh.py",
                          ts=BASE)],
        content_hash="h1"))
    notes = [
        Note(id="note:a1", user_id="local", session_id="claude-code:s1",
             span_ref="msg:1", kind="insight",
             text="auth token refresh race fixed via clock skew pin",
             created_at=BASE),
        Note(id="note:a2", user_id="local", session_id="claude-code:s1",
             span_ref="msg:0", kind="problem",
             text="auth token refresh race seen across tabs", created_at=BASE),
    ]
    repo.upsert_notes(notes)
    emb = AuthEmbedder()
    for n in notes:
        repo.set_embedding("local", n.id, emb.embed([n.text])[0])


def test_hits_quote_the_raw_session(repo):
    _seed(repo)
    hits = recall(repo, AuthEmbedder(), "local", "auth token refresh")
    assert hits
    quotes = [r["quote"] for h in hits for r in h.receipts]
    assert any("pinning clock skew in auth/refresh.py" in q for q in quotes)
    # every receipt names the note it quotes
    assert all(r["note"] for h in hits for r in h.receipts)


def test_receipts_are_bounded_per_hit(repo):
    _seed(repo)
    hits = recall(repo, AuthEmbedder(), "local", "auth token refresh")
    assert all(len(h.receipts) <= 2 for h in hits)


class _NoReceipts:
    """A store without the receipt seam (e.g. a team store with no synced
    excerpts) — recall must degrade to receiptless hits, not crash."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name == "note_excerpt":
            raise AttributeError(name)
        return getattr(self._inner, name)


def test_recall_degrades_without_the_receipt_seam(repo):
    _seed(repo)
    hits = recall(_NoReceipts(repo), AuthEmbedder(), "local", "auth token refresh")
    assert hits and all(h.receipts == [] for h in hits)


def test_handoff_includes_the_receipt_quote(repo):
    _seed(repo)
    hits = recall(repo, AuthEmbedder(), "local", "auth token refresh")
    text = build_handoff("auth token refresh", hits)
    assert 'receipt: "' in text
    assert "pinning clock skew" in text


def test_mcp_recall_now_serializes_receipts(repo):
    _seed(repo)
    from alluvia.mcp_server import recall_now_impl
    out = recall_now_impl(SimpleNamespace(repo=repo, embedder=AuthEmbedder()),
                          "auth token refresh")
    assert "error" not in out
    receipts = [r for h in out["hits"] for r in h.get("receipts", [])]
    assert any("pinning clock skew" in r["quote"] for r in receipts)
