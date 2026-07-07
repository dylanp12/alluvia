from datetime import datetime
from alluvia.models import Message, RawSession, session_id, content_hash


def test_session_id_is_stable_and_source_scoped():
    assert session_id("claude-code", "abc") == "claude-code:abc"


def test_content_hash_ignores_object_identity_but_tracks_text():
    m1 = [Message(role="user", text="hi", ts=None)]
    m2 = [Message(role="user", text="hi", ts=None)]
    m3 = [Message(role="user", text="bye", ts=None)]
    assert content_hash(m1) == content_hash(m2)
    assert content_hash(m1) != content_hash(m3)
