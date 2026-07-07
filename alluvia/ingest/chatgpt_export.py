"""ChatGPT official data-export adapter.

Input: the export ZIP, an extracted directory, or conversations.json itself.
One conversation -> one RawSession. The node tree is linearized along the
canonical branch (current_node -> parent chain); only user/assistant text
parts are kept. Re-import of a newer export is idempotent via content_hash.
"""
from __future__ import annotations
import json
import os
import zipfile
from datetime import datetime, timezone
from typing import Iterator

from alluvia.models import Message, RawSession, content_hash, session_id


def _load_conversations(path: str):
    if os.path.isdir(path):
        path = os.path.join(path, "conversations.json")
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            with z.open("conversations.json") as f:
                return json.load(f)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dt(epoch) -> datetime | None:
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _canonical_nodes(conv: dict) -> list[dict]:
    mapping = conv.get("mapping") or {}
    node_id = conv.get("current_node")
    chain: list[dict] = []
    seen: set[str] = set()
    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = mapping[node_id]
        chain.append(node)
        node_id = node.get("parent")
    chain.reverse()
    return chain


def _message(node: dict) -> Message | None:
    msg = node.get("message")
    if not isinstance(msg, dict):
        return None
    role = ((msg.get("author") or {}).get("role") or "")
    if role not in ("user", "assistant"):
        return None
    content = msg.get("content") or {}
    if content.get("content_type") != "text":
        return None
    parts = [p for p in (content.get("parts") or []) if isinstance(p, str) and p.strip()]
    if not parts:
        return None
    return Message(role=role, text="\n".join(p.strip() for p in parts),
                   ts=_dt(msg.get("create_time")))


class ChatGPTExportAdapter:
    def __init__(self, path: str, user_id: str = "local"):
        self.path = path
        self.user_id = user_id

    def read(self) -> Iterator[RawSession]:
        for conv in _load_conversations(self.path):
            if not isinstance(conv, dict):
                continue
            native_id = str(conv.get("id") or conv.get("conversation_id") or "")
            if not native_id:
                continue
            messages = [m for m in (_message(n) for n in _canonical_nodes(conv)) if m]
            if not messages:
                continue
            times = [m.ts for m in messages if m.ts]
            yield RawSession(
                id=session_id("chatgpt", native_id), user_id=self.user_id,
                source="chatgpt", native_id=native_id,
                title=(conv.get("title") or messages[0].text[:60]),
                started_at=_dt(conv.get("create_time")) or (min(times) if times else None),
                ended_at=max(times) if times else None,
                messages=messages, content_hash=content_hash(messages),
            )
