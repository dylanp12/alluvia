from __future__ import annotations
import hashlib
from alluvia.llm.client import LLM
from alluvia.models import Note, RawSession
from alluvia.distill.scrub import redact, strip_wrappers, is_meta_message, is_process_note

_SYSTEM = (
    "You extract atomic, reusable knowledge from a developer's AI chat session. "
    "Return JSON: {\"notes\":[{\"kind\":one of idea|decision|question|problem|insight,"
    "\"text\":a single self-contained sentence,\"span\":\"msg:<index>\" of the source message}]}. "
    "Keep only substantive DOMAIN knowledge: technical ideas, decisions, problems, "
    "questions, insights. A 'decision' is a DURABLE choice about the domain with a "
    "consequence (e.g. \"use Postgres over SQLite\") — NOT a status report or a step "
    "the assistant took. NEVER extract statements about the assistant's OWN actions, "
    "workflow, waiting, permissions, tool calls, or task state: pauses, "
    "waiting-for-user, continuation/permission requests, session management, tool or "
    "hook chatter. If a sentence's subject is the assistant and its predicate is a "
    "process step, drop it. Do not invent content. "
    "Lines beginning with [action] record files the assistant edited or read and "
    "commands it ran; use them to name the file or command a note is about (e.g. "
    "\"fixed the rotation race in auth/refresh.py\"), but NEVER turn an action line "
    "itself into a note."
)


PROMPT_HASH = hashlib.sha256(_SYSTEM.encode("utf-8")).hexdigest()[:16]

MSG_CHAR_CAP = 2000        # per-message cap: long tool dumps add noise, not signal
RENDER_CHAR_CAP = 16000    # legacy single-render cap (see _render)
# Measured 2026-09-05 on the shipped provider (Groq, gpt-oss-120b): a 16k-char
# render comes back as an EMPTY generation and json_validate_failed, while 8k
# windows distill fine. Long sessions are rendered as bounded windows; the last
# window is always kept because decisions land at the end of a session, and
# the call count per session is capped.
WINDOW_CHARS = 8000
MAX_WINDOWS = 4


def _lines(session: RawSession) -> list[str]:
    lines = []
    for i, m in enumerate(session.messages):
        if is_meta_message(m.text):
            continue                      # harness meta-noise: never reaches the LLM
        cleaned = strip_wrappers(m.text)
        if not cleaned:
            continue                      # wrapper-only message: skip entirely
        if len(cleaned) > MSG_CHAR_CAP:
            cleaned = cleaned[:MSG_CHAR_CAP] + " …[truncated]"
        lines.append(f"msg:{i} [{m.role}] {redact(cleaned)}")
    return lines


def _render(session: RawSession) -> str:
    """Single head-first render, capped (kept for callers that want one prompt)."""
    out, total = [], 0
    for line in _lines(session):
        if total + len(line) > RENDER_CHAR_CAP:
            out.append("…[session truncated for length]")
            break
        out.append(line)
        total += len(line)
    return "\n".join(out)


def _render_windows(session: RawSession) -> list[str]:
    """Consecutive windows of at most WINDOW_CHARS. When a session needs more
    than MAX_WINDOWS, keep the first, the last, and evenly spaced middles."""
    windows: list[list[str]] = [[]]
    total = 0
    for line in _lines(session):
        if windows[-1] and total + len(line) > WINDOW_CHARS:
            windows.append([])
            total = 0
        windows[-1].append(line)
        total += len(line)
    if not windows[0]:
        return []
    n = len(windows)
    if n > MAX_WINDOWS:
        keep = sorted({0, n - 1} | {round(k * (n - 1) / (MAX_WINDOWS - 1))
                                    for k in range(1, MAX_WINDOWS - 1)})
        windows = [windows[i] for i in keep]
    return ["\n".join(w) for w in windows]


def _note_id(session_id: str, text: str) -> str:
    h = hashlib.sha256(f"{session_id}\n{text}".encode("utf-8")).hexdigest()[:16]
    return f"note:{h}"


class Distiller:
    def __init__(self, llm: LLM):
        self.llm = llm
        self.last_partial = False   # True when the provider cut a multi-window
        #                             run short: notes are real but incomplete,
        #                             so the session must not be marked done

    def distill(self, session: RawSession) -> list[Note]:
        """One LLM call per window (bounded by MAX_WINDOWS), notes merged and
        deduplicated by content id. A window the provider rejects as invalid
        JSON is skipped when other windows succeed; if every window is
        rejected the error propagates so callers apply their zero-note rule.
        A provider limit mid-run keeps the windows already distilled and
        sets `last_partial` instead of throwing them away."""
        from alluvia.llm.governor import LLMUnavailable
        raw_notes: list[dict] = []
        rejected: Exception | None = None
        partial = False
        windows = _render_windows(session)
        for window in windows:
            try:
                result = self.llm.complete_json(_SYSTEM, window)
            except LLMUnavailable:
                if raw_notes:
                    partial = True
                    break
                raise
            except Exception as e:
                if "json_validate_failed" in str(e) and len(windows) > 1:
                    rejected = e
                    continue
                raise
            if isinstance(result, dict):
                raw_notes.extend(result.get("notes", []) or [])
        if rejected is not None and not raw_notes:
            raise rejected
        self.last_partial = partial
        notes: list[Note] = []
        seen: set[str] = set()
        for rn in raw_notes:
            text = (rn.get("text") or "").strip()
            if not text:
                continue
            if is_process_note(text):
                continue                      # agent-process chatter the LLM kept: not domain knowledge
            nid = _note_id(session.id, text)
            if nid in seen:
                continue
            seen.add(nid)
            notes.append(Note(
                id=nid, user_id=session.user_id, session_id=session.id,
                span_ref=rn.get("span", ""), kind=rn.get("kind", "insight"),
                text=text, created_at=session.started_at, canonical_id=None,
            ))
        return notes
