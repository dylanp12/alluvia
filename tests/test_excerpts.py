"""Receipts: verbatim, wrapper-stripped, secret-redacted quotes from the raw
session a note was distilled from. Raw store is never touched — excerpts are
sliced fresh on demand."""
from __future__ import annotations
from datetime import datetime

from alluvia.excerpts import EXCERPT_CHAR_CAP, note_excerpt
from alluvia.models import Message, Note, RawSession

BASE = datetime(2026, 1, 1)


def _session(repo, sid: str = "claude-code:s1", texts: list[str] | None = None):
    msgs = [Message(role="user" if i % 2 == 0 else "assistant", text=t, ts=BASE)
            for i, t in enumerate(texts or ["question about tokens",
                                            "the fix: pin the clock skew in refresh"])]
    repo.upsert_session(RawSession(
        id=sid, user_id="local", source=sid.split(":", 1)[0], native_id="n1",
        title="t", started_at=BASE, ended_at=BASE, messages=msgs,
        content_hash=f"h-{sid}-{len(msgs)}"))


def _note(nid: str = "note:1", sid: str = "claude-code:s1",
          span: str = "msg:1") -> Note:
    return Note(id=nid, user_id="local", session_id=sid, span_ref=span,
                kind="insight", text="distilled summary", created_at=BASE)


def test_resolves_span_to_that_messages_verbatim_text(repo):
    _session(repo)
    got = note_excerpt(repo, "local", _note(span="msg:1"))
    assert got == "the fix: pin the clock skew in refresh"


def test_secrets_are_redacted_from_receipts(repo):
    _session(repo, texts=["q", "use key sk_live_abcdefghijklmnop1234 for stripe"])
    got = note_excerpt(repo, "local", _note(span="msg:1"))
    assert "sk_live_" not in got
    assert "[REDACTED]" in got


def test_long_messages_are_capped(repo):
    _session(repo, texts=["q", "x" * 2000])
    got = note_excerpt(repo, "local", _note(span="msg:1"))
    assert len(got) <= EXCERPT_CHAR_CAP


def test_meta_scaffolding_is_never_a_receipt(repo):
    """A receipt quoting harness scaffolding is worse than no receipt — the
    raw store is unfiltered by design, so the slicer must decline."""
    _session(repo, texts=[
        "q",
        "Context: This summary will be shown in a list to help users and "
        "Claude choose which conversations are relevant.\n\nPlease write a "
        "concise, factual summary of this conversation."])
    assert note_excerpt(repo, "local", _note(span="msg:1")) is None


def test_unresolvable_spans_return_none(repo):
    _session(repo)
    assert note_excerpt(repo, "local", _note(span="msg:99")) is None      # out of range
    assert note_excerpt(repo, "local", _note(span="banana")) is None      # malformed
    assert note_excerpt(repo, "local", _note(span="")) is None            # absent
    assert note_excerpt(repo, "local", _note(sid="gone:s9")) is None      # no session


def test_repo_exposes_the_receipt_seam(repo):
    """recall reaches receipts through the store, so cloud stores can answer
    from synced excerpts instead of raw sessions."""
    _session(repo)
    assert repo.note_excerpt("local", _note(span="msg:1")) \
        == "the fix: pin the clock skew in refresh"
