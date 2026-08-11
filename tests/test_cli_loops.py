"""Open loops: problems in open themes with no addressing signal — no
confirmed edge and no live typed candidate pointing at them. Pure graph
query; zero LLM spend."""
from datetime import datetime, timezone

from typer.testing import CliRunner

from alluvia.cli import app
from alluvia.models import Note, Theme
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo

runner = CliRunner()


def _env(tmp_path, monkeypatch):
    db = str(tmp_path / "dev.db")
    monkeypatch.setenv("ALLUVIA_DB", db)
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "dev.toml"))
    conn = connect(db)
    init_schema(conn, embed_dim=8)
    return Repo(conn)


def _problem(nid, text):
    return Note(id=nid, user_id="local", session_id=f"claude-code:s-{nid}",
                span_ref="msg:0", kind="problem", text=text,
                created_at=datetime(2026, 5, 1, tzinfo=timezone.utc))


def test_loops_shows_only_unaddressed_problems(tmp_path, monkeypatch):
    repo = _env(tmp_path, monkeypatch)
    repo.upsert_notes([
        _problem("note:open", "retry storm melts the webhook queue"),
        _problem("note:edged", "cache never expires"),
        _problem("note:cand", "ids trusted from client"),
        _problem("note:muted", "logging is noisy"),
        Note(id="note:idea", user_id="local", session_id="claude-code:s-i",
             span_ref="msg:0", kind="idea", text="an idea, not a problem",
             created_at=datetime(2026, 5, 1, tzinfo=timezone.utc)),
    ])
    repo.replace_themes("local", [
        Theme(id="th:open", user_id="local", label="Queue", summary="s",
              note_ids=["note:open", "note:edged", "note:cand", "note:idea"],
              first_seen=datetime(2026, 4, 1, tzinfo=timezone.utc),
              last_seen=datetime(2026, 7, 1, tzinfo=timezone.utc),
              session_count=4, source_count=1, status="open"),
        Theme(id="th:muted", user_id="local", label="Noise", summary="s",
              note_ids=["note:muted"], session_count=2, source_count=1,
              status="open"),
    ])
    repo.mute_label("local", "Noise")
    # note:edged is addressed by a CONFIRMED edge
    repo.upsert_edges("local", [{
        "id": "edge:1", "subject_id": "note:d1", "relation": "ADDRESSES",
        "object_id": "note:edged", "event_id": None, "weight": 0.9}])
    # note:cand is addressed by a live (pending) candidate
    repo.insert_candidates("local", [{
        "id": "cand:1", "relation": "ADDRESSES", "subject_id": "note:d2",
        "object_id": "note:cand", "score": 0.8, "uncertainty": None,
        "evidence": [], "status": "pending",
        "created_at": "2026-07-17T00:00:00+00:00", "policy_version": "p",
        "why": None}])
    repo.conn.close()
    result = runner.invoke(app, ["loops"])
    assert result.exit_code == 0, result.output
    assert "retry storm melts the webhook queue" in result.output
    assert "cache never expires" not in result.output       # edge-addressed
    assert "ids trusted from client" not in result.output   # candidate-addressed
    assert "logging is noisy" not in result.output          # muted theme
    assert "an idea, not a problem" not in result.output    # not a problem
    assert "Queue" in result.output                          # theme label shown


def test_loops_empty_state(tmp_path, monkeypatch):
    repo = _env(tmp_path, monkeypatch)
    repo.conn.close()
    result = runner.invoke(app, ["loops"])
    assert result.exit_code == 0
    assert "no open loops" in result.output
