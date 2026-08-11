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
