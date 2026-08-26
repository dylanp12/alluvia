"""Receipts: the verbatim quote behind a note — sliced fresh from the raw
session it was distilled from, wrapper-stripped, secret-redacted, capped.
The raw store is never mutated; a receipt is made to be shown and pasted,
so it must be safe to show and paste."""
from __future__ import annotations

from alluvia.models import Note

EXCERPT_CHAR_CAP = 400


def note_excerpt(repo, user_id: str, note: Note,
                 cap: int = EXCERPT_CHAR_CAP) -> str | None:
    from alluvia.distill.scrub import is_meta_message, redact, strip_wrappers
    try:
        idx = int(note.span_ref.split(":", 1)[1])
    except (ValueError, IndexError, AttributeError):
        return None
    session = repo.get_session(user_id, note.session_id)
    if not session or not 0 <= idx < len(session.messages):
        return None
    raw = session.messages[idx].text
    if is_meta_message(raw):
        return None          # a receipt quoting harness scaffolding is worse
    #                          than no receipt (spans can point at meta noise)
    text = redact(strip_wrappers(raw)).strip()
    return text[:cap] or None
