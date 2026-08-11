from alluvia.distill.scrub import is_meta_message
from alluvia.models import Message, RawSession, content_hash, session_id
from alluvia.llm.client import FakeLLM
from alluvia.distill.distiller import Distiller


def test_is_meta_message_matches_markers():
    assert is_meta_message("Stop hook feedback:\nClaude evaluator determined ...")
    assert is_meta_message("Claude evaluator determined continuation is appropriate")
    assert not is_meta_message("design the retry policy for the api")


def test_is_meta_message_matches_injected_scaffolding():
    # runtime-injected content that lands in a user-role slot (issue #15)
    assert is_meta_message("[SYSTEM NOTIFICATION - NOT USER INPUT]\nbackground task completed")
    assert is_meta_message("This session is being continued from a previous conversation "
                           "that ran out of context. The summary below covers ...")
    assert not is_meta_message("continue the auth refactor we discussed earlier")


def test_render_drops_meta_messages_keeps_real_ones():
    msgs = [
        Message(role="user", text="Stop hook feedback:\nClaude evaluator determined X."),
        Message(role="user", text="how should we cache the results?"),
    ]
    s = RawSession(id=session_id("claude-code", "s1"), user_id="local",
                   source="claude-code", native_id="s1", title="t",
                   started_at=None, ended_at=None, messages=msgs,
                   content_hash=content_hash(msgs))
    captured = {}

    class Spy(FakeLLM):
        def complete_json(self, system, user):
            captured["user"] = user
            return super().complete_json(system, user)

    Distiller(Spy([{"notes": []}])).distill(s)
    assert "Stop hook feedback" not in captured["user"]
    assert "Claude evaluator" not in captured["user"]
    assert "cache the results" in captured["user"]
