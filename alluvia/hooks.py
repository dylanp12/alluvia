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

from alluvia import cloud_memory, config
from alluvia.handoff import build_project_handoff_with_ids
from alluvia.projects import project_key, project_root
from alluvia.repo_share import import_share_if_changed, is_shared, write_share

import logging

log = logging.getLogger(__name__)


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
    _stamp(repo, "hook:last_run")
    try:
        # a repo that carries its own memory (.alluvia/memory.jsonl) is imported
        # first — SQLite only, milliseconds — so a fresh clone or a second
        # machine gets the repo's handoff on its very first session
        imported = import_share_if_changed(repo, config.DEFAULT_USER, project)
        if imported and (imported["sessions_added"] or imported["notes_added"]):
            write_handoff(repo, config.DEFAULT_USER, project)
    except Exception as e:                       # noqa: BLE001 — never block the session
        log.warning("repo memory import skipped: %r", e)
    path = handoff_path(project)
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    try:
        side = json.loads(sidecar_path(project).read_text(encoding="utf-8"))
        ids = list(side.get("note_ids") or [])
    except (OSError, ValueError):
        ids = []
    repo.record_handoff_event(config.DEFAULT_USER, project, ids, chars=len(text),
                              source=payload.get("source"))
    return {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                   "additionalContext": text}}


def sidecar_path(project: str) -> Path:
    return handoff_path(project).with_suffix(".json")


def write_handoff(repo, user_id: str, project: str, now=None) -> bool:
    """Cache text + a JSON sidecar naming the notes it shows (proof of use
    needs to know what was on screen, not just that something was)."""
    text, ids = build_project_handoff_with_ids(repo, user_id, project, now=now)
    path = handoff_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        for f in (path, sidecar_path(project)):
            if f.exists():
                f.unlink()
        return False
    path.write_text(text, encoding="utf-8")
    sidecar_path(project).write_text(json.dumps({
        "note_ids": ids, "chars": len(text),
        "written_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
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
    # signed in: memory goes up and comes down here, bounded by the client's
    # timeouts; signed out this is the honest 'skipped' with no network at all
    try:
        stats["cloud"] = cloud_memory.sync(repo, user)
    except Exception as e:                        # noqa: BLE001 — never fail the hook
        stats["cloud"] = {"ok": False, "error": repr(e)}
    pulled = (stats["cloud"].get("pull") or {}).get("notes_added", 0) if stats["cloud"].get("ok") else 0
    if project:
        _mark_references(repo, user, project, session)
        stats["handoff_written"] = write_handoff(repo, user, project, now=now)
        if is_shared(project):
            stats["share_notes"] = write_share(repo, user, project)
    if pulled:
        # another machine's notes arrived: every repo's next session start
        # should already see them, not wait for a hook to run there
        stats["handoffs_rebuilt"] = refresh_handoffs(repo, user, now=now)
    _stamp(repo, "hook:last_run")
    return stats


def _mark_references(repo, user_id: str, project: str, session) -> None:
    """Proxy signal: which of the notes shown at this repo's last session start
    did the session's own text end up using? Labeled a proxy wherever shown."""
    from alluvia.proof import referenced_notes
    ev = repo.latest_handoff_event(user_id, project)
    if not ev or not ev["note_ids"]:
        return
    wanted = set(ev["note_ids"])
    notes = {n.id: n.text for n in repo.get_notes(user_id) if n.id in wanted}
    text = "\n".join(m.text for m in session.messages if m.role == "assistant")
    repo.set_event_references(user_id, ev["id"], referenced_notes(notes, text))


def refresh_handoffs(repo, user_id: str, now=None) -> int:
    """Rebuild the handoff cache for every repository the store knows, so the
    FIRST session after a backfill already receives its context. Repos with
    nothing known lose any stale cache. Returns how many were written."""
    projects = sorted({s["project"] for s in repo.list_session_meta(user_id) if s["project"]})
    written = 0
    for p in projects:
        if write_handoff(repo, user_id, p, now=now):
            written += 1
        if is_shared(p):
            write_share(repo, user_id, p)
    return written
