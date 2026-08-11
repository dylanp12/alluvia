from datetime import datetime, timezone

from alluvia.engine.engine import Engine
from alluvia.llm.client import FakeLLM
from alluvia.models import Message, RawSession, content_hash


class _NullEmbedder:
    def embed(self, texts):
        return [[0.0] * 8 for _ in texts]


class _ModelAwareLLM(FakeLLM):
    """FakeLLM + the Governor's observability attribute."""
    def __init__(self, responses, model="m-fake"):
        super().__init__(responses)
        self.last_model = model


def _session(sid="s1"):
    msgs = [Message(role="user", text="the upload API trusts the client artist id")]
    return RawSession(id=f"claude-code:{sid}", user_id="local", source="claude-code",
                      native_id=sid, title="t",
                      started_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
                      ended_at=None, messages=msgs, content_hash=content_hash(msgs))


def _notes_payload():
    return {"notes": [{"kind": "problem",
                        "text": "upload API trusts client artist id",
                        "span": "msg:0"}]}


def test_distill_records_run_and_stamps_notes(repo):
    repo.upsert_session(_session())
    eng = Engine(repo, _NullEmbedder(), _ModelAwareLLM([_notes_payload()]))
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    eng._distill_new("local", {}, now=now)
    runs = repo.list_extraction_runs("local")
    assert len(runs) == 1
    run = runs[0]
    assert run.stage == "distill" and run.model == "m-fake"
    assert run.session_id == "claude-code:s1"
    assert run.prompt_hash and run.created_at == now.isoformat()
    notes = repo.get_notes("local")
    assert notes and all(n.run_id == run.id for n in notes)


def test_plain_llm_without_last_model_records_none(repo):
    repo.upsert_session(_session("s2"))
    eng = Engine(repo, _NullEmbedder(), FakeLLM([_notes_payload()]))
    eng._distill_new("local", {}, now=datetime(2026, 7, 17, tzinfo=timezone.utc))
    assert repo.list_extraction_runs("local")[0].model is None


def test_refresh_still_works_end_to_end(repo):
    # two sessions so downstream stages see a small-but-plural corpus; the
    # FakeLLM runs dry after distill, which the label/status fallbacks absorb
    repo.upsert_session(_session("s3"))
    repo.upsert_session(_session("s4"))
    eng = Engine(repo, _NullEmbedder(),
                 _ModelAwareLLM([_notes_payload(), {"notes": [
                     {"kind": "decision", "text": "verify ownership server-side",
                      "span": "msg:0"}]}]), min_cluster_size=2)
    stats = eng.refresh("local", now=datetime(2026, 7, 17, tzinfo=timezone.utc))
    assert stats["distill"]["ok"] == 2
    assert len(repo.list_extraction_runs("local")) == 2
