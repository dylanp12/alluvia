"""`alluvia refresh` carries the cloud once signed in: pull before distilling
(another machine's notes count as done), push after. Signed out, the pause
text says what sign-in would change."""
from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia.llm.client import FakeLLM
from tests.test_cli_degraded import DISTILL, _engine_factory, _seed_logs

runner = CliRunner()


def _signed_in(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("ALLUVIA_CLOUD_SESSION", str(tmp_path / "sess.json"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    from alluvia.cloudclient import save_session
    save_session("https://api.example.com", "tok")


def test_refresh_pulls_before_and_pushes_after(tmp_path, monkeypatch):
    from alluvia import cloud_memory
    _signed_in(tmp_path, monkeypatch)
    order = []
    monkeypatch.setattr(cloud_memory, "pull", lambda repo, user, **kw: order.append("pull") or {
        "ok": True, "received": 2, "notes_added": 1, "sessions_added": 1})
    monkeypatch.setattr(cloud_memory, "push", lambda repo, user, **kw: order.append("push") or {
        "ok": True, "pushed": 9, "notes": 4})
    build = _engine_factory(FakeLLM(DISTILL + [{"label": "Auth", "summary": "a"},
                                               {"label": "Deploy", "summary": "d"}]))

    def build_marked(repo, reporter=None):
        eng = build(repo, reporter)
        real = eng.refresh

        def refresh(*a, **k):
            order.append("refresh")
            return real(*a, **k)
        eng.refresh = refresh
        return eng
    monkeypatch.setattr(cli, "build_engine", build_marked)
    runner.invoke(cli.app, ["ingest", "--source", "claude-code", "--path", str(_seed_logs(tmp_path))])
    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 0, r.output
    assert order == ["pull", "refresh", "push"]
    assert "1 note received" in r.output and "4 notes sent" in r.output


def test_signed_out_pause_names_the_way_out(tmp_path, monkeypatch):
    from tests.test_engine_degraded import ColdAfter
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    monkeypatch.setattr(cli, "build_engine", _engine_factory(ColdAfter(DISTILL[:2])))
    runner.invoke(cli.app, ["ingest", "--source", "claude-code", "--path", str(_seed_logs(tmp_path))])
    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 0, r.output
    assert "paused" in r.output and "alluvia cloud login" in r.output
    assert "memory" not in r.output.lower()          # signed out: nothing about sync
