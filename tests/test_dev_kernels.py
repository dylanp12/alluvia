"""--verbose (surface the engine's logs) and refresh --plan (no-spend preview)."""
import json
import time

from typer.testing import CliRunner

import alluvia.cli as cli

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


class _Hijacked:
    """LLM whose output can't be parsed — engine logs an INFO line for it."""

    def complete_json(self, system, user):
        raise ValueError("json_validate_failed: nope")


def _engine_factory(llm):
    from tests.test_cli_m1 import ScriptedEmbedder
    from alluvia.engine.engine import Engine

    def build(repo, reporter=None):
        return Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)
    return build


def _setup(tmp_path, monkeypatch, llm):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    monkeypatch.setattr(cli, "build_engine", _engine_factory(llm))
    logs = _seed_logs(tmp_path)
    runner.invoke(cli.app, ["ingest", "--source", "claude-code",
                            "--path", str(logs)])


def test_verbose_surfaces_engine_info_logs(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, _Hijacked())
    r = runner.invoke(cli.app, ["--verbose", "refresh"])
    assert r.exit_code == 0, r.output
    assert "zero-note" in r.output               # the INFO line became visible


def test_without_verbose_info_logs_stay_hidden(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, _Hijacked())
    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 0
    assert "zero-note" not in r.output


def test_refresh_plan_previews_without_spending(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)

    def explode(repo, reporter=None):
        raise AssertionError("--plan must not build an engine")
    monkeypatch.setattr(cli, "build_engine", explode)
    logs = _seed_logs(tmp_path)
    runner.invoke(cli.app, ["ingest", "--source", "claude-code",
                            "--path", str(logs)])
    r = runner.invoke(cli.app, ["refresh", "--plan"])
    assert r.exit_code == 0, r.output
    assert "4 session(s)" in r.output
    assert "no LLM calls" in r.output
    repo = cli._repo()
    assert repo.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0


def test_refresh_plan_reports_cooling_models(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    repo = cli._repo()
    repo.llm_health_save("groq", "llama-3.3-70b-versatile",
                         {"cooldown_until": time.time() + 3600})
    r = runner.invoke(cli.app, ["refresh", "--plan"])
    assert r.exit_code == 0
    assert "llama-3.3-70b-versatile" in r.output and "cooling" in r.output
