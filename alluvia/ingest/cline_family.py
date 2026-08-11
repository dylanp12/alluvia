"""Cline-family adapter: Cline, Kilo Code, Roo Code — VS Code extensions that store
each task under globalStorage/<ext>/tasks/<id>/, with the transcript in
api_conversation_history.json (Anthropic Messages format). One parser, three
publishers. Version-tolerant: a malformed task is logged and skipped, never fatal."""
from __future__ import annotations

import glob
import json
import logging
import os
from typing import Iterator

from alluvia.ingest.common import anthropic_text, build_session, normalize_role, parse_ts
from alluvia.models import Message, RawSession

log = logging.getLogger(__name__)

_EXTS = {
    "cline": "saoudrizwan.claude-dev",
    "kilo-code": "kilocode.kilo-code",
    "roo-code": "rooveterinaryinc.roo-cline",
}


class ClineFamilyAdapter:
    def __init__(self, flavor: str, root: str | None = None, user_id: str = "local"):
        from alluvia import config
        self.flavor = flavor
        self.ext = _EXTS[flavor]
        self._root = root or config.source_root(flavor)
        self.user_id = user_id

    def _ext_dirs(self) -> list[str]:
        # root override = an editor root (as in vscode_fork); the ext dir lives under it
        if self._root:
            return [os.path.join(self._root, "User", "globalStorage", self.ext)]
        from alluvia.platform import vscode_extension_dirs
        return vscode_extension_dirs(self.ext)

    def read(self) -> Iterator[RawSession]:
        best: dict[str, RawSession] = {}
        for base in self._ext_dirs():
            for hist in glob.glob(os.path.join(base, "tasks", "*", "api_conversation_history.json")):
                try:
                    s = self._session_from_task(hist)
                except Exception as e:
                    log.warning("cline(%s): skipping task %s (%s)", self.flavor, hist, e)
                    continue
                if s and (s.id not in best or len(s.messages) > len(best[s.id].messages)):
                    best[s.id] = s
        yield from best.values()

    def _session_from_task(self, hist_path: str) -> RawSession | None:
        task_dir = os.path.dirname(hist_path)
        native_id = os.path.basename(task_dir)
        with open(hist_path) as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            return None
        msgs: list[Message] = []
        for m in raw:
            if not isinstance(m, dict):
                continue
            role = normalize_role(m.get("role"))
            if role is None:
                continue
            text = anthropic_text(m.get("content"))
            if text:
                msgs.append(Message(role=role, text=text))
        if not msgs:
            return None
        title, started = self._meta(task_dir, native_id)
        return build_session(self.flavor, native_id, title, msgs, self.user_id, started=started)

    def _meta(self, task_dir: str, native_id: str):
        title = None
        started = parse_ts(int(native_id)) if native_id.isdigit() else None  # Cline task ids are epoch-ms
        meta_path = os.path.join(task_dir, "task_metadata.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                if isinstance(meta, dict):
                    title = meta.get("title") or meta.get("task")
                    started = parse_ts(meta.get("ts") or meta.get("createdAt")) or started
            except Exception:
                pass
        return title, started
