"""RecallHit engine: retrieval-only fusion over notes, themes, links, and
status — cited, ranked, zero LLM spend, with a paste-ready handoff."""
import subprocess
from datetime import datetime, timedelta

from alluvia.models import Link, Note, Theme
from alluvia.recall import RecallHit, build_handoff, recall

BASE = datetime(2026, 1, 1)


class QueryEmbedder:
    """'auth'-ish queries embed near auth notes, away from deploy notes."""
    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            base = [1.0, 0.0] if "auth" in t.lower() or "token" in t.lower() \
                else [0.0, 1.0]
            out.append(base + [0.0] * 6)
        return out


def _seed(repo):
    notes = [
        Note(id="note:a1", user_id="local", session_id="claude-code:s1",
             span_ref="msg:0", kind="problem", text="auth token refresh race",
             created_at=BASE),
        Note(id="note:a2", user_id="local", session_id="cursor:s2",
             span_ref="msg:0", kind="insight", text="token rotation lacks lock",
             created_at=BASE + timedelta(days=400)),
        Note(id="note:d1", user_id="local", session_id="claude-code:s3",
             span_ref="msg:0", kind="idea", text="deploy pipeline caching",
             created_at=BASE),
    ]
    repo.upsert_notes(notes)
    emb = QueryEmbedder()
    for n in notes:
        repo.set_embedding("local", n.id, emb.embed([n.text])[0])
    repo.replace_themes("local", [
        Theme(id="theme:0", user_id="local", label="Auth token lifecycle",
              summary="Refresh races and rotation.", note_ids=["note:a1", "note:a2"],
              first_seen=BASE, last_seen=BASE + timedelta(days=400),
              session_count=2, source_count=2, status="open"),
        Theme(id="theme:1", user_id="local", label="Deploy",
              summary="", note_ids=["note:d1"], session_count=1,
              source_count=1, status="unknown"),
    ])
    repo.replace_links("local", [
        Link(id="l1", user_id="local", from_note_id="note:a1",
             to_note_id="note:a2", from_theme_id="theme:0", to_theme_id="theme:0",
             kind="surprise", weight=0.93,
             why="same missing lock, 13 months apart"),
    ])


def test_recall_ranks_matching_theme_with_status_and_citations(repo):
    _seed(repo)
    hits = recall(repo, QueryEmbedder(), "local", "auth token refresh")
    assert hits and hits[0].kind == "theme"
    assert hits[0].title == "Auth token lifecycle"
    assert hits[0].status == "open"
    assert set(hits[0].cites) == {"note:a1", "note:a2"}
    assert any("claude-code" in s for s in hits[0].sources)
    assert hits[0].why                                  # never empty


def test_recall_includes_the_bridge_with_its_why(repo):
    _seed(repo)
    hits = recall(repo, QueryEmbedder(), "local", "token rotation")
    bridge = next(h for h in hits if h.kind == "connection")
    assert "13 months apart" in bridge.why
    assert {"note:a1", "note:a2"} == set(bridge.cites)


def test_recall_excludes_unrelated_material(repo):
    _seed(repo)
    hits = recall(repo, QueryEmbedder(), "local", "auth")
    assert all("Deploy" != h.title for h in hits)


def test_handoff_is_cited_and_caveated(repo):
    _seed(repo)
    hits = recall(repo, QueryEmbedder(), "local", "auth token refresh")
    text = build_handoff("auth token refresh", hits)
    assert "Auth token lifecycle" in text
    assert "note:a1" in text
    assert "verify" in text.lower()                     # context, not ground truth
    assert "[open]" in text


def test_git_cross_reference_labels_conservatively(repo, tmp_path):
    _seed(repo)
    g = tmp_path / "repo"
    g.mkdir()
    for cmd in (["git", "init", "-q"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "--allow-empty",
                 "-m", "fix auth token refresh race with a lock"]):
        subprocess.run(cmd, cwd=g, check=True)
    hits = recall(repo, QueryEmbedder(), "local", "auth token refresh",
                  git_root=str(g))
    top = hits[0]
    assert top.git_ref and "possibly implemented" in top.git_ref
    assert "fix auth token refresh race" in top.git_ref
    # unrelated repos attach nothing
    hits2 = recall(repo, QueryEmbedder(), "local", "auth token refresh")
    assert hits2[0].git_ref is None
