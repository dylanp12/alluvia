"""Issue #2 at the MCP and dashboard surfaces: a degraded map must be
distinguishable from a healthy one wherever it is read."""
import json
from types import SimpleNamespace

from alluvia import config
from alluvia.mcp_server import recall_themes_impl, unfinished_threads_impl
from alluvia.models import Theme
from alluvia.web import overview


def _theme(status="unknown"):
    return Theme(id="theme:0", user_id=config.DEFAULT_USER, label="Auth",
                 summary="", note_ids=["n1"], session_count=3, status=status)


def test_mcp_unfinished_empty_with_unknowns_carries_note(repo):
    repo.replace_themes(config.DEFAULT_USER, [_theme("unknown")])
    out = unfinished_threads_impl(SimpleNamespace(repo=repo))
    assert out["threads"] == []
    assert "status" in out["note"] and "refresh" in out["note"]


def test_mcp_unfinished_healthy_empty_has_no_note(repo):
    repo.replace_themes(config.DEFAULT_USER, [_theme("resolved")])
    out = unfinished_threads_impl(SimpleNamespace(repo=repo))
    assert out["threads"] == [] and "note" not in out


def test_mcp_recall_themes_warns_when_degraded(repo):
    repo.replace_themes(config.DEFAULT_USER, [_theme("unknown")])
    repo.set_meta("last_refresh", json.dumps({"degraded": True}))
    out = recall_themes_impl(SimpleNamespace(repo=repo))
    assert out["themes"]
    assert "degraded" in out["warning"].lower()


def test_mcp_recall_themes_no_warning_when_healthy(repo):
    repo.replace_themes(config.DEFAULT_USER, [_theme("open")])
    repo.set_meta("last_refresh", json.dumps({"degraded": False}))
    assert "warning" not in recall_themes_impl(SimpleNamespace(repo=repo))


def test_web_overview_exposes_refresh_health(repo):
    repo.set_meta("last_refresh", json.dumps(
        {"degraded": True, "at": "2026-07-09T12:00:00+00:00",
         "retry_at": "2026-07-09T14:00:00+00:00"}))
    data = overview(repo, config.DEFAULT_USER)
    assert data["refresh"]["degraded"] is True
    assert data["refresh"]["at"].startswith("2026-07-09")


def test_web_overview_without_meta_is_null_not_crash(repo):
    assert overview(repo, config.DEFAULT_USER)["refresh"] is None
