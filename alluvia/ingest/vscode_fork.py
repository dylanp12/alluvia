"""VS-Code-fork family adapter (Cursor / Windsurf / Antigravity).

One shared core: discover state.vscdb files -> temp-copy (locks/9p) -> extract.
Flavors differ in roots, key patterns, and (optionally) a flavor-specific
extractor. Discovery findings (scripts/probe_forks.py, 2026-07-02):

- cursor: full conversations live in globalStorage cursorDiskKV as
  `composerData:{id}` records — some with inline `conversation`, some
  headers-only (`fullConversationHeadersOnly`) joined to
  `bubbleId:{composerId}:{bubbleUuid}` records (`type` 1=user/2=assistant,
  `text`). Old-style chats appear in workspace ItemTable
  `workbench.panel.aichat.view.aichat.chatdata` ({"tabs":[{"bubbles":[...]}]}).
  The global DB is large (multi-MB values, ~36k bubbles) so it is queried via
  targeted SQL, never loaded wholesale.
- windsurf: state.vscdb holds UI state only; Cascade transcripts are protobuf
  under ~/.codeium/windsurf — no schema, so windsurf ships log-and-skip.
- antigravity: agent state is base64 protobuf (jetskiStateSync.*) — ships
  log-and-skip.

Payloads are undocumented and version-churny: extraction is shape-tolerant and
unknown material is logged and skipped, never fatal.
"""
from __future__ import annotations
import glob
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from alluvia.models import Message, RawSession, content_hash, session_id

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlavorSpec:
    name: str
    roots: tuple[str, ...]
    key_patterns: tuple[str, ...]      # regexes matched against KV keys (generic path)


from alluvia.platform import fork_roots


FLAVORS: dict[str, FlavorSpec] = {
    "cursor": FlavorSpec(
        name="cursor",
        roots=fork_roots("Cursor"),
        key_patterns=(r"aichat.*chatdata",),
    ),
    "windsurf": FlavorSpec(
        name="windsurf",
        roots=fork_roots("Windsurf"),
        key_patterns=(r"cascade.*(session|conversation|chat)", r"chat\.ChatSessionStore"),
    ),
    "antigravity": FlavorSpec(
        name="antigravity",
        roots=fork_roots("Antigravity"),
        key_patterns=(r"agent.*(session|conversation)", r"chat\.ChatSessionStore"),
    ),
}

_USER_ROLES = {"user", "human", "1", 1}
_ASSISTANT_ROLES = {"ai", "assistant", "bot", "2", 2}


def _ts(v) -> datetime | None:
    """Parse epoch ms / epoch s / ISO strings; None on anything else."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if v > 1e12:                     # ms epoch
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


def _msg_from_dict(d: dict) -> Message | None:
    role_raw = d.get("role", d.get("type", d.get("author")))
    if role_raw in _USER_ROLES:
        role = "user"
    elif role_raw in _ASSISTANT_ROLES:
        role = "assistant"
    else:
        return None
    text = d.get("text") or d.get("content") or d.get("message") or ""
    if not isinstance(text, str) or not text.strip():
        return None
    ts = _ts(d.get("timestamp", d.get("createdAt", d.get("created_at"))))
    return Message(role=role, text=text.strip(), ts=ts)


def _messages_from_list(items) -> list[Message]:
    out = []
    for it in items:
        if isinstance(it, dict):
            m = _msg_from_dict(it)
            if m:
                out.append(m)
    return out


def _sessions_from_payload(payload, fallback_id: str) -> list[tuple[str, str | None, list[Message]]]:
    """Try known payload shapes -> [(native_id, title, messages)]."""
    out: list[tuple[str, str | None, list[Message]]] = []
    if isinstance(payload, dict):
        if isinstance(payload.get("tabs"), list):                      # aichat chatdata
            for tab in payload["tabs"]:
                if not isinstance(tab, dict):
                    continue
                msgs = _messages_from_list(tab.get("bubbles", []))
                if msgs:
                    out.append((str(tab.get("tabId", fallback_id)),
                                tab.get("chatTitle"), msgs))
            return out
        for key in ("conversation", "messages", "bubbles", "turns"):   # single-session dicts
            if isinstance(payload.get(key), list):
                msgs = _messages_from_list(payload[key])
                if msgs:
                    nid = str(payload.get("composerId") or payload.get("id")
                              or payload.get("sessionId") or fallback_id)
                    out.append((nid, payload.get("name"), msgs))
                return out
        return out
    if isinstance(payload, list):                                      # bare message list
        msgs = _messages_from_list(payload)
        if msgs:
            out.append((fallback_id, None, msgs))
    return out


@contextmanager
def _open_copy(path: str):
    """Temp-copy a DB (plus WAL/SHM sidecars) and open read-only."""
    tmpdir = tempfile.mkdtemp(prefix="alluvia-fork-")
    try:
        dst = os.path.join(tmpdir, "db.vscdb")
        shutil.copy2(path, dst)
        for ext in ("-wal", "-shm"):
            if os.path.exists(path + ext):
                shutil.copy2(path + ext, dst + ext)
        conn = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
        try:
            yield conn
        finally:
            conn.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}


def _decode(v) -> str:
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return str(v)


class VSCodeForkAdapter:
    def __init__(self, flavor: str, root: str | None = None, user_id: str = "local"):
        from alluvia import config
        self.spec = FLAVORS[flavor]
        cfg_root = config.source_root(flavor)
        self.roots = (root,) if root else ((cfg_root,) if cfg_root else self.spec.roots)
        self.user_id = user_id
        self._key_rx = [re.compile(p, re.IGNORECASE) for p in self.spec.key_patterns]

    # -- discovery ---------------------------------------------------------
    def _db_paths(self) -> list[str]:
        paths: list[str] = []
        for root in self.roots:
            paths += glob.glob(os.path.join(root, "User", "workspaceStorage",
                                            "*", "state.vscdb"))
            g = os.path.join(root, "User", "globalStorage", "state.vscdb")
            if os.path.exists(g):
                paths.append(g)
        return sorted(paths)

    # -- read --------------------------------------------------------------
    def read(self) -> Iterator[RawSession]:
        best: dict[str, RawSession] = {}
        for path in self._db_paths():
            try:
                with _open_copy(path) as conn:
                    for session in self._extract_db(conn, path):
                        prev = best.get(session.id)
                        if prev is None or len(session.messages) > len(prev.messages):
                            best[session.id] = session
            except Exception as e:
                log.warning("%s: skipping unreadable DB %s (%s)",
                            self.spec.name, path, e)
        if not best:
            log.info("%s: no chat sessions found — flavor may store transcripts "
                     "outside state.vscdb (see module docstring)", self.spec.name)
        yield from best.values()

    def _extract_db(self, conn, path: str) -> Iterator[RawSession]:
        tables = _tables(conn)
        ws = os.path.basename(os.path.dirname(os.path.dirname(path)))
        if self.spec.name == "cursor" and "cursorDiskKV" in tables:
            yield from self._extract_cursor_global(conn)
        yield from self._extract_generic(conn, tables, ws)

    # -- generic pattern path (all flavors, workspace DBs) -------------------
    def _extract_generic(self, conn, tables: set[str], ws: str) -> Iterator[RawSession]:
        for table in ("ItemTable",):
            if table not in tables:
                continue
            for key, raw in conn.execute(f"SELECT key, value FROM {table}"):
                key = str(key)
                if not any(rx.search(key) for rx in self._key_rx):
                    continue
                try:
                    payload = json.loads(_decode(raw))
                except json.JSONDecodeError:
                    continue
                fallback = f"{ws}-{abs(hash(key)) % 10**10}"
                for native_id, title, msgs in _sessions_from_payload(payload, fallback):
                    yield self._session(native_id, title, msgs)

    # -- cursor globalStorage: composerData + bubble join --------------------
    def _extract_cursor_global(self, conn) -> Iterator[RawSession]:
        for key, raw in conn.execute(
                "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"):
            try:
                comp = json.loads(_decode(raw))
            except json.JSONDecodeError:
                continue
            if not isinstance(comp, dict):
                continue
            composer_id = str(comp.get("composerId")
                              or str(key).split(":", 1)[1])
            msgs = _messages_from_list(comp.get("conversation") or [])
            if not msgs:
                msgs = self._bubbles(conn, composer_id,
                                     comp.get("fullConversationHeadersOnly") or [])
            if not msgs:
                continue
            created = _ts(comp.get("createdAt"))
            updated = _ts(comp.get("lastUpdatedAt"))
            yield self._session(composer_id, comp.get("name"), msgs,
                                started=created, ended=updated)

    def _bubbles(self, conn, composer_id: str, headers: list) -> list[Message]:
        msgs: list[Message] = []
        for h in headers:
            if not isinstance(h, dict) or not h.get("bubbleId"):
                continue
            row = conn.execute(
                "SELECT value FROM cursorDiskKV WHERE key = ?",
                (f"bubbleId:{composer_id}:{h['bubbleId']}",)).fetchone()
            if not row:
                continue
            try:
                bubble = json.loads(_decode(row[0]))
            except json.JSONDecodeError:
                continue
            if isinstance(bubble, dict):
                if "type" not in bubble and h.get("type") is not None:
                    bubble = {**bubble, "type": h["type"]}
                m = _msg_from_dict(bubble)
                if m:
                    msgs.append(m)
        return msgs

    # -- assembly ------------------------------------------------------------
    def _session(self, native_id: str, title: str | None, msgs: list[Message],
                 started: datetime | None = None,
                 ended: datetime | None = None) -> RawSession:
        times = [m.ts for m in msgs if m.ts]
        return RawSession(
            id=session_id(self.spec.name, native_id), user_id=self.user_id,
            source=self.spec.name, native_id=native_id,
            title=(title or msgs[0].text)[:60],
            started_at=started or (min(times) if times else None),
            ended_at=ended or (max(times) if times else None),
            messages=msgs, content_hash=content_hash(msgs),
        )
