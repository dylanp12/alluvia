from alluvia.models import Message, RawSession, content_hash, session_id
from alluvia.engine.engine import Engine
from alluvia.engine.embed import FakeEmbedder
from alluvia.llm.client import FakeLLM


def _sess(native, text="hello"):
    msgs = [Message(role="user", text=text)]
    return RawSession(id=session_id("claude-code", native), user_id="local",
                      source="claude-code", native_id=native, title="t",
                      started_at=None, ended_at=None, messages=msgs,
                      content_hash=content_hash(msgs))


def test_zero_note_session_marked_done_and_not_redistilled(repo):
    repo.upsert_session(_sess("empty"))
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": []}]), min_cluster_size=2)
    eng.refresh("local")
    assert repo.distilled_session_ids("local") == {"claude-code:empty"}
    # second refresh: FakeLLM has no responses left -> would raise if re-distilled
    eng2 = Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2)
    eng2.refresh("local")                                  # must not call the LLM


class JsonHijackedLLM:
    def complete_json(self, system, user):
        raise RuntimeError(
            "Error code: 400 - {'code': 'json_validate_failed', "
            "'failed_generation': 'the assistant is waiting'}")


def test_json_validate_failed_marks_session_as_zero_note(repo):
    repo.upsert_session(_sess("meta", text="Analyze this conversation and determine..."))
    eng = Engine(repo, FakeEmbedder(dim=8), JsonHijackedLLM(), min_cluster_size=2)
    eng.refresh("local")                                   # must not raise or loop
    assert repo.distilled_session_ids("local") == {"claude-code:meta"}
    assert repo.get_notes("local") == []


def test_marker_union_backfills_pre_marker_sessions(repo):
    # a session distilled BEFORE the marker table existed (has notes, no marker row)
    from alluvia.models import Note
    repo.upsert_session(_sess("old"))
    repo.upsert_notes([Note(id="note:x", user_id="local", session_id="claude-code:old",
                            span_ref="msg:0", kind="idea", text="x", created_at=None)])
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2)
    eng._distill_new("local")                              # union skips it: no LLM call
