from datetime import datetime, timezone

from typer.testing import CliRunner

from alluvia.cli import app
from alluvia.models import Note
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


def _note(nid, text):
    return Note(id=nid, user_id="local", session_id=f"claude-code:s-{nid}",
                span_ref="msg:1", kind="decision", text=text,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_tensions_lists_typed_candidates(tmp_path, monkeypatch):
    repo = _env(tmp_path, monkeypatch)
    repo.upsert_notes([_note("note:a", "trust the client id"),
                       _note("note:b", "never trust client ids")])
    repo.insert_candidates("local", [{
        "id": "cand:rel:link:x", "relation": "CONTRADICTS",
        "subject_id": "note:a", "object_id": "note:b", "score": 0.9,
        "uncertainty": None, "evidence": ["claude-code:s-note:a/msg:1"],
        "status": "pending", "created_at": "2026-07-17T00:00:00+00:00",
        "policy_version": "relate-v1", "why": "they cannot both hold"}])
    repo.conn.close()
    result = runner.invoke(app, ["tensions"])
    assert result.exit_code == 0, result.output
    assert "CONTRADICTS" in result.output
    assert "trust the client id" in result.output
    assert "never trust client ids" in result.output
    assert "they cannot both hold" in result.output
    assert "0.9" in result.output
    assert "claude-code:s-note:a/msg:1" in result.output


def test_tensions_empty_state_points_at_scan(tmp_path, monkeypatch):
    repo = _env(tmp_path, monkeypatch)
    repo.conn.close()
    result = runner.invoke(app, ["tensions"])
    assert result.exit_code == 0, result.output
    assert "--scan" in result.output


def test_tensions_keep_promotes(tmp_path, monkeypatch):
    repo = _env(tmp_path, monkeypatch)
    repo.upsert_notes([_note("note:a", "trust the client id"),
                       _note("note:b", "never trust client ids")])
    repo.insert_candidates("local", [{
        "id": "cand:rel:link:x", "relation": "CONTRADICTS",
        "subject_id": "note:a", "object_id": "note:b", "score": 0.9,
        "uncertainty": None, "evidence": ["claude-code:s-note:a/msg:1"],
        "status": "pending", "created_at": "2026-07-17T00:00:00+00:00",
        "policy_version": "relate-v1", "why": "w"}])
    repo.conn.close()
    result = runner.invoke(app, ["tensions", "--keep", "cand:rel:link:x"])
    assert result.exit_code == 0, result.output
    assert "confirmed" in result.output
    listing = runner.invoke(app, ["tensions"])
    assert "cand:rel:link:x" in listing.output       # id shown for rating
    assert "✓" in listing.output


def test_tensions_bad_id_exits_nonzero(tmp_path, monkeypatch):
    repo = _env(tmp_path, monkeypatch)
    repo.conn.close()
    result = runner.invoke(app, ["tensions", "--dismiss", "cand:rel:nope"])
    assert result.exit_code == 1
