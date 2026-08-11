from datetime import datetime, timezone

from alluvia.mcp_server import tensions_now_impl
from alluvia.models import Note
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo


class _Deps:
    def __init__(self, repo):
        self.repo = repo


def _repo(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn, embed_dim=8)
    return Repo(conn)


def test_tensions_now_returns_findings(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_notes([
        Note(id="note:a", user_id="local", session_id="claude-code:s-a",
             span_ref="msg:1", kind="decision", text="trust the client",
             created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        Note(id="note:b", user_id="local", session_id="cursor:s-b",
             span_ref="msg:3", kind="decision", text="never trust the client",
             created_at=datetime(2026, 2, 1, tzinfo=timezone.utc))])
    repo.insert_candidates("local", [{
        "id": "cand:rel:link:x", "relation": "CONTRADICTS",
        "subject_id": "note:a", "object_id": "note:b", "score": 0.85,
        "uncertainty": None, "evidence": ["claude-code:s-a/msg:1"],
        "status": "pending", "created_at": "2026-07-18T00:00:00+00:00",
        "policy_version": "relate-v1", "why": "they cannot both hold"}])
    out = tensions_now_impl(_Deps(repo))
    assert "error" not in out
    assert len(out["findings"]) == 1
    f = out["findings"][0]
    assert f["id"] == "cand:rel:link:x"
    assert f["relation"] == "CONTRADICTS" and f["confidence"] == 0.85
    assert f["subject"]["text"] == "trust the client"
    assert f["object"]["text"] == "never trust the client"
    assert f["why"] == "they cannot both hold"
    assert f["evidence"] == ["claude-code:s-a/msg:1"]
    assert f["status"] == "pending"


def test_tensions_now_empty_store(tmp_path):
    out = tensions_now_impl(_Deps(_repo(tmp_path)))
    assert out == {"findings": [], "limit": 10}


def test_tensions_now_excludes_dismissed(tmp_path):
    repo = _repo(tmp_path)
    repo.insert_candidates("local", [{
        "id": "cand:d", "relation": "SUPERSEDES", "subject_id": "x",
        "object_id": "y", "score": 0.5, "uncertainty": None, "evidence": [],
        "status": "dismissed", "created_at": "2026-07-18T00:00:00+00:00",
        "policy_version": "relate-v1", "why": None}])
    assert tensions_now_impl(_Deps(repo))["findings"] == []
