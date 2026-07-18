"""Recall at every surface: CLI (+handoff), MCP front door, bare-alluvia
now-view. All read-only — no write gate, no LLM spend."""
import json as _json
from types import SimpleNamespace

from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia.mcp_server import recall_now_impl
from tests.test_recall import QueryEmbedder, _seed

runner = CliRunner()


def _wire(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    repo = cli._repo()
    _seed(repo)
    monkeypatch.setattr(cli, "_recall_embedder", lambda: QueryEmbedder())
    return repo


def test_cli_recall_lists_cited_hits(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    r = runner.invoke(cli.app, ["recall", "auth token refresh"])
    assert r.exit_code == 0, r.output
    assert "Auth token lifecycle" in r.output
    assert "why:" in r.output and "sources:" in r.output


def test_cli_recall_handoff_is_paste_ready(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    r = runner.invoke(cli.app, ["recall", "auth token refresh", "--handoff"])
    assert r.exit_code == 0
    assert r.output.startswith("Relevant prior context")
    assert "note:a1" in r.output and "verify" in r.output.lower()


def test_cli_recall_json(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    r = runner.invoke(cli.app, ["recall", "token rotation", "--json"])
    data = _json.loads(r.output)
    assert data["query"] == "token rotation"
    assert data["hits"] and {"kind", "title", "why", "cites"} <= set(data["hits"][0])


def test_mcp_recall_now_shape_and_warnings(repo):
    _seed(repo)
    deps = SimpleNamespace(repo=repo, embedder=QueryEmbedder())
    out = recall_now_impl(deps, "auth token refresh")
    assert out["hits"] and out["hits"][0]["title"] == "Auth token lifecycle"
    assert "handoff" in out
    assert any("no refresh has run yet" in w for w in out["warnings"])
    # writes stay gated, reads are not: no "disabled" error here
    assert "error" not in out


def test_bare_alluvia_prints_now_view(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch)
    r = runner.invoke(cli.app, [])
    assert r.exit_code == 0
    out = r.output.lower()
    assert "unfinished" in out or "open loop" in out
    assert "bridge" in out
    assert "recall" in out                      # teaches the front door


def test_bare_alluvia_empty_store_points_to_quickstart(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    r = runner.invoke(cli.app, [])
    assert r.exit_code == 0
    assert "init" in r.output
