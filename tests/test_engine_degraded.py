"""Issue #1: when the LLM is rate-limited away, the map degrades gracefully —
heuristic statuses keep `unfinished` alive, fallbacks stay uncached (so the
next refresh completes the map), and the run records what happened (issue #2)."""
import hashlib
import json
from datetime import datetime, timedelta

from alluvia.engine.engine import Engine
from alluvia.llm.client import FakeLLM
from alluvia.llm.governor import LLMUnavailable
from alluvia.models import Message, RawSession, content_hash, session_id

BASE = datetime(2026, 1, 1)


class ScriptedEmbedder:
    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            base = [1.0, 0.0] if "auth" in t.lower() else [0.0, 1.0]
            eps = (int(hashlib.sha256(t.encode()).hexdigest(), 16) % 100) / 10000.0
            out.append(base + [eps, 0.0, 0.0, 0.0, 0.0, 0.0])
        return out


class ColdAfter:
    """Behaves like FakeLLM for the first N calls, then the provider is a wall."""

    def __init__(self, responses, cooldown_until=2_000_000.0):
        self._fake = FakeLLM(responses)
        self._n = len(responses)
        self.cooldown_until = cooldown_until

    def complete_json(self, system, user):
        if self._n <= 0:
            raise LLMUnavailable(self.cooldown_until)
        self._n -= 1
        return self._fake.complete_json(system, user)


def _sess(native, text, day):
    ts = BASE + timedelta(days=day)
    msgs = [Message(role="user", text=text, ts=ts)]
    return RawSession(id=session_id("claude-code", native), user_id="local",
                      source="claude-code", native_id=native, title=text,
                      started_at=ts, ended_at=ts, messages=msgs,
                      content_hash=content_hash(msgs))


def _corpus(repo, auth_days=(1, 40), deploy_days=(5, 6)):
    """Auth = recurring (>=2 sessions, 39d span); Deploy = not recurring."""
    texts = {}
    for i, d in enumerate(auth_days):
        t = f"auth token rotation strategy for the gateway service v{i}"
        repo.upsert_session(_sess(f"a{i}", t, d))
        texts[f"a{i}"] = t
    for i, d in enumerate(deploy_days):
        repo.upsert_session(_sess(f"d{i}", f"deploy pipeline config step {i}", d))
    distill = [{"notes": [{"kind": "idea", "text": f"auth token rotation strategy "
                           f"for the gateway service v{i}", "span": "msg:0"}]}
               for i in range(len(auth_days))]
    distill += [{"notes": [{"kind": "idea", "text": f"deploy pipeline config step {i}",
                            "span": "msg:0"}]} for i in range(len(deploy_days))]
    return distill


def test_status_heuristic_keeps_unfinished_alive_when_llm_cold(repo):
    distill = _corpus(repo)                       # distills fine, then wall
    eng = Engine(repo, ScriptedEmbedder(), ColdAfter(distill), min_cluster_size=2)
    eng.refresh("local", now=BASE + timedelta(days=45))   # auth last touch 5d ago

    themes = {t.label: t for t in repo.list_themes("local")}
    auth = next(t for t in themes.values() if "auth" in t.label.lower())
    deploy = next(t for t in themes.values() if "deploy" in t.label.lower())
    assert auth.status == "open"                  # recurring + recent -> heuristic open
    assert deploy.status == "unknown"             # not recurring: by design, no guess
    # heuristic is a stopgap, never cached — the LLM upgrades it next refresh
    assert not repo.conn.execute("SELECT * FROM theme_status_cache").fetchall()
    # the headline lens is NOT dark (the whole point of #1)
    assert [t.label for t in eng.unfinished("local")] == [auth.label]


def test_status_heuristic_stale_recurring_is_dormant(repo):
    distill = _corpus(repo)
    eng = Engine(repo, ScriptedEmbedder(), ColdAfter(distill), min_cluster_size=2)
    eng.refresh("local", now=BASE + timedelta(days=140))  # auth last touch 100d ago
    auth = next(t for t in repo.list_themes("local")
                if "auth" in t.label.lower())
    assert auth.status == "dormant"
    assert eng.unfinished("local", include_dormant=True)


def test_label_fallback_cuts_at_word_boundary_and_stays_uncached(repo):
    distill = _corpus(repo)
    eng = Engine(repo, ScriptedEmbedder(), ColdAfter(distill), min_cluster_size=2)
    eng.refresh("local", now=BASE + timedelta(days=45))
    labels = [t.label for t in repo.list_themes("local")]
    assert "auth token rotation strategy for the" in labels   # not "...for the ga"
    assert all(not l.endswith(" ") for l in labels)
    assert not repo.conn.execute("SELECT * FROM theme_label_cache").fetchall()


def test_refresh_records_stats_and_degraded_flag(repo):
    distill = _corpus(repo)
    eng = Engine(repo, ScriptedEmbedder(), ColdAfter(distill), min_cluster_size=2)
    stats = eng.refresh("local", now=BASE + timedelta(days=45))
    assert stats["degraded"] is True
    assert stats["themes"]["built"] == 2
    assert stats["themes"]["label_fallback"] == 2 and stats["themes"]["label_llm"] == 0
    assert stats["themes"]["status_heuristic"] == 1
    assert stats["retry_at"] is not None
    persisted = json.loads(repo.get_meta("last_refresh"))
    assert persisted["degraded"] is True          # surfaces can read it later


def test_refresh_healthy_run_is_not_degraded(repo):
    distill = _corpus(repo)
    llm = FakeLLM(distill + [
        {"label": "Auth", "summary": "auth"},
        {"label": "Deploy", "summary": "deploy"},
        {"status": "open"},
    ])
    eng = Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)
    stats = eng.refresh("local", now=BASE + timedelta(days=45))
    assert stats["degraded"] is False
    assert stats["themes"]["label_llm"] == 2
    assert stats["themes"]["status_ok"] == 1
    assert json.loads(repo.get_meta("last_refresh"))["degraded"] is False


def test_distill_stops_immediately_when_provider_cold(repo):
    for i in range(4):
        repo.upsert_session(_sess(f"s{i}", f"auth topic {i}", i + 1))
    cold = ColdAfter([])                          # wall from the very first call
    eng = Engine(repo, ScriptedEmbedder(), cold, min_cluster_size=2)
    stats = eng.refresh("local", now=BASE + timedelta(days=45))
    # nothing marked distilled -> fully resumable next run, and no 5-strike churn
    assert repo.distilled_session_ids("local") == set()
    assert stats["distill"]["ok"] == 0 and stats["distill"]["cold"] is True
    assert stats["degraded"] is True
