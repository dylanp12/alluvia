"""Proof of use: what the memory did, counted honestly.

Explicit verdicts are the truth (`alluvia handoff --kept|--noise`, MCP
`rate_context`). The reference check is a labeled proxy: after a session, a
shown note counts as referenced when the session's own text carries at least
two of the note's distinctive terms, or names a file the note names in an
[action] line. Refusals are counted too — saying "no record" is part of the
proof. Counts only; never rates dressed as accuracy."""
from __future__ import annotations

import re

from alluvia.lexical import lex_tokens, path_anchors

MIN_TERM_LEN = 5
TERMS_NEEDED = 2
_ACTION = re.compile(r"^\[action\] .*$", re.MULTILINE)


def _terms(text: str) -> set[str]:
    return {t for t in lex_tokens(text) if len(t) >= MIN_TERM_LEN}


def referenced_notes(notes: dict[str, str], session_text: str) -> list[str]:
    """Ids of the shown notes the session text plausibly used (proxy)."""
    low = session_text.lower()
    if not low.strip():
        return []
    actions = " ".join(m.group(0).lower() for m in _ACTION.finditer(session_text))
    out: list[str] = []
    for nid, text in notes.items():
        terms = _terms(text)
        hits = sum(1 for t in terms if t in low)
        by_terms = hits >= TERMS_NEEDED
        by_path = any(a in actions for a in path_anchors(text)) if actions else False
        if by_terms or by_path:
            out.append(nid)
    return out


def record_verdict_for(repo, user_id: str, project: str, verdict: str,
                       note_id: str | None = None, event_id: str | None = None) -> str | None:
    """Attach a verdict to the latest handoff shown for this repository (or a
    named event). None when nothing has been shown there yet."""
    if event_id is None:
        ev = repo.latest_handoff_event(user_id, project)
        if ev is None:
            return None
        event_id = ev["id"]
    repo.record_verdict(user_id, event_id, verdict, note_id=note_id)
    return event_id


def stats_block(repo, user_id: str) -> list[str]:
    events = repo.list_handoff_events(user_id)
    lines_shown = sum(len(e["note_ids"]) for e in events)
    referenced = sum(len(e["referenced_note_ids"]) for e in events)
    verdicts = repo.list_verdicts(user_id)
    kept = sum(1 for v in verdicts if v["verdict"] == "kept")
    noise = sum(1 for v in verdicts if v["verdict"] == "noise")
    c = repo.counters(user_id)
    return [
        f"handoffs: {len(events)} delivered · {lines_shown} lines · kept {kept} · noise {noise}"
        f" · referenced (proxy) {referenced}/{lines_shown}",
        f"recall:   {c.get('recall_answered', 0)} answered · {c.get('recall_refused', 0)} said no record",
        f"forget:   {len(repo.suppressed_note_ids(user_id))} notes suppressed",
    ]
