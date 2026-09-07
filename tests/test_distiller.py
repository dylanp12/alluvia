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


def test_prompt_teaches_action_lines_and_render_keeps_them():
    from alluvia.distill.distiller import _SYSTEM, _render
    from alluvia.models import Message, RawSession, content_hash
    msgs = [Message(role="user", text="fix the race"),
            Message(role="assistant", text="Pinned clock skew.\n[action] Edit auth/refresh.py")]
    s = RawSession(id="claude-code:x", user_id="local", source="claude-code", native_id="x",
                   title="t", started_at=None, ended_at=None, messages=msgs,
                   content_hash=content_hash(msgs))
    assert "[action]" in _SYSTEM and "never" in _SYSTEM.lower()
    assert "[action] Edit auth/refresh.py" in _render(s)


def _long_session():
    from alluvia.models import Message, RawSession, content_hash
    filler = "x" * 1500
    msgs = [Message(role="user", text="we need to decide on the cache layer")]
    msgs += [Message(role="assistant", text=f"exploring option {i} {filler}") for i in range(30)]
    msgs += [Message(role="user", text="ok, decided: content-hash keys, invalidate on push only")]
    return RawSession(id="claude-code:long", user_id="local", source="claude-code", native_id="long",
                      title="t", started_at=None, ended_at=None, messages=msgs,
                      content_hash=content_hash(msgs))


def test_long_sessions_render_as_bounded_windows_that_include_the_tail():
    """Measured 2026-09-05 on the shipped provider: a 16k-char render is
    rejected (empty generation, json_validate_failed) while 8k head or tail
    windows distill fine. Decisions land at the END of a session, so the
    last window is always kept; the call count is bounded."""
    from alluvia.distill.distiller import MAX_WINDOWS, WINDOW_CHARS, _render_windows
    s = _long_session()
    wins = _render_windows(s)
    assert 2 <= len(wins) <= MAX_WINDOWS
    assert all(len(w) <= WINDOW_CHARS + 200 for w in wins)
    assert "msg:0 [user] we need to decide" in wins[0]
    assert f"msg:{len(s.messages) - 1} [user] ok, decided: content-hash keys" in wins[-1]


def test_distill_merges_notes_across_windows():
    from alluvia.distill.distiller import Distiller
    from alluvia.llm.client import FakeLLM
    s = _long_session()
    llm = FakeLLM([{"notes": [{"kind": "question", "text": "which cache layer", "span": "msg:0"}]},
                   {"notes": [{"kind": "idea", "text": "option 12 looked viable", "span": "msg:13"}]},
                   {"notes": [{"kind": "idea", "text": "option 24 looked viable", "span": "msg:25"}]},
                   {"notes": [{"kind": "decision", "text": "content-hash keys, invalidate on push only",
                               "span": "msg:31"},
                              {"kind": "question", "text": "which cache layer", "span": "msg:0"}]}])
    notes = Distiller(llm).distill(s)
    assert [n.text for n in notes] == ["which cache layer", "option 12 looked viable",
                                       "option 24 looked viable",
                                       "content-hash keys, invalidate on push only"]   # deduped


def test_partial_distill_keeps_earlier_windows_and_flags_partial():
    """A provider limit in the middle of a long session must not throw away
    the windows that already came back. The result is returned as partial so
    the caller does NOT mark the session done — the rest is picked up later."""
    from alluvia.distill.distiller import Distiller
    from alluvia.llm.governor import LLMUnavailable
    s = _long_session()
    calls = {"n": 0}

    class Flaky:
        def complete_json(self, system, user):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"notes": [{"kind": "question", "text": "which cache layer", "span": "msg:0"}]}
            raise LLMUnavailable(0, "per-minute limit")
    d = Distiller(Flaky())
    notes = d.distill(s)
    assert [n.text for n in notes] == ["which cache layer"]
    assert d.last_partial is True
    # a clean run resets the flag
    d2 = Distiller(type("Ok", (), {"complete_json": lambda self, a, b: {"notes": []}})())
    d2.distill(s)
    assert d2.last_partial is False
