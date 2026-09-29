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


def build_project_handoff(repo, user_id: str, project: str,
                          now: datetime | None = None,
                          max_chars: int = MAX_CHARS) -> str | None:
    return build_project_handoff_with_ids(repo, user_id, project, now=now, max_chars=max_chars)[0]


def build_project_handoff_struct(repo, user_id: str, project: str,
                                 now: datetime | None = None) -> dict | None:
    """The briefing as data: what the last session settled, what is open here,
    earlier decisions, the footer lines, and candidate note ids in ``shown``.
    The plugin renders this structure within its character budget; use
    build_project_handoff_with_ids for the ids that survive that limit."""
    sessions = repo.list_session_meta(user_id, project=project)
    if not sessions:
        return None
    by_id = {s["id"]: s for s in sessions}
    hidden = repo.suppressed_note_ids(user_id)
    notes = [n for n in repo.get_notes(user_id)
             if n.session_id in by_id and n.id not in hidden]
    if not notes:
        return None
    by_session: dict[str, list[Note]] = {}
    for note in notes:
        by_session.setdefault(note.session_id, []).append(note)
    native = {sid: s["native_id"][:8] for sid, s in by_id.items()}

    def when(sid: str) -> datetime:
        s = by_id[sid]
        return to_utc(s["ended_at"] or s["started_at"]) or _EPOCH

    session_order = sorted(by_session, key=lambda sid: (when(sid), sid), reverse=True)
    latest_sid = session_order[0]
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
        # Decisions first; within a kind, prefer later messages in this session.
        return sorted(pool, key=lambda n: (KIND_ORDER.get(n.kind, 9), -span(n), n.text, n.id))[:k]

    def item(n: Note) -> dict:
        return {"kind": "note", "id": n.id, "note_kind": n.kind, "text": n.text,
                "session_id": n.session_id, "session_native": native[n.session_id]}

    last = [item(n) for n in pick(by_session[latest_sid])]
    mine = {n.id for n in notes}
    open_ = [{"kind": "topic", "id": t.id, "label": t.label, "status": t.status,
              "session_count": t.session_count}
             for t in repo.list_themes(user_id)
             if t.status in ("open", "dormant") and any(nid in mine for nid in t.note_ids)][:PER_SECTION]
    earlier = []
    for sid in session_order[1:]:
        # Message positions only rank notes within the same conversation.
        remaining = PER_SECTION - len(earlier)
        earlier.extend(item(n) for n in pick(
            [n for n in by_session[sid] if n.kind == "decision"], k=remaining))
        if len(earlier) == PER_SECTION:
            break
    distilled = repo.done_session_ids(user_id)
    pending = sum(1 for sid in by_id if sid not in distilled)
    foot = f"{len(sessions)} session{'s' if len(sessions) != 1 else ''} in this repo"
    if pending:
        foot += (f" · {pending} session{'s' if pending != 1 else ''} not yet distilled "
                 f"(alluvia refresh)")
    footer = [foot,
              'prior context, not ground truth — verify against the code. '
              'more: alluvia recall "<question>" --here · wrong? alluvia forget <note-id>',
              'useful? alluvia handoff --kept · noise? alluvia handoff --noise']
    return {"project": project_name(project), "head": head, "last": last, "open": open_,
            "earlier": earlier, "footer": footer,
            "shown": [i["id"] for i in last] + [i["id"] for i in earlier]}


def _fmt(it: dict, prefix: str) -> str:
    body = it["text"] if len(it["text"]) <= LINE_CAP else it["text"][:LINE_CAP - 1] + "…"
    return f"- {prefix}{body} (session {it['session_native']})"


def _render_handoff_with_ids(s: dict, max_chars: int) -> tuple[str, list[str]]:
    lines: list[tuple[str, str | None]] = [
        (f"alluvia · prior context for this repo ({s['project']})", None),
        (f"{s['head']}:", None),
    ]
    lines += [(_fmt(it, f"[{it['note_kind']}] "), it["id"]) for it in s["last"]]
    lines += [(f"- open here: {t['label']} [{t['status']}] · {t['session_count']} sessions", None)
              for t in s["open"]]
    if s["earlier"]:
        lines.append(("earlier decisions here:", None))
        lines += [(_fmt(it, ""), it["id"]) for it in s["earlier"]]
    lines += [(line, None) for line in s["footer"]]
    text = "\n".join(line for line, _ in lines)
    if len(text) <= max_chars:
        return text, [note_id for _, note_id in lines if note_id is not None]

    visible: list[str] = []
    shown: list[str] = []
    used = 0
    for line, note_id in lines:
        added = len(line) + bool(visible)
        if used + added + 2 > max_chars:  # Reserve the final newline and ellipsis.
            break
        visible.append(line)
        used += added
        if note_id is not None:
            shown.append(note_id)
    text = "\n".join(visible)
    return (text + "\n…" if visible else "…" if max_chars > 0 else ""), shown


def render_handoff(s: dict, max_chars: int = MAX_CHARS) -> str:
    """The exact text the plugin injects, rendered from the structure."""
    return _render_handoff_with_ids(s, max_chars)[0]


def build_project_handoff_with_ids(repo, user_id: str, project: str,
                                   now: datetime | None = None,
                                   max_chars: int = MAX_CHARS) -> tuple[str | None, list[str]]:
    """The handoff text and the ids of the notes it shows — the ids are what a
    later verdict or reference check is about."""
    s = build_project_handoff_struct(repo, user_id, project, now=now)
    if s is None:
        return None, []
    return _render_handoff_with_ids(s, max_chars)
