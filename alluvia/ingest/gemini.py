"""Gemini CLI adapter (google-gemini/gemini-cli). Auto-saved conversation history
lives under `<home>/.gemini/tmp/<id>/chats/` as either JSONL (line 1 = metadata,
then turns interleaved with `$set`/`$rewindTo` control records) or a single JSON
object with a `messages` array. Turns use `type` ("user"|"gemini") — NOT `role` —
with text under `content` (a string or a list of `{text}` parts). Tool-call parts
(functionCall/functionResponse) carry no text and drop out naturally."""
from __future__ import annotations

import glob
import json
import logging
import os
from typing import Iterator

from alluvia.ingest.common import build_session, join_text_parts, normalize_role, parse_ts
from alluvia.models import Message, RawSession

log = logging.getLogger(__name__)


class GeminiAdapter:
    def __init__(self, root: str | None = None, user_id: str = "local"):
        from alluvia import config
        if root or config.source_root("gemini"):
            self._root = root or config.source_root("gemini")
        else:
            home = os.environ.get("GEMINI_CLI_HOME") or os.path.expanduser("~")
            self._root = os.path.join(home, ".gemini")
        self.user_id = user_id

    def read(self) -> Iterator[RawSession]:
        best: dict[str, RawSession] = {}
        chats = os.path.join(self._root, "tmp", "*", "chats")
        files = (glob.glob(os.path.join(chats, "**", "*.jsonl"), recursive=True)
                 + glob.glob(os.path.join(chats, "**", "*.json"), recursive=True))
        for f in files:
            try:
                s = self._session(f)
            except Exception as e:
                log.warning("gemini: skipping %s (%s)", f, e)
                continue
            if s and (s.native_id not in best or len(s.messages) > len(best[s.native_id].messages)):
                best[s.native_id] = s
        yield from best.values()

    def _session(self, path: str) -> RawSession | None:
        if path.endswith(".jsonl"):
            native_id, started, title, msgs = self._read_jsonl(path)
        else:
            native_id, started, title, msgs = self._read_json(path)
        if not msgs:
            return None
        if not native_id:
            native_id = os.path.basename(path).rsplit(".", 1)[0]
        return build_session("gemini", native_id, title, msgs, self.user_id, started=started)

    def _read_jsonl(self, path: str):
        native_id = started = title = None
        msgs: list[Message] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(obj, dict) or "$set" in obj or "$rewindTo" in obj:
                    continue                                   # control record, not a turn
                if "type" in obj and "id" in obj:              # a conversation turn
                    m = self._message(obj)
                    if m:
                        msgs.append(m)
                elif "sessionId" in obj or "startTime" in obj:  # the metadata record (line 1)
                    native_id = native_id or obj.get("sessionId")
                    started = started or parse_ts(obj.get("startTime"))
                    title = title or obj.get("summary")
        return native_id, started, title, msgs

    def _read_json(self, path: str):
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
        if not isinstance(obj, dict):
            return None, None, None, []
        native_id = obj.get("sessionId")
        started = parse_ts(obj.get("startTime"))
        title = obj.get("summary")
        msgs = [m for m in (self._message(d) for d in (obj.get("messages") or [])) if m]
        return native_id, started, title, msgs

    def _message(self, d) -> Message | None:
        if not isinstance(d, dict):
            return None
        role = normalize_role(d.get("type") or d.get("role"))  # user/gemini(->assistant); info/error -> None
        if role is None:
            return None
        text = join_text_parts(d.get("content", d.get("parts")))
        if not text:
            return None                                        # tool-only turns have no text -> skip
        return Message(role=role, text=text)
