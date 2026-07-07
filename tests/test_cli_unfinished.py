from datetime import datetime
from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo
from alluvia.models import Theme

runner = CliRunner()


def _seed(dbpath):
    conn = connect(dbpath); init_schema(conn, embed_dim=8); repo = Repo(conn)
    repo.replace_themes("local", [
        Theme(id="t0", user_id="local", label="Auth", summary="auth stuff",
              note_ids=["n1"], first_seen=datetime(2026, 1, 1), last_seen=datetime(2026, 5, 1),
              session_count=5, source_count=1, status="open"),
        Theme(id="t1", user_id="local", label="Deploy", summary="done",
              note_ids=["n2"], session_count=3, source_count=1, status="resolved"),
        Theme(id="t2", user_id="local", label="Old", summary="stale",
              note_ids=["n3"], session_count=2, source_count=1, status="dormant"),
    ])


def test_unfinished_lists_open_only_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "u.db"))
    _seed(str(tmp_path / "u.db"))
    r = runner.invoke(cli.app, ["unfinished"])
    assert r.exit_code == 0, r.output
    assert "Auth" in r.output
    assert "Deploy" not in r.output          # resolved hidden
    assert "Old" not in r.output             # dormant hidden by default
    r2 = runner.invoke(cli.app, ["unfinished", "--include-dormant"])
    assert "Old" in r2.output                # dormant shown with flag
