from alluvia.models import Message, RawSession, content_hash, session_id
from alluvia.llm.client import FakeLLM
from alluvia.distill.distiller import Distiller


def _session():
    msgs = [
        Message(role="user", text="Should auth be a separate service? my key is sk-ant-api03-SECRET99999"),
        Message(role="assistant", text="Yes, a token service with middleware."),
    ]
    return RawSession(
        id=session_id("claude-code", "s1"), user_id="local", source="claude-code",
        native_id="s1", title="auth", started_at=None, ended_at=None,
        messages=msgs, content_hash=content_hash(msgs),
    )


def test_distills_notes_with_kind_and_span():
    captured = {}

    class SpyLLM(FakeLLM):
        def complete_json(self, system, user):
            captured["user"] = user
            return super().complete_json(system, user)

    llm = SpyLLM([{"notes": [
        {"kind": "question", "text": "Should auth be its own service?", "span": "msg:0"},
        {"kind": "decision", "text": "Use a token service with middleware.", "span": "msg:1"},
    ]}])
    notes = Distiller(llm).distill(_session())
    assert [n.kind for n in notes] == ["question", "decision"]
    assert notes[0].session_id == "claude-code:s1"
    assert notes[0].span_ref == "msg:0"
    assert all(n.user_id == "local" for n in notes)
    # secrets never reach the model:
    assert "sk-ant-api03-SECRET99999" not in captured["user"]
    assert "[REDACTED]" in captured["user"]
    # deterministic ids derived from content:
    again = Distiller(FakeLLM([{"notes": [
        {"kind": "question", "text": "Should auth be its own service?", "span": "msg:0"},
        {"kind": "decision", "text": "Use a token service with middleware.", "span": "msg:1"},
    ]}])).distill(_session())
    assert {n.id for n in notes} == {n.id for n in again}
