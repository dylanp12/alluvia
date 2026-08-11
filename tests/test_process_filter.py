from alluvia.distill.scrub import is_process_note


def test_process_chatter_is_flagged():
    for t in [
        "The assistant should pause and wait for the user to provide guidance on how to proceed.",
        "No autonomous work currently available; blocked on user input.",
        "Session configured with bypassPermissions in normal mode.",
        "The assistant marked task ID 2 as completed using the TaskUpdate tool.",
        "The assistant should not continue autonomously and must respond to the user's question.",
        "The assistant will wait for additional context before performing the commit.",
        "The assistant concluded that it has no more autonomous work to do right now.",
        "The assistant decided to stop because it is waiting for clarification about next steps.",
        "The assistant set should_continue to false, indicating no further autonomous execution.",
    ]:
        assert is_process_note(t), t


def test_real_decisions_survive():
    for t in [
        "The PR does the right architectural thing, but it is not mergeable as-is.",
        "Use a token service with middleware.",
        "The assistant should validate the bet before submitting it.",
        "We'll store sessions in Postgres over SQLite for the cloud.",
        "The refresh token double-fires because two tabs race the same token.",
    ]:
        assert not is_process_note(t), t


def test_distiller_drops_process_notes():
    from alluvia.distill.distiller import Distiller
    from alluvia.llm.client import FakeLLM
    from alluvia.models import Message, RawSession, content_hash, session_id

    msgs = [Message(role="user", text="hi"), Message(role="assistant", text="ok")]
    session = RawSession(
        id=session_id("claude-code", "s1"), user_id="local", source="claude-code",
        native_id="s1", title="t", started_at=None, ended_at=None,
        messages=msgs, content_hash=content_hash(msgs))
    llm = FakeLLM([{"notes": [
        {"kind": "decision", "text": "The assistant should pause and wait for guidance.", "span": "msg:1"},
        {"kind": "decision", "text": "Use a token service with middleware.", "span": "msg:1"},
        {"kind": "insight", "text": "No autonomous work available; blocked on user input.", "span": "msg:0"},
    ]}])
    notes = Distiller(llm).distill(session)
    assert [n.text for n in notes] == ["Use a token service with middleware."]
