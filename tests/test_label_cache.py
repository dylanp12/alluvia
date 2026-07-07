import hashlib
from datetime import datetime, timedelta
from alluvia.models import Message, RawSession, content_hash, session_id
from alluvia.llm.client import FakeLLM
from alluvia.engine.engine import Engine


class ScriptedEmbedder:
    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            base = [1.0, 0.0] if "auth" in t.lower() else [0.0, 1.0]
            eps = (int(hashlib.sha256(t.encode()).hexdigest(), 16) % 100) / 10000.0
            out.append(base + [eps, 0.0, 0.0, 0.0, 0.0, 0.0])
        return out


BASE = datetime(2026, 1, 1)


def _sess(native, text, day):
    ts = BASE + timedelta(days=day)
    msgs = [Message(role="user", text=text, ts=ts)]
    return RawSession(id=session_id("claude-code", native), user_id="local",
                      source="claude-code", native_id=native, title=text,
                      started_at=ts, ended_at=ts, messages=msgs,
                      content_hash=content_hash(msgs))


def _seed_two_clusters(repo):
    repo.upsert_session(_sess("s1", "auth tokens", 1))
    repo.upsert_session(_sess("s2", "auth middleware", 2))
    repo.upsert_session(_sess("s3", "deploy fly", 1))
    repo.upsert_session(_sess("s4", "deploy pipeline", 2))


_DISTILLS = [
    {"notes": [{"kind": "idea", "text": "auth tokens", "span": "msg:0"}]},
    {"notes": [{"kind": "idea", "text": "auth middleware", "span": "msg:0"}]},
    {"notes": [{"kind": "idea", "text": "deploy fly", "span": "msg:0"}]},
    {"notes": [{"kind": "idea", "text": "deploy pipeline", "span": "msg:0"}]},
]


def test_labels_cached_and_not_rebilled(repo):
    _seed_two_clusters(repo)
    llm = FakeLLM(_DISTILLS + [
        {"label": "Auth", "summary": "auth stuff"},
        {"label": "Deploy", "summary": "deploy stuff"},
    ])
    eng = Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)
    eng.refresh("local", now=BASE + timedelta(days=3))
    labels = {t.label for t in repo.list_themes("local")}
    assert labels == {"Auth", "Deploy"}
    # second refresh: empty FakeLLM — cached labels must be reused, no LLM call
    eng2 = Engine(repo, ScriptedEmbedder(), FakeLLM([]), min_cluster_size=2)
    eng2.refresh("local", now=BASE + timedelta(days=3))
    assert {t.label for t in repo.list_themes("local")} == {"Auth", "Deploy"}
    assert {t.summary for t in repo.list_themes("local")} == {"auth stuff", "deploy stuff"}


class ExplodingLLM:
    def complete_json(self, system, user):
        raise RuntimeError("429")


def test_fallback_labels_not_cached_so_they_retry(repo):
    _seed_two_clusters(repo)
    ok = Engine(repo, ScriptedEmbedder(), FakeLLM(list(_DISTILLS)), min_cluster_size=2)
    ok._distill_new("local")
    ok._embed_new("local")
    # labeling fails -> fallback labels, NOT cached
    eng = Engine(repo, ScriptedEmbedder(), ExplodingLLM(), min_cluster_size=2)
    eng._rebuild_themes("local", BASE + timedelta(days=3))
    assert all(t.summary == "" for t in repo.list_themes("local"))
    # next rebuild with a working LLM heals the labels (cache miss -> real calls)
    eng2 = Engine(repo, ScriptedEmbedder(), FakeLLM([
        {"label": "Auth", "summary": "healed"},
        {"label": "Deploy", "summary": "healed"},
    ]), min_cluster_size=2)
    eng2._rebuild_themes("local", BASE + timedelta(days=3))
    assert all(t.summary == "healed" for t in repo.list_themes("local"))
