import os
from datetime import datetime, timezone

from typer.testing import CliRunner

from alluvia.cli import app
from alluvia.models import Message, Note, RawSession, content_hash
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo

runner = CliRunner()


def _seed(db_path):
    conn = connect(db_path)
    init_schema(conn, embed_dim=8)
    repo = Repo(conn)
    msgs = [Message(role="user", text="hi")]
    repo.upsert_session(RawSession(
        id="claude-code:s1", user_id="local", source="claude-code",
        native_id="s1", title="t",
        started_at=datetime(2026, 6, 1, tzinfo=timezone.utc), ended_at=None,
        messages=msgs, content_hash=content_hash(msgs)))
    repo.upsert_notes([Note(
        id="note:a", user_id="local", session_id="claude-code:s1",
        span_ref="msg:0", kind="problem", text="p",
        created_at=datetime(2026, 6, 1, tzinfo=timezone.utc))])
    conn.close()


def test_export_graph_writes_a_bundle(tmp_path, monkeypatch):
    db = str(tmp_path / "dev.db")
    monkeypatch.setenv("ALLUVIA_DB", db)
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "dev.toml"))
    _seed(db)
    out = str(tmp_path / "bundle")
    result = runner.invoke(app, ["export-graph", "--out", out])
    assert result.exit_code == 0, result.output
    for fn in ("contract.json", "nodes.jsonl.gz", "events.jsonl.gz",
               "judgments.jsonl.gz"):
        assert os.path.exists(os.path.join(out, fn)), fn
    assert "wrote graph bundle" in result.output


def test_no_judgments_flag(tmp_path, monkeypatch):
    db = str(tmp_path / "dev.db")
    monkeypatch.setenv("ALLUVIA_DB", db)
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "dev.toml"))
    _seed(db)
    out = str(tmp_path / "bundle2")
    result = runner.invoke(app, ["export-graph", "--out", out, "--no-judgments"])
    assert result.exit_code == 0, result.output
    assert not os.path.exists(os.path.join(out, "judgments.jsonl.gz"))
