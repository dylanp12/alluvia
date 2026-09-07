"""`alluvia cloud sync` UX: previews, confirms, pushes — one command."""
from typer.testing import CliRunner

import alluvia.cli as cli

runner = CliRunner()


def _seed(monkeypatch, tmp_path, signed_in=True):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("ALLUVIA_CLOUD_SESSION", str(tmp_path / "sess.json"))
    monkeypatch.setenv("ALLUVIA_CLOUD_CONFIG", str(tmp_path / "cloud.toml"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    if signed_in:
        from alluvia.cloudclient import save_session
        save_session("https://api.example.com", "tok")
    from tests.test_cloud_bundle import _seed as seed_repo
    seed_repo(cli._repo())


def test_sync_previews_and_pushes_on_confirm(tmp_path, monkeypatch):
    _seed(monkeypatch, tmp_path)
    pushed = {}
    monkeypatch.setattr("alluvia.cloudclient.push_bundle",
                        lambda url, tok, b: pushed.update(b) or {"notes": len(b["notes"])})
    r = runner.invoke(cli.app, ["cloud", "sync", "--yes"])
    assert r.exit_code == 0, r.output
    assert "will upload" in r.output and "synced" in r.output
    assert "notes" in pushed                          # a real bundle was pushed


def test_sync_without_login_exits_cleanly(tmp_path, monkeypatch):
    _seed(monkeypatch, tmp_path, signed_in=False)
    r = runner.invoke(cli.app, ["cloud", "sync", "--yes"])
    assert r.exit_code == 1 and "login" in r.output


def test_status_and_logout(tmp_path, monkeypatch):
    _seed(monkeypatch, tmp_path)
    assert "signed in" in runner.invoke(cli.app, ["cloud", "status"]).output
    runner.invoke(cli.app, ["cloud", "logout"])
    assert "not signed in" in runner.invoke(cli.app, ["cloud", "status"]).output


def test_login_establishes_a_session(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_CLOUD_SESSION", str(tmp_path / "sess.json"))
    r = runner.invoke(cli.app, ["cloud", "login", "--url",
                                "https://api.example.com", "--token", "abc"])
    assert r.exit_code == 0 and "signed in" in r.output
    from alluvia.cloudclient import load_session
    assert load_session()["token"] == "abc"


def test_status_shows_plan_budget_and_last_memory_sync(tmp_path, monkeypatch):
    import json
    from alluvia import cloudclient
    from alluvia.cloud_memory import LAST_SYNC
    _seed(monkeypatch, tmp_path)
    monkeypatch.setattr(cloudclient, "get_billing", lambda url, tok: {
        "plan": "free", "status": None, "usage": {"spend": 1.25, "budget": 5.0}})
    from datetime import datetime, timedelta, timezone
    at = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    cli._repo().set_meta(LAST_SYNC, json.dumps({"at": at, "notes_pushed": 12, "notes_pulled": 2}))
    out = runner.invoke(cli.app, ["cloud", "status"]).output
    assert "signed in" in out and "Free" in out
    assert "$1.25 of $5.00 this month" in out
    assert "12 notes" in out and "3 min ago" in out


def test_status_stays_useful_offline(tmp_path, monkeypatch):
    from alluvia import cloudclient
    _seed(monkeypatch, tmp_path)
    def down(url, tok):
        raise cloudclient.SyncError("cannot reach https://api.example.com: timed out")
    monkeypatch.setattr(cloudclient, "get_billing", down)
    r = runner.invoke(cli.app, ["cloud", "status"])
    assert r.exit_code == 0 and "signed in" in r.output
    assert "unavailable" in r.output and "not synced yet" in r.output


def test_login_syncs_memory_right_away(tmp_path, monkeypatch):
    from alluvia import cloud_memory
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("ALLUVIA_CLOUD_SESSION", str(tmp_path / "sess.json"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    monkeypatch.setattr(cloud_memory, "sync", lambda repo, user, **kw: {
        "ok": True, "pull": {"ok": True, "notes_added": 3, "sessions_added": 1},
        "push": {"ok": True, "notes": 7}})
    r = runner.invoke(cli.app, ["cloud", "login", "--url", "https://api.example.com", "--token", "abc"])
    assert r.exit_code == 0, r.output
    assert "3 notes received" in r.output and "7 notes sent" in r.output


def test_sync_also_pushes_memory(tmp_path, monkeypatch):
    from alluvia import cloud_memory
    _seed(monkeypatch, tmp_path)
    monkeypatch.setattr("alluvia.cloudclient.push_bundle", lambda url, tok, b: {"notes": 1})
    monkeypatch.setattr(cloud_memory, "push", lambda repo, user, **kw: {"ok": True, "pushed": 9, "notes": 4})
    r = runner.invoke(cli.app, ["cloud", "sync", "--yes"])
    assert r.exit_code == 0, r.output
    assert "memory: 4 notes" in r.output
