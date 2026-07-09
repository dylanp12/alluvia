"""Persisted governor state (issue #3 §7): abstract per-(provider,model) rows
in SQLite so a fresh CLI process respects cooldowns instead of re-hammering."""
from alluvia.store.repo import LLMHealthStore


def test_meta_roundtrip(repo):
    assert repo.get_meta("last_refresh") is None
    repo.set_meta("last_refresh", '{"themes": 3}')
    assert repo.get_meta("last_refresh") == '{"themes": 3}'
    repo.set_meta("last_refresh", '{"themes": 4}')          # upsert
    assert repo.get_meta("last_refresh") == '{"themes": 4}'


def test_health_store_load_save_roundtrip(repo):
    store = LLMHealthStore(repo)
    assert store.load("groq", "m1") is None
    store.save("groq", "m1", {"cooldown_until": 123.5, "rung": 2,
                              "consecutive": 3, "est_rate": 0.5,
                              "last_success": 99.0, "last_call": 100.0})
    st = store.load("groq", "m1")
    assert st["cooldown_until"] == 123.5 and st["rung"] == 2
    assert st["est_rate"] == 0.5
    store.save("groq", "m1", {"cooldown_until": 0.0, "rung": 0,
                              "consecutive": 0, "est_rate": 0.55,
                              "last_success": 101.0, "last_call": 101.0})
    assert store.load("groq", "m1")["rung"] == 0            # upsert, not insert


def test_health_store_none_rate_and_listing(repo):
    store = LLMHealthStore(repo)
    store.save("groq", "m1", {"cooldown_until": 5.0})       # partial row is fine
    store.save("groq", "m2", {"cooldown_until": 0.0, "est_rate": None})
    st = store.load("groq", "m1")
    assert st["cooldown_until"] == 5.0
    assert store.load("groq", "m2")["est_rate"] is None
    models = {r["model"] for r in repo.llm_health_all()}
    assert models == {"m1", "m2"}


def test_governor_persists_through_sqlite_store(repo):
    """End-to-end: breaker opened via one governor is respected by a second."""
    import pytest
    from alluvia.llm.governor import Governor, LLMUnavailable
    from tests.test_llm_governor import FakeClock, ScriptedAdapter, RateLimited

    clock = FakeClock()
    store = LLMHealthStore(repo)
    gov1 = Governor("groq", [("m1", ScriptedAdapter([RateLimited("500")]))],
                    store=store, clock=clock, sleeper=clock.sleep, patience=10)
    with pytest.raises(LLMUnavailable):
        gov1.complete_json("s", "u")
    fresh = ScriptedAdapter([{"ok": True}])
    gov2 = Governor("groq", [("m1", fresh)], store=store,
                    clock=clock, sleeper=clock.sleep, patience=10)
    with pytest.raises(LLMUnavailable):
        gov2.complete_json("s", "u")
    assert fresh.calls == 0
