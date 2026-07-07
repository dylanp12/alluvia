from alluvia.config import PIPELINE_VERSION
from alluvia.models import Message, RawSession, content_hash, session_id
from alluvia.llm.client import FakeLLM
from alluvia.engine.engine import Engine
from alluvia.engine.embed import FakeEmbedder


def _sess(native):
    msgs = [Message(role="user", text=f"topic {native}")]
    return RawSession(id=session_id("claude-code", native), user_id="local",
                      source="claude-code", native_id=native, title="t",
                      started_at=None, ended_at=None, messages=msgs,
                      content_hash=content_hash(msgs))


def test_pipeline_version_is_2():
    assert PIPELINE_VERSION == 2


def test_v1_marked_session_redistills_and_marker_upgrades(repo):
    repo.upsert_session(_sess("old"))
    # simulate a v1-era checkpoint row
    repo.conn.execute(
        "INSERT INTO distilled_sessions(user_id,session_id,pipeline_version) "
        "VALUES ('local','claude-code:old',1)")
    repo.conn.commit()
    assert repo.distilled_session_ids("local") == set()          # v1 < current -> not done
    eng = Engine(repo, FakeEmbedder(dim=8),
                 FakeLLM([{"notes": []}]), min_cluster_size=2)
    eng.refresh("local")                                          # re-distills (1 LLM call)
    assert repo.distilled_session_ids("local") == {"claude-code:old"}  # marker now v2


def test_current_version_marker_not_redistilled(repo):
    repo.upsert_session(_sess("new"))
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": []}]), min_cluster_size=2)
    eng.refresh("local")
    # empty FakeLLM: would raise if the v2-marked session were re-distilled
    Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2).refresh("local")
