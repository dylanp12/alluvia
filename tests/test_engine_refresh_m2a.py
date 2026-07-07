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


def test_refresh_wires_link_and_track(repo):
    # 2 auth + 2 deploy -> two themes; Auth recurring (39d span), Deploy not (1d span).
    repo.upsert_session(_sess("s1", "auth tokens", 1))
    repo.upsert_session(_sess("s2", "auth middleware", 40))
    repo.upsert_session(_sess("s3", "deploy fly", 5))
    repo.upsert_session(_sess("s4", "deploy pipeline", 6))
    llm = FakeLLM([
        {"notes": [{"kind": "idea", "text": "auth tokens", "span": "msg:0"}]},
        {"notes": [{"kind": "idea", "text": "auth middleware", "span": "msg:0"}]},
        {"notes": [{"kind": "idea", "text": "deploy fly", "span": "msg:0"}]},
        {"notes": [{"kind": "idea", "text": "deploy pipeline", "span": "msg:0"}]},
        {"label": "Auth", "summary": "auth"},               # 2 label calls (order not asserted)
        {"label": "Deploy", "summary": "deploy"},
        {"status": "open"},                                 # only the recurring theme is classified
    ])
    eng = Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)
    eng.refresh("local", now=BASE + timedelta(days=45))
    themes = repo.list_themes("local")
    # track wired: exactly one recurring theme classified, one non-recurring stays 'unknown'
    # (assert by recurrence, not label — HDBSCAN's cluster-label order isn't guaranteed).
    classified = [t for t in themes if t.status != "unknown"]
    assert len(classified) == 1 and classified[0].status in ("open", "dormant", "resolved")
    assert len([t for t in themes if t.status == "unknown"]) == 1
    # link stage wired: links table is queryable and every edge is cross-theme (the invariant).
    assert all(l.from_theme_id != l.to_theme_id for l in repo.list_links("local"))
