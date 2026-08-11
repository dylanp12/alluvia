"""OpenCode adapter (anomalyco/opencode, formerly sst/opencode). Storage is a
3-level tree under `<data>/opencode/storage/`: a session file, its messages, and
each message's parts (where the text actually lives). One session = one
`session/<projectID>/ses_*.json` + `message/<sessionID>/msg_*.json` +
`part/<messageID>/prt_*.json`. IDs are time-sortable, so filename order is
chronological. Version-tolerant: a malformed session is logged and skipped."""
from __future__ import annotations

import glob
import json
import logging
import os
from typing import Iterator

from alluvia.ingest.common import build_session, normalize_role, parse_ts
from alluvia.models import Message, RawSession

log = logging.getLogger(__name__)

# Part types whose `.text` is human-readable prose (everything else — tool, file,
# step-start/finish, snapshot, patch, agent, ... — is skipped for text extraction).
_TEXT_PARTS = ("text", "reasoning")


class OpenCodeAdapter:
    def __init__(self, root: str | None = None, user_id: str = "local"):
        from alluvia import config
        self._root = root or config.source_root("opencode")
        self.user_id = user_id

    def _storage_dirs(self) -> list[str]:
        # root override points straight at a `storage/` dir (as in tests / config).
        if self._root:
            return [self._root]
        xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        d = os.path.join(xdg, "opencode", "storage")
        return [d] if os.path.isdir(d) else []

    def read(self) -> Iterator[RawSession]:
        for base in self._storage_dirs():
            for sfile in glob.glob(os.path.join(base, "session", "*", "ses_*.json")):
                try:
                    s = self._session(base, sfile)
                except Exception as e:
                    log.warning("opencode: skipping session %s (%s)", sfile, e)
                    continue
                if s:
                    yield s

    def _session(self, base: str, sfile: str) -> RawSession | None:
        with open(sfile) as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            return None
        sid = meta.get("id") or os.path.basename(sfile)[:-5]   # strip ".json"
        msgs: list[Message] = []
        for mfile in sorted(glob.glob(os.path.join(base, "message", sid, "msg_*.json"))):
            try:
                with open(mfile) as f:
                    m = json.load(f)
            except Exception:
                continue
            if not isinstance(m, dict):
                continue
            role = normalize_role(m.get("role"))
            if role is None:
                continue
            mid = m.get("id") or os.path.basename(mfile)[:-5]
            text = self._message_text(base, mid)
            if text:
                msgs.append(Message(role=role, text=text))
        if not msgs:
            return None
        title = meta.get("title")
        started = parse_ts((meta.get("time") or {}).get("created"))
        return build_session("opencode", sid, title, msgs, self.user_id, started=started)

    def _message_text(self, base: str, mid: str) -> str:
        out: list[str] = []
        for pfile in sorted(glob.glob(os.path.join(base, "part", mid, "prt_*.json"))):
            try:
                with open(pfile) as f:
                    p = json.load(f)
            except Exception:
                continue
            if not isinstance(p, dict) or p.get("type") not in _TEXT_PARTS:
                continue
            if p.get("ignored") or p.get("synthetic"):
                continue
            t = p.get("text")
            if isinstance(t, str) and t:
                out.append(t)
        return "\n".join(out)
