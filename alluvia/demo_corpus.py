"""A tiny synthetic corpus with PRE-COMPUTED derived data, so every lens is
alive seconds after install — no API key, no LLM call, no ingestion.

The story mirrors the product's public validation narrative (two tools, a
security gap met twice more than a year apart) with entirely fictional
content. Raw + derived + one judgment are seeded so themes, connections,
unfinished, proposals, and the dashboard all have something true to show."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from alluvia.models import Link, Message, Note, Proposal, RawSession, content_hash

DIM = 384


def _vec(seed: str) -> list[float]:
    """Deterministic unit-ish vector; real enough for storage and rebuilds."""
    h = hashlib.sha256(seed.encode()).digest()
    raw = [((b / 255.0) - 0.5) for b in (h * 12)[:DIM]]
    norm = sum(x * x for x in raw) ** 0.5 or 1.0
    return [x / norm for x in raw]


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


_SESSIONS = [
    ("claude-code", "d1", "upload service ids", "2025-04-02T10:00:00",
     [("user", "uploads lose their id somewhere between client and service"),
      ("assistant", "the service isn't storing the id on upload — it trusts the client copy")]),
    ("cursor", "d2", "security review: order api", "2026-06-10T15:00:00",
     [("user", "reviewing the order api for the audit"),
      ("assistant", "there's no cross-check between order id and account id — that enables forgery")]),
    ("claude-code", "d3", "retry queue design", "2025-09-14T09:00:00",
     [("user", "designing the retry queue for webhook delivery"),
      ("assistant", "exponential backoff with a dead-letter table after five attempts")]),
    ("cursor", "d4", "webhook retries again", "2026-02-20T11:00:00",
     [("user", "webhooks are double-firing under retries again"),
      ("assistant", "the retry queue needs idempotency keys — this was left open last time")]),
    ("claude-code", "d5", "search latency", "2025-12-01T13:00:00",
     [("user", "search is slow on long histories"),
      ("assistant", "precompute the token index nightly; resolved after batching")]),
]

_NOTES = [
    ("note:demo1", "claude-code:d1", "problem",
     "upload service does not store the id server-side", "2025-04-02T10:05:00"),
    ("note:demo2", "cursor:d2", "insight",
     "no cross-check between order id and account id enables forgery", "2026-06-10T15:10:00"),
    ("note:demo3", "claude-code:d3", "decision",
     "retry queue uses exponential backoff with a dead-letter table", "2025-09-14T09:20:00"),
    ("note:demo4", "cursor:d4", "problem",
     "webhook retries double-fire; idempotency keys still missing", "2026-02-20T11:15:00"),
    ("note:demo5", "claude-code:d5", "insight",
     "nightly token index precompute fixed search latency", "2025-12-01T13:30:00"),
]

_THEMES = [
    ("theme:demo0", "Server-side ID validation", 
     "The same trust-boundary gap met twice: ids accepted without a server-side cross-check.",
     ["note:demo1", "note:demo2"], "2025-04-02T10:05:00", "2026-06-10T15:10:00",
     2, 2, "open"),
    ("theme:demo1", "Webhook retry idempotency",
     "Retries keep double-firing; idempotency keys decided but never landed.",
     ["note:demo3", "note:demo4"], "2025-09-14T09:20:00", "2026-02-20T11:15:00",
     2, 2, "open"),
    ("theme:demo2", "Search latency",
     "Slow search on long histories; resolved via nightly precompute.",
     ["note:demo5"], "2025-12-01T13:30:00", "2025-12-01T13:30:00",
     1, 1, "resolved"),
]

_LINKS = [
    ("link:demo1", "note:demo2", "note:demo1", "theme:demo0", "theme:demo0",
     0.94, "same missing server-side validation, found twice, 14 months apart"),
    ("link:demo2", "note:demo4", "note:demo3", "theme:demo1", "theme:demo1",
     0.88, "the decision existed seven months before the bug returned"),
]


def _real_embeddings() -> dict:
    """Precomputed bge-small vectors (see demo_embeddings.json) so `recall`
    against the demo store matches without a seed-time model download."""
    import json
    import os
    p = os.path.join(os.path.dirname(__file__), "demo_embeddings.json")
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def seed(repo, user_id: str = "local") -> None:
    if repo.list_sessions(user_id):
        return                                 # idempotent
    for source, native, title, ts, msgs in _SESSIONS:
        messages = [Message(role=r, text=t, ts=_dt(ts)) for r, t in msgs]
        repo.upsert_session(RawSession(
            id=f"{source}:{native}", user_id=user_id, source=source,
            native_id=native, title=title, started_at=_dt(ts), ended_at=_dt(ts),
            messages=messages, content_hash=content_hash(messages)))
    notes = [Note(id=nid, user_id=user_id, session_id=sid, span_ref="msg:1",
                  kind=kind, text=text, created_at=_dt(ts))
             for nid, sid, kind, text, ts in _NOTES]
    repo.upsert_notes(notes)
    real = _real_embeddings()
    for n in notes:
        repo.set_embedding(user_id, n.id, real.get(n.id) or _vec(n.text))
    from alluvia.models import Theme
    repo.replace_themes(user_id, [
        Theme(id=tid, user_id=user_id, label=label, summary=summary,
              note_ids=nids, first_seen=_dt(f), last_seen=_dt(l),
              session_count=sc, source_count=oc, status=status)
        for tid, label, summary, nids, f, l, sc, oc, status in _THEMES])
    repo.replace_links(user_id, [
        Link(id=lid, user_id=user_id, from_note_id=a, to_note_id=b,
             from_theme_id=ta, to_theme_id=tb, kind="surprise", weight=w, why=why)
        for lid, a, b, ta, tb, w, why in _LINKS])
    repo.insert_proposal(Proposal(
        id="prop:demo1", user_id=user_id,
        created_at="2026-06-11T09:00:00+00:00", kind="theme",
        source_ref="theme:demo0", source_hash="demo",
        title="Add a server-side id cross-check",
        text="Both incidents share one root cause: the service trusts "
             "client-supplied ids. Add a server-side consistency check at "
             "upload and order creation.",
        next_step="Write the check behind a flag; backfill an audit query first.",
        cites=["note:demo1", "note:demo2"], novelty_sim=0.31, feasibility=4,
        risk="low — additive validation", model="demo"))
    repo.set_meta("last_refresh", json.dumps(
        {"at": "2026-06-11T09:00:00+00:00", "degraded": False, "retry_at": None}))
