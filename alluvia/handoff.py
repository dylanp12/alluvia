"""The project handoff: what alluvia knows about THIS repository, injected
at session start, resume, and after compaction.

Deterministic and cheap — built from distilled notes and themes, no
embedder, no LLM — so a hook can produce it in milliseconds. Every line
names the session it came from; suppressed notes never appear; when nothing
is known the answer is None, and the hook injects nothing at all."""
from __future__ import annotations

from datetime import datetime, timezone

from alluvia.models import Note, to_utc
from alluvia.projects import project_name

MAX_CHARS = 1500
KIND_ORDER = {"decision": 0, "problem": 1, "question": 2, "insight": 3, "idea": 4}
PER_SECTION = 3
LINE_CAP = 140
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _line(prefix: str, n: Note, native: str) -> str:
    body = n.text if len(n.text) <= LINE_CAP else n.text[:LINE_CAP - 1] + "…"
    return f"- {prefix}{body} (session {native})"


def build_project_handoff(repo, user_id: str, project: str,
                          now: datetime | None = None,
                          max_chars: int = MAX_CHARS) -> str | None:
    return build_project_handoff_with_ids(repo, user_id, project, now=now, max_chars=max_chars)[0]


def build_project_handoff_with_ids(repo, user_id: str, project: str,
                                   now: datetime | None = None,
                                   max_chars: int = MAX_CHARS) -> tuple[str | None, list[str]]:
    """The handoff text and the ids of the notes it shows — the ids are what a
    later verdict or reference check is about."""
    sessions = repo.list_session_meta(user_id, project=project)
    if not sessions:
        return None, []
    by_id = {s["id"]: s for s in sessions}
    hidden = repo.suppressed_note_ids(user_id)
    notes = [n for n in repo.get_notes(user_id)
             if n.session_id in by_id and n.id not in hidden]
    if not notes:
        return None, []
    shown: list[str] = []
    native = {sid: s["native_id"][:8] for sid, s in by_id.items()}

    def when(sid: str) -> datetime:
        s = by_id[sid]
        return to_utc(s["ended_at"] or s["started_at"]) or _EPOCH

    latest_sid = max({n.session_id for n in notes}, key=when)
    latest = by_id[latest_sid]
    stamp = latest["ended_at"] or latest["started_at"]
    head = (f"last session {stamp.date().isoformat() if stamp else 'undated'}"
            + (f" on {latest['branch']}" if latest.get("branch") else ""))

    def span(n: Note) -> int:
        try:
            return int(str(n.span_ref).split(":", 1)[1])
        except (ValueError, IndexError):
            return -1

    def pick(pool: list[Note], k: int = PER_SECTION) -> list[Note]:
        # decisions first; within a kind, later in the session = the settled view
        return sorted(pool, key=lambda n: (KIND_ORDER.get(n.kind, 9), -span(n), n.text))[:k]

    lines = [f"alluvia · prior context for this repo ({project_name(project)})", f"{head}:"]
    for n in pick([n for n in notes if n.session_id == latest_sid]):
        lines.append(_line(f"[{n.kind}] ", n, native[n.session_id]))
        shown.append(n.id)

    mine = {n.id for n in notes}
    open_themes = [t for t in repo.list_themes(user_id)
                   if t.status in ("open", "dormant") and any(nid in mine for nid in t.note_ids)]
    for t in open_themes[:PER_SECTION]:
        lines.append(f"- open here: {t.label} [{t.status}] · {t.session_count} sessions")

    older = pick([n for n in notes if n.kind == "decision" and n.session_id != latest_sid])
    if older:
        lines.append("earlier decisions here:")
        for n in sorted(older, key=lambda n: when(n.session_id), reverse=True):
            lines.append(_line("", n, native[n.session_id]))
            shown.append(n.id)

    distilled = repo.done_session_ids(user_id)
    pending = sum(1 for sid in by_id if sid not in distilled)
    foot = f"{len(sessions)} session{'s' if len(sessions) != 1 else ''} in this repo"
    if pending:
        foot += (f" · {pending} session{'s' if pending != 1 else ''} not yet distilled "
                 f"(alluvia refresh)")
    lines.append(foot)
    lines.append('prior context, not ground truth — verify against the code. '
                 'more: alluvia recall "<question>" --here · wrong? alluvia forget <note-id>')
    lines.append('useful? alluvia handoff --kept · noise? alluvia handoff --noise')
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars - 1].rsplit("\n", 1)[0] + "\n…"
    return text, shown
