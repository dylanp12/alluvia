"""Reusable adapter toolkit: timestamp/role/message parsing, Anthropic content-block
extraction, and RawSession assembly. Keeps each source adapter thin and consistently
version-tolerant."""
from __future__ import annotations

from datetime import datetime, timezone

from alluvia.models import Message, RawSession, content_hash, session_id

_USER_ROLES = {"user", "human", "1", 1}
_ASSISTANT_ROLES = {"ai", "assistant", "bot", "model", "gemini", "2", 2}   # model/gemini: Gemini CLI
_TOOL_RESULT_CAP = 2000


def parse_ts(v) -> datetime | None:
    """Epoch-ms / epoch-s / ISO string -> aware datetime; None on anything else."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if v > 1e12:
            v = v / 1000.0
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def normalize_role(raw) -> str | None:
    if raw in _USER_ROLES:
        return "user"
    if raw in _ASSISTANT_ROLES:
        return "assistant"
    return None


def message_from_dict(d: dict) -> Message | None:
    role = normalize_role(d.get("role", d.get("type", d.get("author"))))
    if role is None:
        return None
    text = d.get("text") or d.get("content") or d.get("message") or ""
    if not isinstance(text, str) or not text.strip():
        return None
    return Message(role=role, text=text.strip(),
                   ts=parse_ts(d.get("timestamp", d.get("createdAt", d.get("created_at")))))


def messages_from_dicts(items) -> list[Message]:
    out = []
    for it in items:
        if isinstance(it, dict):
            m = message_from_dict(it)
            if m:
                out.append(m)
    return out


def anthropic_text(content) -> str:
    """Text from an Anthropic Messages `content`: a str, or a list of blocks. Keeps
    `text` and `tool_result` (capped); drops `tool_use` invocations + unknown blocks."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        t = block.get("type")
        if t == "text":
            txt = block.get("text")
            if isinstance(txt, str) and txt.strip():
                parts.append(txt.strip())
        elif t == "tool_result":
            inner = anthropic_text(block.get("content"))
            if inner:
                parts.append(inner[:_TOOL_RESULT_CAP])
        # tool_use and unknown block types: skipped
    return "\n".join(parts).strip()


def join_text_parts(content) -> str:
    """Text from a list of `{... "text": str}` parts, or a bare string. Serves the
    Gemini (`parts`) and Codex (`content` items) shapes: keeps any part carrying a
    `text` key, skips the rest (function calls, images, tool results). Newline-joined."""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for p in content:
        if isinstance(p, dict):
            t = p.get("text")
            if isinstance(t, str) and t.strip():
                parts.append(t.strip())
    return "\n".join(parts).strip()


def build_session(source: str, native_id: str, title: str | None,
                  messages: list[Message], user_id: str,
                  started: datetime | None = None, ended: datetime | None = None) -> RawSession:
    """Assemble a RawSession. `messages` must be non-empty (caller skips empties)."""
    times = [m.ts for m in messages if m.ts]
    return RawSession(
        id=session_id(source, native_id), user_id=user_id, source=source, native_id=native_id,
        title=(title or messages[0].text)[:60],
        started_at=started or (min(times) if times else None),
        ended_at=ended or (max(times) if times else None),
        messages=messages, content_hash=content_hash(messages))
