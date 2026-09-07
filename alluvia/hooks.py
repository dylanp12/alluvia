"""Claude Code hook handlers.

session-start: read the cached handoff for the repo the session runs in and
hand it back as `additionalContext`. No model, no LLM, no network — a few
milliseconds. Nothing cached → nothing injected.

session-end / pre-compact: ingest the live transcript (one file, one
session), distill that session, embed its notes, rebuild this repo's
handoff. A cold provider keeps the raw session and rebuilds the handoff from
what is already known; the pending count is stated in the handoff itself.

Hooks must never break the user's session: the CLI wrapper swallows every
error into hooks.log and exits 0."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from alluvia import config
from alluvia.handoff import build_project_handoff
from alluvia.projects import project_key, project_root


def parse_payload(raw: str) -> dict:
    try:
        obj = json.loads(raw) if raw and raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def handoff_path(project: str) -> Path:
    return Path(config.handoff_dir()) / f"{project_key(project)}.md"


def _project_of(payload: dict) -> str | None:
    return project_root(payload.get("cwd") or os.getcwd())


def _stamp(repo, key: str) -> None:
    repo.set_meta(key, datetime.now(timezone.utc).isoformat())


def run_session_start(payload: dict, repo) -> dict | None:
    project = _project_of(payload)
    if not project:
        return None
    path = handoff_path(project)
    _stamp(repo, "hook:last_run")
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                   "additionalContext": text}}


def write_handoff(repo, user_id: str, project: str, now=None) -> bool:
    text = build_project_handoff(repo, user_id, project, now=now)
    path = handoff_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        if path.exists():
            path.unlink()
        return False
    path.write_text(text, encoding="utf-8")
    return True


def run_capture(payload: dict, repo, engine, now=None) -> dict:
    """Shared by session-end and pre-compact."""
    from alluvia.ingest.claude_code import ClaudeCodeAdapter
    from alluvia.llm.governor import LLMUnavailable
    user = config.DEFAULT_USER
    stats = {"ingested": False, "notes": 0, "pending": False, "handoff_written": False,
             "distill_error": None}
    transcript = payload.get("transcript_path")
    if not transcript or not os.path.isfile(transcript):
        raise FileNotFoundError(f"transcript not found: {transcript}")
    session = ClaudeCodeAdapter(os.path.dirname(transcript), user_id=user).read_file(transcript)
    if session is None:
        return stats                              # empty or harness-only transcript
    project = session.project or _project_of(payload)
    repo.upsert_session(session)
    stats["ingested"] = True
    try:
        notes = engine.distill_session(user, session.id, force=True, now=now)
        stats["notes"] = len(notes)
        engine.embed_new(user)
    except LLMUnavailable:
        stats["pending"] = True                   # raw kept; handoff says so
    except Exception as e:                        # noqa: BLE001 — a failed distill
        stats["distill_error"] = repr(e)          # must never cost the user the
    #                                               handoff built from what is known
    if project:
        stats["handoff_written"] = write_handoff(repo, user, project, now=now)
    _stamp(repo, "hook:last_run")
    return stats


def refresh_handoffs(repo, user_id: str, now=None) -> int:
    """Rebuild the handoff cache for every repository the store knows, so the
    FIRST session after a backfill already receives its context. Repos with
    nothing known lose any stale cache. Returns how many were written."""
    projects = sorted({s["project"] for s in repo.list_session_meta(user_id) if s["project"]})
    return sum(1 for p in projects if write_handoff(repo, user_id, p, now=now))
