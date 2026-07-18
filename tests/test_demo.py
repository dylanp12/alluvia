"""`alluvia demo`: all four lenses live in seconds — no key, no LLM calls,
never anywhere near the real store."""
import os

from typer.testing import CliRunner

import alluvia.cli as cli

runner = CliRunner()


def _clean_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))            # demo db under fake home
    monkeypatch.delenv("ALLUVIA_DB", raising=False)
    for k in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(cli, "EMBED_DIM", 384)


def test_demo_shows_all_four_lenses_keyless(tmp_path, monkeypatch):
    _clean_env(tmp_path, monkeypatch)
    r = runner.invoke(cli.app, ["demo"])
    assert r.exit_code == 0, r.output
    out = r.output
    assert "themes" in out.lower()
    assert "↔" in out                               # a bridge with two sides
    assert "months apart" in out
    assert "unfinished" in out.lower()
    assert "proposal" in out.lower()
    assert "serve" in out                                # next-step hint
    # demo store exists; the REAL default store was never created
    assert os.path.exists(tmp_path / ".alluvia" / "demo.db")
    assert not os.path.exists(tmp_path / ".alluvia" / "alluvia.db")


def test_demo_is_idempotent_and_cleanable(tmp_path, monkeypatch):
    _clean_env(tmp_path, monkeypatch)
    runner.invoke(cli.app, ["demo"])
    r2 = runner.invoke(cli.app, ["demo"])                # second run: no dupes
    assert r2.exit_code == 0
    rc = runner.invoke(cli.app, ["demo", "--clean"])
    assert rc.exit_code == 0
    assert not os.path.exists(tmp_path / ".alluvia" / "demo.db")
