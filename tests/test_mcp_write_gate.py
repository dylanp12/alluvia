"""MCP write/spend tools are opt-in: surprise writes and spending must be
impossible, not merely detectable. Read tools are always available."""
from types import SimpleNamespace

from alluvia import config
from alluvia.mcp_server import (propose_next_impl, rate_proposal_impl,
                                recall_themes_impl)


def _deps(repo):
    return SimpleNamespace(repo=repo)


def test_writes_disabled_by_default(repo, monkeypatch):
    monkeypatch.delenv("ALLUVIA_MCP_WRITES", raising=False)
    out = rate_proposal_impl(_deps(repo), "prop:x", "keep")
    assert "disabled" in out["error"] and "writes" in out["error"]
    out = propose_next_impl(_deps(repo))
    assert "disabled" in out["error"]


def test_reads_always_work(repo, monkeypatch):
    monkeypatch.delenv("ALLUVIA_MCP_WRITES", raising=False)
    assert "error" not in recall_themes_impl(_deps(repo))


def test_env_enables_writes(repo, monkeypatch):
    monkeypatch.setenv("ALLUVIA_MCP_WRITES", "1")
    out = rate_proposal_impl(_deps(repo), "prop:missing", "keep")
    assert out["error"] == "no proposal prop:missing"     # past the gate


def test_toml_enables_writes(repo, tmp_path, monkeypatch):
    monkeypatch.delenv("ALLUVIA_MCP_WRITES", raising=False)
    cfg = tmp_path / "config.toml"
    cfg.write_text("[mcp]\nwrites = true\n")
    monkeypatch.setenv("ALLUVIA_CONFIG", str(cfg))
    config.reset_toml_cache()
    out = rate_proposal_impl(_deps(repo), "prop:missing", "keep")
    assert out["error"] == "no proposal prop:missing"


def test_rate_context_is_gated_and_needs_a_delivered_handoff(repo, monkeypatch, tmp_path):
    from alluvia.mcp_server import rate_context_impl
    monkeypatch.delenv("ALLUVIA_MCP_WRITES", raising=False)
    out = rate_context_impl(_deps(repo), "kept", project=str(tmp_path))
    assert "disabled" in out["error"]
    monkeypatch.setenv("ALLUVIA_MCP_WRITES", "1")
    out = rate_context_impl(_deps(repo), "kept", project=str(tmp_path))
    assert "no handoff" in out["error"]
    eid = repo.record_handoff_event("local", str(tmp_path), ["n:1"], chars=5, source="startup")
    out = rate_context_impl(_deps(repo), "noise", note_id="n:1", project=str(tmp_path))
    assert out == {"event": eid, "verdict": "noise", "note_id": "n:1", "rated_via": "mcp"}
    assert rate_context_impl(_deps(repo), "meh", project=str(tmp_path))["error"].startswith("verdict must be")
