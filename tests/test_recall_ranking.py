"""Ranking on REAL-shaped similarity. Small local embedders give unrelated
text cosines around 0.4–0.5 and related text 0.75+, and cross-source bridge
weights run 1.6–1.8. Recall must rank by the question, refuse junk, and never
let a bridge's weight buy it a slot (the failure measured on the founder's
store, 2026-09-02: the same five bridges for every query)."""
from __future__ import annotations
from datetime import datetime
import math

from alluvia.models import Link, Note, Theme
from alluvia.recall import recall

BASE = datetime(2026, 1, 1)


class RealisticEmbedder:
    """Every text shares a big common component (like a real model's
    'technical English' direction), plus a small topic component: unrelated
    cosine ≈ 0.5, same-topic ≈ 0.85. Calibrated like the shipped embedder."""
    dim = 8
    sim_floor = 0.55
    sim_strong = 0.72

    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            topic = [0.0, 0.0, 0.0]
            if "auth" in low or "token" in low:
                topic[0] = 1.0
            elif "deploy" in low or "cache" in low:
                topic[1] = 1.0
            elif "supabase" in low or "eacces" in low:
                topic[2] = 1.0
            v = [1.0] + topic + [0.0] * 4          # common direction first
            n = math.sqrt(sum(x * x for x in v))
            out.append([x / n for x in v])
        return out


def _seed(repo):
    notes = [
        Note(id="note:a1", user_id="local", session_id="claude-code:s1", span_ref="msg:0",
             kind="problem", text="auth token refresh race", created_at=BASE),
        Note(id="note:a2", user_id="local", session_id="cursor:s2", span_ref="msg:0",
             kind="decision", text="token rotation lock added", created_at=BASE),
        Note(id="note:d1", user_id="local", session_id="claude-code:s3", span_ref="msg:0",
             kind="idea", text="deploy pipeline caching", created_at=BASE),
        Note(id="note:e1", user_id="local", session_id="cursor:s4", span_ref="msg:0",
             kind="problem", text="EACCES running the supabase cli", created_at=BASE),
        Note(id="note:e2", user_id="local", session_id="claude-code:s5", span_ref="msg:0",
             kind="insight", text="supabase permissions in the user namespace", created_at=BASE),
    ]
    repo.upsert_notes(notes)
    emb = RealisticEmbedder()
    for n in notes:
        repo.set_embedding("local", n.id, emb.embed([n.text])[0])
    repo.replace_themes("local", [
        Theme(id="theme:auth", user_id="local", label="Auth token lifecycle", summary="",
              note_ids=["note:a1", "note:a2"], session_count=2, source_count=2, status="open"),
        Theme(id="theme:sb", user_id="local", label="Supabase permissions", summary="",
              note_ids=["note:e1", "note:e2"], session_count=2, source_count=2, status="open"),
    ])
    # the heaviest bridge in the store is about supabase, not auth
    repo.replace_links("local", [
        Link(id="l-sb", user_id="local", from_note_id="note:e1", to_note_id="note:e2",
             from_theme_id="theme:sb", to_theme_id="theme:sb", kind="cross_source_surprise",
             weight=1.81, why="same permission model, 13 months apart"),
        Link(id="l-auth", user_id="local", from_note_id="note:a1", to_note_id="note:a2",
             from_theme_id="theme:auth", to_theme_id="theme:auth", kind="cross_source_surprise",
             weight=1.60, why="same race"),
    ])


def test_unrelated_query_is_refused_despite_high_baseline_similarity(repo):
    _seed(repo)
    assert recall(repo, RealisticEmbedder(), "local", "my grandmother's lasagna recipe") == []


def test_heavy_bridge_never_outranks_the_relevant_theme(repo):
    _seed(repo)
    hits = recall(repo, RealisticEmbedder(), "local", "auth token refresh race")
    assert hits[0].kind == "theme" and hits[0].title == "Auth token lifecycle"
    assert all("note:e1" not in h.cites for h in hits), "the supabase bridge is not about auth"
    assert all(h.confidence in ("strong", "corroborated") for h in hits)


def test_two_different_questions_do_not_share_the_same_bridges(repo):
    _seed(repo)
    a = recall(repo, RealisticEmbedder(), "local", "auth token refresh race")
    b = recall(repo, RealisticEmbedder(), "local", "EACCES supabase cli permissions")
    ca = {tuple(sorted(h.cites)) for h in a if h.kind == "connection"}
    cb = {tuple(sorted(h.cites)) for h in b if h.kind == "connection"}
    assert ca and cb and ca.isdisjoint(cb)


def test_weak_dense_only_matches_are_hidden_by_default(repo):
    _seed(repo)
    # a topic-less question sits between floor and strong for EVERY note
    # (real embedders put unrelated technical text there) with no exact term
    # to vouch for it: hidden unless asked for, and labeled weak when shown
    q = "invalidation strategy for build artifacts"
    assert recall(repo, RealisticEmbedder(), "local", q) == []
    hits = recall(repo, RealisticEmbedder(), "local", q, include_weak=True)
    assert hits and all(h.confidence == "weak" for h in hits)
