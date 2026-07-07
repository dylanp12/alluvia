from alluvia.models import RawSession, Message, session_id, content_hash


def _session(user="local", native="s1", text="hi"):
    msgs = [Message(role="user", text=text)]
    return RawSession(
        id=session_id("claude-code", native), user_id=user, source="claude-code",
        native_id=native, title="t", started_at=None, ended_at=None,
        messages=msgs, content_hash=content_hash(msgs),
    )


def test_upsert_is_idempotent_on_content_hash(repo):
    s = _session()
    assert repo.upsert_session(s) is True     # inserted
    assert repo.upsert_session(s) is False    # unchanged -> no-op
    assert len(repo.list_sessions("local")) == 1


def test_changed_content_updates_and_reports_true(repo):
    repo.upsert_session(_session(text="hi"))
    assert repo.upsert_session(_session(text="different")) is True
    got = repo.get_session("local", "claude-code:s1")
    assert got.messages[0].text == "different"


def test_user_isolation(repo):
    repo.upsert_session(_session(user="a", native="x"))
    repo.upsert_session(_session(user="b", native="y"))
    assert [s.native_id for s in repo.list_sessions("a")] == ["x"]
    assert repo.get_session("a", "claude-code:y") is None
