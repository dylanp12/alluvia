from __future__ import annotations
import hashlib
from datetime import datetime, timedelta
from alluvia.models import Note, Theme, to_utc

_SYSTEM = ('Did this recurring thread reach a conclusion/decision, or is it still open? '
           'Return JSON {"status": "resolved" | "open"}.')
MIN_SESSIONS = 2
MIN_SPAN_DAYS = 14
STALE_DAYS = 60


def _recurring(t: Theme, min_sessions: int, min_span_days: int) -> bool:
    if t.session_count < min_sessions or not t.first_seen or not t.last_seen:
        return False
    return (to_utc(t.last_seen) - to_utc(t.first_seen)).days >= min_span_days


def _status_hash(t: Theme, notes: dict[str, Note]) -> str:
    parts = sorted(f"{nid}:{notes[nid].text}" for nid in t.note_ids if nid in notes)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def classify_status(user_id: str, theme: Theme, notes: dict[str, Note], llm, cache, *,
                    now: datetime, min_sessions: int = MIN_SESSIONS,
                    min_span_days: int = MIN_SPAN_DAYS, stale_days: int = STALE_DAYS) -> str:
    """Return open|resolved|dormant|unknown. `cache` has get(user,hash)/set(user,hash,status)."""
    now = to_utc(now)
    if not _recurring(theme, min_sessions, min_span_days):
        return "unknown"
    h = _status_hash(theme, notes)
    base = cache.get(user_id, h)
    if base is None:
        result = llm.complete_json(
            _SYSTEM, "\n".join(notes[n].text for n in theme.note_ids if n in notes))
        base = result.get("status", "open") if isinstance(result, dict) else "open"
        if base not in ("open", "resolved"):
            base = "open"
        cache.set(user_id, h, base)
    if (base == "open" and theme.last_seen
            and to_utc(theme.last_seen) < now - timedelta(days=stale_days)):
        return "dormant"
    return base
