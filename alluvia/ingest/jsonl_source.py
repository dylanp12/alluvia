"""Normalized-session JSONL source — the public ingestion contract.

Any feeder (an archiver like pond, an rsync of another machine, a one-off
script) that writes the schema documented in docs/SOURCES.md becomes an
alluvia source. Community tools own their parsers; alluvia owns the
contract. Invalid lines are logged and skipped, never fatal — the
log-and-skip convention all adapters share."""
from __future__ import annotations

import glob
import json
import logging
import os
from datetime import datetime
from typing import Iterator

from alluvia.models import Message, RawSession, content_hash, session_id

log = logging.getLogger(__name__)


def _ts(raw) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


class JsonlSourceAdapter:
    def __init__(self, path: str, user_id: str):
        self.path = path
        self.user_id = user_id

    def _files(self) -> list[str]:
        if os.path.isdir(self.path):
            return sorted(glob.glob(os.path.join(self.path, "**", "*.jsonl"),
                                    recursive=True))
        return [self.path]

    def read(self) -> Iterator[RawSession]:
        for fp in self._files():
            try:
                lines = open(fp, encoding="utf-8", errors="replace")
            except OSError as e:
                log.warning("jsonl source: cannot read %s (%s) — skipped", fp, e)
                continue
            with lines:
                for n, line in enumerate(lines, 1):
                    line = line.strip()
                    if not line:
                        continue
                    s = self._parse(line, f"{fp}:{n}")
                    if s is not None:
                        yield s

    def _parse(self, line: str, where: str) -> RawSession | None:
        try:
            obj = json.loads(line)
        except ValueError:
            log.warning("jsonl source: %s is not JSON — skipped", where)
            return None
        source = obj.get("source")
        native = obj.get("native_id")
        raw_msgs = obj.get("messages") or []
        msgs = [Message(role=m.get("role", ""), text=m.get("text", ""),
                        ts=_ts(m.get("ts")))
                for m in raw_msgs
                if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                and (m.get("text") or "").strip()]
        if not source or not native or not msgs:
            log.warning("jsonl source: %s missing source/native_id/messages — "
                        "skipped", where)
            return None
        return RawSession(
            id=session_id(str(source), str(native)), user_id=self.user_id,
            source=str(source), native_id=str(native),
            title=str(obj.get("title") or msgs[0].text[:60]),
            started_at=_ts(obj.get("started_at")),
            ended_at=_ts(obj.get("ended_at")),
            messages=msgs, content_hash=content_hash(msgs))
