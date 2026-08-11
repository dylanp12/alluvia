"""OpenAI Codex CLI adapter (openai/codex). One JSONL "rollout" file per session
under `<CODEX_HOME>/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` (+ archived).
Each line is a RolloutLine `{timestamp, type, payload}`; the real conversation is
the `response_item` lines whose payload is a `message`. `event_msg` lines
double-encode the same text and are skipped. Tolerant of the older wrapper-less
format (bare ResponseItem objects at the JSON root) and of `.zst` compression."""
from __future__ import annotations

import glob
import json
import logging
import os
from typing import Iterator

from alluvia.ingest.common import build_session, join_text_parts, normalize_role, parse_ts
from alluvia.models import Message, RawSession

log = logging.getLogger(__name__)

# Wrapper record types that are never conversation content (payload ignored).
_WRAPPER_SKIP = {"event_msg", "turn_context", "compacted", "world_state",
                 "inter_agent_communication", "inter_agent_communication_metadata"}


class CodexAdapter:
    def __init__(self, root: str | None = None, user_id: str = "local"):
        from alluvia import config
        self._root = (root or config.source_root("codex") or os.environ.get("CODEX_HOME")
                      or os.path.expanduser("~/.codex"))
        self.user_id = user_id

    def read(self) -> Iterator[RawSession]:
        best: dict[str, RawSession] = {}
        for sub in ("sessions", "archived_sessions"):
            base = os.path.join(self._root, sub)
            for f in glob.glob(os.path.join(base, "**", "rollout-*.jsonl*"), recursive=True):
                try:
                    s = self._session(f)
                except Exception as e:
                    log.warning("codex: skipping %s (%s)", f, e)
                    continue
                if s and (s.native_id not in best or len(s.messages) > len(best[s.native_id].messages)):
                    best[s.native_id] = s
        yield from best.values()

    def _lines(self, path: str) -> list[str] | None:
        if path.endswith(".zst"):
            try:
                import zstandard
            except ImportError:
                log.warning("codex: skipping %s (install `zstandard` to read compressed rollouts)", path)
                return None
            with open(path, "rb") as fh:
                data = zstandard.ZstdDecompressor().stream_reader(fh).read()
            return data.decode("utf-8", "replace").splitlines()
        with open(path, encoding="utf-8") as fh:
            return fh.read().splitlines()

    def _session(self, path: str) -> RawSession | None:
        lines = self._lines(path)
        if lines is None:
            return None
        native_id: str | None = None
        started = None
        msgs: list[Message] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(obj, dict):
                continue
            t = obj.get("type")
            if t == "session_meta":
                meta = obj.get("payload") if isinstance(obj.get("payload"), dict) else obj
                native_id = native_id or meta.get("id") or meta.get("session_id")
                started = started or parse_ts(meta.get("timestamp"))
            elif t == "response_item":
                item = obj.get("payload")
                if isinstance(item, dict) and item.get("type") == "message":
                    self._add_message(item, msgs)
            elif t in _WRAPPER_SKIP:
                continue
            elif t == "message":                       # bare ResponseItem (old wrapper-less format)
                self._add_message(obj, msgs)
            elif t is None and "timestamp" in obj and ("id" in obj or "session_id" in obj) \
                    and "role" not in obj:             # root meta line (old format)
                native_id = native_id or obj.get("id") or obj.get("session_id")
                started = started or parse_ts(obj.get("timestamp"))
            # function_call / function_call_output / reasoning / token_count: skipped
        if not msgs:
            return None
        if not native_id:
            native_id = os.path.basename(path).split(".")[0]   # fallback: rollout-<ts>-<uuid>
        return build_session("codex", native_id, None, msgs, self.user_id, started=started)

    def _add_message(self, item: dict, msgs: list[Message]) -> None:
        role = normalize_role(item.get("role"))    # user/assistant only; system/developer -> None -> skip
        if role is None:
            return
        text = join_text_parts(item.get("content"))
        if text:
            msgs.append(Message(role=role, text=text))
