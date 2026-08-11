"""Source registry: slug -> factory(path_override) -> Adapter. Factories lazy-import
their adapter so CLI startup stays light and there are no import cycles."""
from __future__ import annotations

from typing import Callable

from alluvia.ingest.base import Adapter


def _claude_code(path):
    from alluvia import config
    from alluvia.ingest.claude_code import ClaudeCodeAdapter
    from alluvia.platform import claude_code_root
    root = path or config.source_root("claude-code") or claude_code_root()
    return ClaudeCodeAdapter(root, user_id=config.DEFAULT_USER)


def _fork(flavor):
    def make(path):
        from alluvia import config
        from alluvia.ingest.vscode_fork import VSCodeForkAdapter
        return VSCodeForkAdapter(flavor, root=path, user_id=config.DEFAULT_USER)
    return make


def _jsonl(path):
    from alluvia import config
    from alluvia.ingest.jsonl_source import JsonlSourceAdapter
    if not path:
        raise ValueError("--path to a .jsonl file or directory is required")
    return JsonlSourceAdapter(path, user_id=config.DEFAULT_USER)


def _chatgpt(path):
    from alluvia import config
    from alluvia.ingest.chatgpt_export import ChatGPTExportAdapter
    if not path:
        raise ValueError("--path to the export ZIP/dir is required")
    return ChatGPTExportAdapter(path, user_id=config.DEFAULT_USER)


def _cline(flavor):
    def make(path):
        from alluvia import config
        from alluvia.ingest.cline_family import ClineFamilyAdapter
        return ClineFamilyAdapter(flavor, root=path, user_id=config.DEFAULT_USER)
    return make


def _opencode(path):
    from alluvia import config
    from alluvia.ingest.opencode import OpenCodeAdapter
    return OpenCodeAdapter(root=path, user_id=config.DEFAULT_USER)


def _codex(path):
    from alluvia import config
    from alluvia.ingest.codex import CodexAdapter
    return CodexAdapter(root=path, user_id=config.DEFAULT_USER)


def _gemini(path):
    from alluvia import config
    from alluvia.ingest.gemini import GeminiAdapter
    return GeminiAdapter(root=path, user_id=config.DEFAULT_USER)


SOURCES: dict[str, Callable[[str | None], Adapter]] = {
    "claude-code": _claude_code,
    "cursor": _fork("cursor"),
    "windsurf": _fork("windsurf"),
    "antigravity": _fork("antigravity"),
    "jsonl": _jsonl,
    "chatgpt-export": _chatgpt,
    "cline": _cline("cline"),
    "kilo-code": _cline("kilo-code"),
    "roo-code": _cline("roo-code"),
    "opencode": _opencode,
    "codex": _codex,
    "gemini": _gemini,
}
