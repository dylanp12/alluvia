from alluvia.engine.engine import Engine
from alluvia.engine.embed import FakeEmbedder
from alluvia.llm.client import FakeLLM
from alluvia.models import Message, RawSession, content_hash


def _sess(native, texts):
    msgs = [Message(role="user", text=t) for t in texts]
    return RawSession(id=f"claude-code:{native}", user_id="local", source="claude-code",
                      native_id=native, title=texts[0], started_at=None, ended_at=None,
                      messages=msgs, content_hash=content_hash(msgs))


def test_distill_session_is_incremental_and_forceable(repo):
    repo.upsert_session(_sess("s1", ["auth token service"]))
    llm = FakeLLM([{"notes": [{"kind": "decision", "text": "use a token service", "span": "msg:0"}]},
                   {"notes": [{"kind": "decision", "text": "use a token service", "span": "msg:0"},
                              {"kind": "problem", "text": "refresh race", "span": "msg:0"}]}])
    eng = Engine(repo, FakeEmbedder(dim=8), llm, min_cluster_size=2)
    notes = eng.distill_session("local", "claude-code:s1")
    assert [n.text for n in notes] == ["use a token service"]
    assert repo.distilled_session_ids("local") == {"claude-code:s1"}
    # already distilled → no LLM call, returns the stored notes
    assert [n.text for n in eng.distill_session("local", "claude-code:s1")] == ["use a token service"]
    # the live transcript grew → force re-distills and keeps the union
    assert {n.text for n in eng.distill_session("local", "claude-code:s1", force=True)} == {
        "use a token service", "refresh race"}
    eng.embed_new("local")
    assert repo.note_ids_with_embeddings("local") == {n.id for n in repo.get_notes("local")}


def test_distill_session_unknown_id_returns_empty(repo):
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2)
    assert eng.distill_session("local", "claude-code:missing") == []


def test_distill_session_treats_json_validate_failed_as_zero_note(repo):
    """Groq's JSON mode rejects some hijacked/huge transcripts outright. The
    batch path already counts that as a zero-knowledge session; the hook
    path must agree instead of raising into the user's session."""
    repo.upsert_session(_sess("s1", ["auth token service"]))

    class Rejects:
        def complete_json(self, *a, **k):
            raise RuntimeError("Error code: 400 - {'code': 'json_validate_failed'}")
    eng = Engine(repo, FakeEmbedder(dim=8), Rejects(), min_cluster_size=2)
    assert eng.distill_session("local", "claude-code:s1") == []
    assert repo.distilled_session_ids("local") == {"claude-code:s1"}   # marked, not retried forever


def test_partial_distill_is_not_marked_done(repo):
    """Partial notes are kept and embedded, but the session stays pending so a
    later pass fills in the windows the provider refused."""
    from alluvia.llm.governor import LLMUnavailable
    from tests.test_distiller import _long_session
    s = _long_session()
    repo.upsert_session(s)
    calls = {"n": 0}

    class Flaky:
        def complete_json(self, system, user):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"notes": [{"kind": "question", "text": "which cache layer", "span": "msg:0"}]}
            raise LLMUnavailable(0, "per-minute limit")
    eng = Engine(repo, FakeEmbedder(dim=8), Flaky(), min_cluster_size=2)
    notes = eng.distill_session("local", s.id)
    assert [n.text for n in notes] == ["which cache layer"]
    assert repo.distilled_session_ids("local") == set()          # still pending
    assert repo.distill_coverage("local")["pending"] == 1


def test_refresh_leaves_partial_sessions_pending_too(repo):
    """The batch path agrees with the hook path: a partial session is listed
    by pending_distill and marked partial, never done."""
    from alluvia.engine.engine import pending_distill
    from alluvia.llm.governor import LLMUnavailable
    from tests.test_distiller import _long_session
    s = _long_session()
    repo.upsert_session(s)
    calls = {"n": 0}

    class Flaky:
        def complete_json(self, system, user):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"notes": [{"kind": "question", "text": "which cache layer", "span": "msg:0"}]}
            raise LLMUnavailable(0, "per-minute limit")
    eng = Engine(repo, FakeEmbedder(dim=8), Flaky(), min_cluster_size=2)
    eng._distill_new("local")
    assert [n.text for n in repo.get_notes("local")] == ["which cache layer"]
    assert [x.id for x in pending_distill(repo, "local")] == [s.id]
    assert repo.partial_session_ids("local") == {s.id}


def test_full_redistill_replaces_the_sessions_notes_partial_unions(repo):
    """Re-ingesting a session with a better adapter changes what the LLM sees.
    A FULL re-distill must replace that session's notes (stale ones vanish,
    with their vectors); a PARTIAL one must only add, never drop."""
    from alluvia.llm.governor import LLMUnavailable
    from tests.test_distiller import _long_session
    s = _long_session()
    repo.upsert_session(s)
    calls = {"n": 0}
    script = [
        {"notes": [{"kind": "decision", "text": "old A", "span": "msg:0"},
                   {"kind": "decision", "text": "keep B", "span": "msg:0"}]},
        {"notes": []}, {"notes": []}, {"notes": []},                 # first full pass: 4 windows
        {"notes": [{"kind": "decision", "text": "keep B", "span": "msg:0"},
                   {"kind": "decision", "text": "new C", "span": "msg:0"}]},
        {"notes": []}, {"notes": []}, {"notes": []},                 # second full pass
        {"notes": [{"kind": "decision", "text": "new D", "span": "msg:0"}]},   # third pass: partial
    ]

    class Scripted:
        def complete_json(self, system, user):
            calls["n"] += 1
            if calls["n"] == 10:
                raise LLMUnavailable(0, "limit")
            return script[calls["n"] - 1]
    eng = Engine(repo, FakeEmbedder(dim=8), Scripted(), min_cluster_size=2)
    eng.distill_session("local", s.id, force=True); eng.embed_new("local")
    assert {n.text for n in repo.get_notes("local")} == {"old A", "keep B"}
    eng.distill_session("local", s.id, force=True); eng.embed_new("local")
    texts = {n.text for n in repo.get_notes("local")}
    assert texts == {"keep B", "new C"}, "stale note must be replaced on a full pass"
    assert repo.note_ids_with_embeddings("local") == {n.id for n in repo.get_notes("local")}
    eng.distill_session("local", s.id, force=True)                  # partial: D then limit
    assert {n.text for n in repo.get_notes("local")} == {"keep B", "new C", "new D"}
    assert repo.partial_session_ids("local") == {s.id}
