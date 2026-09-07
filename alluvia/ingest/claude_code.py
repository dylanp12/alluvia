from __future__ import annotations
import glob
import json
import os
from datetime import datetime
from typing import Iterator
from alluvia.models import Message, RawSession, content_hash, session_id
from alluvia.distill.scrub import strip_wrappers


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _ts(v) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


MAX_ACTIONS_PER_MESSAGE = 20
_ACTION_ARG_CAP = 120


def _rel(path: str, cwd: str | None) -> str:
    """Path relative to the session's working directory, whichever separator
    the transcript uses; paths outside it stay absolute."""
    if cwd and isinstance(path, str):
        root = cwd.rstrip("/\\")
        for sep in ("/", "\\"):
            base = root + sep
            if path.startswith(base):
                return path[len(base):]
    return path


def _one_line(s, cap: int = _ACTION_ARG_CAP) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= cap else s[:cap] + "…"


def _action(block: dict, cwd: str | None) -> str:
    """One line per tool call: what was touched or run, never the payload."""
    name = block.get("name") or "tool"
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    if "file_path" in inp:
        return f"{name} {_rel(inp['file_path'], cwd)}"
    if name == "Bash" and "command" in inp:
        return f"Bash: {_one_line(inp['command'])}"
    for key in ("pattern", "url", "query", "description", "prompt", "skill"):
        if key in inp:
            return f"{name} {_one_line(inp[key], 80)}"
    return name


def _actions(content, cwd: str | None) -> list[str]:
    if not isinstance(content, list):
        return []
    acts = [_action(b, cwd) for b in content
            if isinstance(b, dict) and b.get("type") == "tool_use"]
    if len(acts) > MAX_ACTIONS_PER_MESSAGE:
        acts = acts[:MAX_ACTIONS_PER_MESSAGE] + [f"…{len(acts) - MAX_ACTIONS_PER_MESSAGE} more"]
    return acts


def _message_text(msg: dict, cwd: str | None) -> str:
    """Conversation text plus `[action]` lines for tool calls. Tool RESULTS are
    dropped (bulky, noisy); what the assistant did is kept, what it saw is not."""
    text = _text(msg.get("content")).strip()
    acts = _actions(msg.get("content"), cwd) if msg.get("role") == "assistant" else []
    lines = ([text] if text else []) + [f"[action] {a}" for a in acts]
    return "\n".join(lines)


# Harness-generated evaluation transcripts (stop-hook continuation judges,
# workflow critics) are stored as ordinary session files but are NOT the
# user's thinking. No metadata distinguishes them (probed 2026-07-02: fields
# identical to normal sessions), but their first message is machine-generated
# boilerplate — a stable signature. Real-data census: 586 of ~694 sessions.
META_SESSION_MARKERS = (
    "Analyze this conversation and determine",
    "You are a completeness critic",
)


def _is_meta_session(messages: list[Message]) -> bool:
    for m in messages:
        if m.role == "user":
            head = strip_wrappers(m.text)[:200]
            return any(marker in head for marker in META_SESSION_MARKERS)
    return False


class ClaudeCodeAdapter:
    """Reads Claude Code JSONL logs.

    Each *file* is one session — the file's UUID is the identity, because the
    internal ``sessionId`` is shared by subagent transcripts and collapses them.
    ``isSidechain`` lines (subagent/tool scratch work) are dropped so the corpus
    is the user's own conversation threads, and non-message events are ignored.
    """

    def __init__(self, root: str, user_id: str = "local"):
        self.root = root
        self.user_id = user_id

    def read(self) -> Iterator[RawSession]:
        for path in sorted(glob.glob(os.path.join(self.root, "**", "*.jsonl"), recursive=True)):
            session = self._read_file(path)
            if session is not None:
                yield session

    def read_file(self, path: str) -> RawSession | None:
        """One transcript file → one session (hooks ingest the live transcript)."""
        return self._read_file(path)

    def _read_file(self, path: str) -> RawSession | None:
        from alluvia.projects import project_root
        native_id = os.path.splitext(os.path.basename(path))[0]
        messages: list[Message] = []
        cwd: str | None = None
        branch: str | None = None
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # partial/non-JSON lines occur in real logs
                if not isinstance(obj, dict):
                    continue
                if cwd is None and isinstance(obj.get("cwd"), str) and obj["cwd"]:
                    cwd = obj["cwd"]
                if branch is None and isinstance(obj.get("gitBranch"), str) and obj["gitBranch"]:
                    branch = obj["gitBranch"]
                if obj.get("isSidechain"):
                    continue  # subagent/sidechain scratch work — not the user's thread
                if obj.get("isMeta"):
                    continue  # harness-injected user-slot content (skill bodies,
                    #           command expansions) — not the user's thinking
                if obj.get("type") not in ("user", "assistant"):
                    continue  # skip attachments, snapshots, progress, etc.
                msg = obj.get("message")
                if not isinstance(msg, dict):
                    continue
                text = _message_text(msg, cwd)
                if not text:
                    continue
                role = msg.get("role") or obj.get("type") or "user"
                messages.append(Message(role=role, text=text, ts=_ts(obj.get("timestamp"))))
        if not messages:
            return None  # sidechain-only / eventless file — not a user session
        if _is_meta_session(messages):
            return None  # harness-generated judge/critic transcript — not the user's thinking
        return RawSession(
            id=session_id("claude-code", native_id), user_id=self.user_id,
            source="claude-code", native_id=native_id,
            title=next((strip_wrappers(m.text)[:60] for m in messages
                        if strip_wrappers(m.text)), native_id),
            started_at=messages[0].ts, ended_at=messages[-1].ts, messages=messages,
            content_hash=content_hash(messages),
            project=project_root(cwd), branch=branch,
        )
