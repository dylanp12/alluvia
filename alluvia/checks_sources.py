"""Attributed source receipts for regression checks; no inference or store writes."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from alluvia.distill.scrub import is_meta_message, redact, strip_wrappers
from alluvia.projects import project_key


class SourceError(ValueError):
    """A requested note cannot supply scoped, usable source evidence."""


def _identity(path: str | Path) -> tuple[Path, Path]:
    try:
        root = subprocess.run(
            ["git", "-C", str(Path(path).resolve()), "rev-parse", "--show-toplevel"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        common = subprocess.run(
            ["git", "-C", root, "rev-parse", "--git-common-dir"],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SourceError("Source project must be an accessible Git repository.") from exc
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = Path(root) / common_path
    return Path(root).resolve(), common_path.resolve()


def note_source(repo, user_id: str, note_id: str, project: str | Path) -> dict:
    """Quote the original message with its role, scope and immutable content hash.

    This attributes a recorded statement; it does not establish that the statement
    is correct, current, or an authoritative user instruction.
    """
    note = next((note for note in repo.get_notes(user_id) if note.id == note_id), None)
    if note is None:
        raise SourceError("No source note with that id.")
    if note_id in repo.suppressed_note_ids(user_id):
        raise SourceError("The source note was forgotten; choose an active correction.")
    session = repo.get_session(user_id, note.session_id)
    if session is None or not session.project:
        raise SourceError("The source has no recorded project scope.")
    root, identity = _identity(project)
    _, recorded_identity = _identity(session.project)
    if identity != recorded_identity:
        raise SourceError("The source belongs to a different project.")
    match = re.fullmatch(r"msg:(\d+)", note.span_ref or "")
    if not match or int(match.group(1)) >= len(session.messages):
        raise SourceError("The source note has no usable message reference.")
    message = session.messages[int(match.group(1))]
    if is_meta_message(message.text):
        raise SourceError("The source is a harness message, not a project correction.")
    text = redact(strip_wrappers(message.text)).strip()
    if not text:
        raise SourceError("The source message contains no usable text.")
    return {
        "kind": "history_note", "text": text[:4000], "role": message.role,
        "truncated": len(text) > 4000, "note_id": note.id,
        "note_text": redact(note.text), "session_id": session.id,
        "span_ref": note.span_ref, "content_hash": session.content_hash,
        "project": {"name": root.name, "key": project_key(str(root))},
        "branch": session.branch,
        "authority": "Recorded source; inspect its role and applicability before using it.",
    }
