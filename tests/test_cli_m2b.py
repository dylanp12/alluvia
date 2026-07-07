import json
import os
import sqlite3
from typer.testing import CliRunner
from alluvia.cli import app

runner = CliRunner()


def _mk_fork_root(tmp_path):
    db = tmp_path / "Cursor" / "User" / "workspaceStorage" / "w1" / "state.vscdb"
    os.makedirs(db.parent, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    conn.execute("INSERT INTO ItemTable VALUES (?,?)", (
        "workbench.panel.aichat.view.aichat.chatdata",
        json.dumps({"tabs": [{"tabId": "t1", "bubbles": [
            {"type": "user", "text": "hello cursor"}]}]})))
    conn.commit()
    conn.close()
    return str(tmp_path / "Cursor")


def test_ingest_cursor_source(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "m2b.db"))
    r = runner.invoke(app, ["ingest", "--source", "cursor",
                            "--path", _mk_fork_root(tmp_path)])
    assert r.exit_code == 0, r.output
    assert "1 session" in r.output
    r2 = runner.invoke(app, ["show", "cursor:t1"])
    assert r2.exit_code == 0 and "hello cursor" in r2.output


def test_ingest_chatgpt_export_requires_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "m2b.db"))
    r = runner.invoke(app, ["ingest", "--source", "chatgpt-export"])
    assert r.exit_code != 0                      # --path mandatory for exports


def test_unknown_source_still_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "m2b.db"))
    r = runner.invoke(app, ["ingest", "--source", "nope", "--path", "."])
    assert r.exit_code != 0
