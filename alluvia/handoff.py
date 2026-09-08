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
    earlier decisions, the footer lines, and the ids of the notes shown. The
    plugin's text is rendered from this, so an app that renders it can never
    disagree with what the agent was told."""
    sessions = repo.list_session_meta(user_id, project=project)
    if not sessions:
        return None
    by_id = {s["id"]: s for s in sessions}
    hidden = repo.suppressed_note_ids(user_id)
    notes = [n for n in repo.get_notes(user_id)
             if n.session_id in by_id and n.id not in hidden]
    if not notes:
        return None
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

    def item(n: Note) -> dict:
        return {"kind": "note", "id": n.id, "note_kind": n.kind, "text": n.text,
                "session_id": n.session_id, "session_native": native[n.session_id]}

    last = [item(n) for n in pick([n for n in notes if n.session_id == latest_sid])]
    mine = {n.id for n in notes}
    open_ = [{"kind": "topic", "id": t.id, "label": t.label, "status": t.status,
              "session_count": t.session_count}
             for t in repo.list_themes(user_id)
             if t.status in ("open", "dormant") and any(nid in mine for nid in t.note_ids)][:PER_SECTION]
    older = pick([n for n in notes if n.kind == "decision" and n.session_id != latest_sid])
    earlier = [item(n) for n in sorted(older, key=lambda n: when(n.session_id), reverse=True)]
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


def render_handoff(s: dict, max_chars: int = MAX_CHARS) -> str:
    """The exact text the plugin injects, rendered from the structure."""
    lines = [f"alluvia · prior context for this repo ({s['project']})", f"{s['head']}:"]
    lines += [_fmt(it, f"[{it['note_kind']}] ") for it in s["last"]]
    lines += [f"- open here: {t['label']} [{t['status']}] · {t['session_count']} sessions"
              for t in s["open"]]
    if s["earlier"]:
        lines.append("earlier decisions here:")
        lines += [_fmt(it, "") for it in s["earlier"]]
    lines += s["footer"]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars - 1].rsplit("\n", 1)[0] + "\n…"
    return text


def build_project_handoff_with_ids(repo, user_id: str, project: str,
                                   now: datetime | None = None,
                                   max_chars: int = MAX_CHARS) -> tuple[str | None, list[str]]:
    """The handoff text and the ids of the notes it shows — the ids are what a
    later verdict or reference check is about."""
    s = build_project_handoff_struct(repo, user_id, project, now=now)
    if s is None:
        return None, []
    return render_handoff(s, max_chars), s["shown"]
