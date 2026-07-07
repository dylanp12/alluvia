import hashlib
from alluvia.models import Message, RawSession, content_hash, session_id
from alluvia.llm.client import FakeLLM
from alluvia.engine.engine import Engine


class ScriptedEmbedder:
    """Deterministic, semantically-controlled vectors so clusters form predictably.
    (FakeEmbedder's hash vectors are deterministic but NOT semantic — unusable here.)"""
    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            base = [1.0, 0.0] if "auth" in t.lower() else [0.0, 1.0]
            eps = (int(hashlib.sha256(t.encode()).hexdigest(), 16) % 100) / 10000.0
            out.append(base + [eps, 0.0, 0.0, 0.0, 0.0, 0.0])
        return out


def _sess(native, texts):
    msgs = [Message(role="user", text=t) for t in texts]
    return RawSession(id=session_id("claude-code", native), user_id="local",
                      source="claude-code", native_id=native, title=texts[0],
                      started_at=None, ended_at=None, messages=msgs,
                      content_hash=content_hash(msgs))


def test_refresh_builds_themes(repo):
    repo.upsert_session(_sess("s1", ["auth token service"]))
    repo.upsert_session(_sess("s2", ["auth middleware design"]))
    repo.upsert_session(_sess("s3", ["deploy to fly.io"]))
    repo.upsert_session(_sess("s4", ["deploy pipeline config"]))
    # 4 distill calls (one per session), then 2 label calls (one per cluster).
    llm = FakeLLM([
        {"notes": [{"kind": "idea", "text": "auth token service", "span": "msg:0"}]},
        {"notes": [{"kind": "idea", "text": "auth middleware design", "span": "msg:0"}]},
        {"notes": [{"kind": "idea", "text": "deploy to fly.io", "span": "msg:0"}]},
        {"notes": [{"kind": "idea", "text": "deploy pipeline config", "span": "msg:0"}]},
        {"label": "Auth", "summary": "Auth architecture."},
        {"label": "Deploy", "summary": "Deployment."},
    ])
    eng = Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)
    eng.refresh("local")
    themes = repo.list_themes("local")
    assert len(themes) == 2                       # auth cluster + deploy cluster
    assert all(t.session_count == 2 and t.source_count == 1 for t in themes)

    # idempotent: re-refresh does not re-distill (needs only label responses, not notes).
    eng2 = Engine(repo, ScriptedEmbedder(), FakeLLM([
        {"label": "Auth", "summary": "Auth architecture."},
        {"label": "Deploy", "summary": "Deployment."},
    ]), min_cluster_size=2)
    eng2.refresh("local")
    assert repo.session_ids_with_notes("local") == {
        "claude-code:s1", "claude-code:s2", "claude-code:s3", "claude-code:s4"}
