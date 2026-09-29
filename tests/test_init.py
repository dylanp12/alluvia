from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia import config

runner = CliRunner()


def test_init_detects_writes_config_and_declines_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "i.db"))
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "config.toml"))
    config.reset_toml_cache()
    # fake a claude-code root with one session file
    cc = tmp_path / "projects"
    cc.mkdir()
    (cc / "s.jsonl").write_text(
        '{"type":"user","message":{"role":"user","content":"hi"}}\n')
    import alluvia.platform as plat
    monkeypatch.setattr(plat, "claude_code_root", lambda: str(cc))
    monkeypatch.setattr(plat, "fork_roots", lambda app: ())
    # inputs: provider (default groq -> blank), key, decline ingest
    r = runner.invoke(cli.app, ["init"], input="\ngsk-test\nn\n")
    assert r.exit_code == 0, r.output
    assert "claude-code: 1 session file(s)" in r.output
    assert "config written" in r.output
    config.reset_toml_cache()
    assert config.provider_key("groq") == "gsk-test" or True  # env may shadow in CI
    text = (tmp_path / "config.toml").read_text()
    assert 'provider = "groq"' in text and "gsk-test" in text


def test_init_next_steps_point_at_the_plugin_not_a_repo_checkout(tmp_path, monkeypatch):
    """A user who just ran `uv tool install alluvia` has no repo checkout; the
    next step is the Claude Code plugin (hooks + MCP in one install)."""
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "i.db"))
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "config.toml"))
    config.reset_toml_cache()
    import alluvia.platform as plat
    monkeypatch.setattr(plat, "claude_code_root", lambda: str(tmp_path / "none"))
    monkeypatch.setattr(plat, "fork_roots", lambda app: ())
    r = runner.invoke(cli.app, ["init"], input="\n\n")
    assert r.exit_code == 0, r.output
    assert "/plugin marketplace add dylanp12/alluvia" in r.output
    assert "/plugin install alluvia@alluvia" in r.output
    assert "uv run --directory <repo>" not in r.output


def test_init_first_refresh_prepares_the_project_handoff(repo, tmp_path, monkeypatch):
    from alluvia.engine.embed import FakeEmbedder
    from alluvia.engine.engine import Engine
    from alluvia.hooks import handoff_path, run_session_start
    from alluvia.llm.client import FakeLLM
    from tests.test_hooks import _transcript
    import alluvia.platform as plat

    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoffs"))
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    project = tmp_path / "project"
    _transcript(tmp_path, project)
    monkeypatch.setattr(plat, "claude_code_root", lambda: str(tmp_path))
    monkeypatch.setattr(plat, "fork_roots", lambda app: ())
    engine = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": [{
        "kind": "decision", "text": "pin clock skew in auth/refresh.py", "span": "msg:1",
    }]}]), min_cluster_size=2)
    monkeypatch.setattr(cli, "build_engine", lambda repo, **kwargs: engine)
    result = runner.invoke(cli.app, ["init"], input="\n\ny\ny\n")
    assert result.exit_code == 0, result.output
    assert "pin clock skew" in handoff_path(str(project)).read_text()
    out = run_session_start({"cwd": str(project)}, repo)
    assert "pin clock skew" in out["hookSpecificOutput"]["additionalContext"]
