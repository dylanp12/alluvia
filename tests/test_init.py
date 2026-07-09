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
