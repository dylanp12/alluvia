from alluvia.models import Message, RawSession, content_hash, session_id
from alluvia.distill.distiller import _render, MSG_CHAR_CAP, RENDER_CHAR_CAP
from alluvia.engine.engine import Engine
from alluvia.engine.embed import FakeEmbedder


def _sess(native, msgs):
    return RawSession(id=session_id("claude-code", native), user_id="local",
                      source="claude-code", native_id=native, title="t",
                      started_at=None, ended_at=None, messages=msgs,
                      content_hash=content_hash(msgs))


def test_render_caps_message_and_total_length():
    msgs = [Message(role="user", text="x" * (MSG_CHAR_CAP * 3)) for _ in range(40)]
    out = _render(_sess("big", msgs))
    assert len(out) <= RENDER_CHAR_CAP + 100          # cap + truncation marker
    assert "…[truncated]" in out
    assert "…[session truncated for length]" in out


class ExplodingLLM:
    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user):
        self.calls += 1
        raise RuntimeError("rate limited")


def test_distill_aborts_after_consecutive_failures(repo):
    for i in range(10):
        repo.upsert_session(_sess(f"s{i}", [Message(role="user", text=f"topic {i}")]))
    llm = ExplodingLLM()
    eng = Engine(repo, FakeEmbedder(dim=8), llm, min_cluster_size=2)
    eng.refresh("local")                               # must not raise
    assert llm.calls == Engine.MAX_CONSECUTIVE_FAILURES   # stopped early, resumable
    assert repo.session_ids_with_notes("local") == set()  # nothing half-written
