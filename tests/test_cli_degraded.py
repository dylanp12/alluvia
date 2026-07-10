"""Issue #2: a degraded refresh must be visible at every surface the user
actually touches — refresh output, themes, unfinished."""
import json

from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia import config
from alluvia.llm.client import FakeLLM
from alluvia.models import Theme

runner = CliRunner()


def _seed_logs(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    for name, content in [("a", "auth token service"), ("b", "auth middleware"),
                          ("c", "deploy to fly"), ("d", "deploy pipeline")]:
        line = json.dumps({"type": "user",
                           "message": {"role": "user", "content": content}})
        (logs / f"{name}.jsonl").write_text(line + "\n")
    return logs


def _engine_factory(llm):
    from tests.test_cli_m1 import ScriptedEmbedder
    from alluvia.engine.engine import Engine

    def build(repo, reporter=None):
        return Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)
    return build


DISTILL = [
    {"notes": [{"kind": "idea", "text": "auth token service", "span": "msg:0"}]},
    {"notes": [{"kind": "idea", "text": "auth middleware", "span": "msg:0"}]},
    {"notes": [{"kind": "idea", "text": "deploy to fly", "span": "msg:0"}]},
    {"notes": [{"kind": "idea", "text": "deploy pipeline", "span": "msg:0"}]},
]


def test_refresh_prints_stage_summary_and_degradation_banner(tmp_path, monkeypatch):
    from tests.test_engine_degraded import ColdAfter
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    monkeypatch.setattr(cli, "build_engine", _engine_factory(ColdAfter(DISTILL)))
    logs = _seed_logs(tmp_path)
    runner.invoke(cli.app, ["ingest", "--source", "claude-code", "--path", str(logs)])

    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 0, r.output
    assert "themes: 2" in r.output
    assert "2 pending" in r.output                    # labels that never got the LLM
    assert "rate-limited" in r.output                 # the banner names the cause
    assert "re-run" in r.output.lower()               # ...and the remedy


def test_refresh_healthy_prints_summary_without_banner(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    llm = FakeLLM(DISTILL + [{"label": "Auth", "summary": "a"},
                             {"label": "Deploy", "summary": "d"}])
    monkeypatch.setattr(cli, "build_engine", _engine_factory(llm))
    logs = _seed_logs(tmp_path)
    runner.invoke(cli.app, ["ingest", "--source", "claude-code", "--path", str(logs)])

    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 0, r.output
    assert "themes: 2" in r.output
    assert "labels" in r.output                       # stage summary always shown
    assert "rate-limited" not in r.output             # no banner on a healthy run


def _seed_theme(monkeypatch, tmp_path, status="unknown", meta=None):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    repo = cli._repo()
    repo.replace_themes(config.DEFAULT_USER, [
        Theme(id="theme:0", user_id=config.DEFAULT_USER, label="Auth",
              summary="", note_ids=["n1"], session_count=3, status=status)])
    if meta:
        repo.set_meta("last_refresh", json.dumps(meta))
    return repo


def test_themes_shows_hint_when_last_refresh_degraded(tmp_path, monkeypatch):
    _seed_theme(monkeypatch, tmp_path, meta={"degraded": True,
                                             "retry_at": "2026-07-09T14:00:00+00:00"})
    r = runner.invoke(cli.app, ["themes"])
    assert r.exit_code == 0
    assert "degraded" in r.output.lower()
    assert "refresh" in r.output                      # tells the user the remedy


def test_unfinished_explains_all_unknown_instead_of_pretending_empty(tmp_path,
                                                                     monkeypatch):
    _seed_theme(monkeypatch, tmp_path, status="unknown")
    r = runner.invoke(cli.app, ["unfinished"])
    assert r.exit_code == 0
    # the truth is "the classifier never ran", not "you have no unfinished threads"
    assert "status" in r.output.lower()
    assert "refresh" in r.output


def test_unfinished_healthy_empty_keeps_plain_message(tmp_path, monkeypatch):
    _seed_theme(monkeypatch, tmp_path, status="resolved")
    r = runner.invoke(cli.app, ["unfinished"])
    assert r.exit_code == 0
    assert "no unfinished threads" in r.output
