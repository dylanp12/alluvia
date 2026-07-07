from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


def to_utc(dt: datetime | None) -> datetime | None:
    """Coerce to tz-aware UTC (naive datetimes are assumed UTC).

    Sources differ: fork/ChatGPT adapters emit aware timestamps, older data and
    tests are naive — comparisons must never mix the two."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Message:
    role: str
    text: str
    ts: datetime | None = None


@dataclass
class RawSession:
    id: str
    user_id: str
    source: str
    native_id: str
    title: str
    started_at: datetime | None
    ended_at: datetime | None
    messages: list[Message]
    content_hash: str


@dataclass
class Note:
    id: str
    user_id: str
    session_id: str
    span_ref: str
    kind: str          # idea|decision|question|problem|insight
    text: str
    created_at: datetime | None
    canonical_id: str | None = None


@dataclass
class Theme:
    id: str
    user_id: str
    label: str
    summary: str
    note_ids: list[str] = field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    session_count: int = 0
    source_count: int = 0
    status: str = "unknown"          # open | resolved | dormant | unknown


def session_id(source: str, native_id: str) -> str:
    return f"{source}:{native_id}"


def content_hash(messages: list[Message]) -> str:
    payload = json.dumps([[m.role, m.text] for m in messages], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class Link:
    id: str
    user_id: str
    from_note_id: str
    to_note_id: str
    from_theme_id: str
    to_theme_id: str
    kind: str
    weight: float
    why: str | None = None


def link_id(a: str, b: str) -> str:
    lo, hi = sorted([a, b])
    h = hashlib.sha256(f"{lo}|{hi}".encode("utf-8")).hexdigest()[:16]
    return f"link:{h}"


@dataclass
class Proposal:
    """Third data class: a JUDGMENT — durable output + human rating.
    Never rebuilt, never dropped by refresh."""
    id: str
    user_id: str
    created_at: str
    kind: str                 # link | theme
    source_ref: str
    source_hash: str
    title: str
    text: str
    next_step: str
    cites: list[str]
    novelty_sim: float | None
    feasibility: int | None
    risk: str | None
    model: str
    outcome: str = "pending"  # pending | kept | dismissed | rejected
    reject_reason: str | None = None
    rated_at: str | None = None
    rating_note: str | None = None
    rated_via: str | None = None      # cli | mcp (audit: who relayed the judgment)
