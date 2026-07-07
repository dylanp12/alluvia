from __future__ import annotations
import hashlib
from alluvia.llm.client import LLM
from alluvia.models import Note, RawSession
from alluvia.distill.scrub import scrub_secrets, strip_wrappers, is_meta_message

_SYSTEM = (
    "You extract atomic, reusable knowledge from a developer's AI chat session. "
    "Return JSON: {\"notes\":[{\"kind\":one of idea|decision|question|problem|insight,"
    "\"text\":a single self-contained sentence,\"span\":\"msg:<index>\" of the source message}]}. "
    "Keep only substantive DOMAIN knowledge: technical ideas, decisions, problems, "
    "questions, insights. IGNORE conversation-process content entirely — pauses, "
    "waiting-for-user, continuation/permission requests, session management, tool "
    "or hook chatter, and anything about the assistant's own workflow. "
    "Do not invent content."
)


MSG_CHAR_CAP = 2000        # per-message cap: long tool dumps add noise, not signal
RENDER_CHAR_CAP = 16000    # total prompt cap: keeps big sessions inside context/TPM


def _render(session: RawSession) -> str:
    lines = []
    total = 0
    for i, m in enumerate(session.messages):
        if is_meta_message(m.text):
            continue                      # harness meta-noise: never reaches the LLM
        cleaned = strip_wrappers(m.text)
        if not cleaned:
            continue                      # wrapper-only message: skip entirely
        if len(cleaned) > MSG_CHAR_CAP:
            cleaned = cleaned[:MSG_CHAR_CAP] + " …[truncated]"
        line = f"msg:{i} [{m.role}] {scrub_secrets(cleaned)}"
        if total + len(line) > RENDER_CHAR_CAP:
            lines.append("…[session truncated for length]")
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def _note_id(session_id: str, text: str) -> str:
    h = hashlib.sha256(f"{session_id}\n{text}".encode("utf-8")).hexdigest()[:16]
    return f"note:{h}"


class Distiller:
    def __init__(self, llm: LLM):
        self.llm = llm

    def distill(self, session: RawSession) -> list[Note]:
        result = self.llm.complete_json(_SYSTEM, _render(session))
        raw_notes = result.get("notes", []) if isinstance(result, dict) else []
        notes: list[Note] = []
        seen: set[str] = set()
        for rn in raw_notes:
            text = (rn.get("text") or "").strip()
            if not text:
                continue
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
