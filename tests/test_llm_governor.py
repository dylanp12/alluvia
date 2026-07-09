"""Governor behavior (issue #3): outcome-driven backoff/breaker/chain.

Everything runs on a fake clock + scripted adapters — the governor must be
correct with zero provider hints, faster with them."""
import pytest

from alluvia.llm.governor import (
    Governor, LLMUnavailable, MemoryHealthStore,
    classify_exception, retry_after_seconds,
    RATE_LIMITED, SERVER_ERROR, CLIENT_ERROR, UNKNOWN,
)


class _Resp:
    def __init__(self, headers=None, status_code=None):
        self.headers = headers or {}
        if status_code is not None:
            self.status_code = status_code


class RateLimited(Exception):
    status_code = 429

    def __init__(self, retry_after: str | None = None):
        super().__init__("rate limited")
        self.response = _Resp({"retry-after": retry_after} if retry_after else {})


class ServerDown(Exception):
    status_code = 503


class BadRequest(Exception):
    status_code = 400


class ScriptedAdapter:
    """Yields scripted results; raises entries that are exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def complete_json(self, system, user):
        self.calls += 1
        item = self.script.pop(0) if self.script else {"ok": True}
        if isinstance(item, Exception):
            raise item
        return item


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t
        self.sleeps = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.t += s


def _gov(candidates, clock, store=None, patience=600):
    return Governor("groq", candidates, store=store or MemoryHealthStore(),
                    clock=clock, sleeper=clock.sleep, patience=patience)


# --- outcome classification ------------------------------------------------

def test_classify_by_status_code_attr_and_response():
    assert classify_exception(RateLimited()) == RATE_LIMITED
    assert classify_exception(ServerDown()) == SERVER_ERROR
    assert classify_exception(BadRequest()) == CLIENT_ERROR

    class ViaResponse(Exception):
        def __init__(self, code):
            self.response = _Resp(status_code=code)

    assert classify_exception(ViaResponse(429)) == RATE_LIMITED
    assert classify_exception(ViaResponse(500)) == SERVER_ERROR
    assert classify_exception(ViaResponse(404)) == CLIENT_ERROR
    assert classify_exception(ValueError("no status")) == UNKNOWN


def test_retry_after_numeric_and_garbage():
    assert retry_after_seconds(RateLimited("30")) == 30.0
    assert retry_after_seconds(RateLimited("bogus")) is None
    assert retry_after_seconds(RateLimited()) is None
    assert retry_after_seconds(ValueError("no response")) is None


def test_retry_after_http_date():
    from datetime import datetime, timezone, timedelta
    from email.utils import format_datetime
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=100))
    v = retry_after_seconds(RateLimited(future))
    assert v is not None and 50 < v < 150


# --- single-candidate governor ----------------------------------------------

def test_success_passes_through_untouched():
    clock = FakeClock()
    a = ScriptedAdapter([{"answer": 1}])
    gov = _gov([("m1", a)], clock)
    assert gov.complete_json("s", "u") == {"answer": 1}
    assert a.calls == 1 and clock.sleeps == []


def test_rate_limit_honors_retry_after_hint_then_succeeds():
    clock = FakeClock()
    a = ScriptedAdapter([RateLimited("3"), {"ok": True}])
    gov = _gov([("m1", a)], clock)
    assert gov.complete_json("s", "u") == {"ok": True}
    assert a.calls == 2
    assert clock.sleeps[0] == 3.0                      # provider hint honored


def test_ladder_climbs_when_no_hint():
    clock = FakeClock()
    a = ScriptedAdapter([RateLimited(), RateLimited(), RateLimited(), {"ok": True}])
    gov = _gov([("m1", a)], clock, patience=600)
    assert gov.complete_json("s", "u") == {"ok": True}
    # 1st 429 -> rung0 (5s); still failing -> climb to 30s, then 120s
    assert clock.sleeps[:3] == [5.0, 30.0, 120.0]


def test_success_resets_ladder_and_breaker():
    clock = FakeClock()
    store = MemoryHealthStore()
    a = ScriptedAdapter([RateLimited(), RateLimited(), {"ok": True}])
    gov = _gov([("m1", a)], clock, store=store)
    gov.complete_json("s", "u")
    st = store.load("groq", "m1")
    assert st["rung"] == 0 and st["consecutive"] == 0
    assert st["cooldown_until"] == 0.0
    assert st["last_success"] == clock.t


def test_breaker_opens_when_next_wait_exceeds_patience():
    clock = FakeClock()
    store = MemoryHealthStore()
    a = ScriptedAdapter([RateLimited(), RateLimited(), RateLimited()])
    gov = _gov([("m1", a)], clock, store=store, patience=60)
    with pytest.raises(LLMUnavailable) as ei:
        gov.complete_json("s", "u")
    # slept 5 + 30, then the 120s rung exceeded remaining patience -> OPEN
    assert clock.sleeps == [5.0, 30.0]
    assert a.calls == 3
    st = store.load("groq", "m1")
    assert st["cooldown_until"] == pytest.approx(clock.t + 120.0)
    assert ei.value.cooldown_until == pytest.approx(clock.t + 120.0)


def test_open_breaker_skips_without_calling():
    clock = FakeClock()
    store = MemoryHealthStore()
    store.save("groq", "m1", {"cooldown_until": clock.t + 500})
    a = ScriptedAdapter([{"ok": True}])
    gov = _gov([("m1", a)], clock, store=store)
    with pytest.raises(LLMUnavailable):
        gov.complete_json("s", "u")
    assert a.calls == 0 and clock.sleeps == []


def test_half_open_probe_after_cooldown_closes_on_success():
    clock = FakeClock()
    store = MemoryHealthStore()
    store.save("groq", "m1", {"cooldown_until": clock.t - 1, "rung": 3,
                              "consecutive": 4})
    a = ScriptedAdapter([{"ok": True}])
    gov = _gov([("m1", a)], clock, store=store)
    assert gov.complete_json("s", "u") == {"ok": True}
    st = store.load("groq", "m1")
    assert st["rung"] == 0 and st["consecutive"] == 0 and st["cooldown_until"] == 0.0


def test_half_open_failure_climbs_ladder_across_calls():
    clock = FakeClock()
    store = MemoryHealthStore()
    # already failed through the short rungs in a previous process
    store.save("groq", "m1", {"cooldown_until": clock.t - 1, "rung": 3,
                              "consecutive": 3})
    a = ScriptedAdapter([RateLimited()])
    gov = _gov([("m1", a)], clock, store=store, patience=60)
    with pytest.raises(LLMUnavailable):
        gov.complete_json("s", "u")
    st = store.load("groq", "m1")
    assert st["rung"] == 4                              # climbed
    assert st["cooldown_until"] == pytest.approx(clock.t + 3600.0)


# --- chain fallthrough --------------------------------------------------------

def test_chain_falls_through_to_next_model_when_first_is_cold():
    clock = FakeClock()
    store = MemoryHealthStore()
    store.save("groq", "m1", {"cooldown_until": clock.t + 500})
    a1, a2 = ScriptedAdapter([{"ok": 1}]), ScriptedAdapter([{"ok": 2}])
    gov = _gov([("m1", a1), ("m2", a2)], clock, store=store)
    assert gov.complete_json("s", "u") == {"ok": 2}
    assert a1.calls == 0 and a2.calls == 1


def test_all_candidates_cold_raises_with_soonest_cooldown():
    clock = FakeClock()
    store = MemoryHealthStore()
    store.save("groq", "m1", {"cooldown_until": clock.t + 500})
    a1 = ScriptedAdapter([])
    a2 = ScriptedAdapter([RateLimited("999")])
    gov = _gov([("m1", a1), ("m2", a2)], clock, patience=10, store=store)
    with pytest.raises(LLMUnavailable) as ei:
        gov.complete_json("s", "u")
    # m1 cools until +500; m2 got a 999s hint > patience -> opened at +999
    assert ei.value.cooldown_until == pytest.approx(clock.t + 500)


def test_client_error_fails_loud_no_retry():
    clock = FakeClock()
    a = ScriptedAdapter([BadRequest()])
    gov = _gov([("m1", a)], clock)
    with pytest.raises(BadRequest):
        gov.complete_json("s", "u")
    assert a.calls == 1 and clock.sleeps == []


def test_client_error_advances_chain():
    clock = FakeClock()
    a1, a2 = ScriptedAdapter([BadRequest()]), ScriptedAdapter([{"ok": 2}])
    gov = _gov([("m1", a1), ("m2", a2)], clock)
    assert gov.complete_json("s", "u") == {"ok": 2}
    assert a1.calls == 1 and a2.calls == 1


def test_server_errors_retry_briefly_then_advance():
    clock = FakeClock()
    a1 = ScriptedAdapter([ServerDown(), ServerDown(), ServerDown()])
    a2 = ScriptedAdapter([{"ok": 2}])
    gov = _gov([("m1", a1), ("m2", a2)], clock)
    assert gov.complete_json("s", "u") == {"ok": 2}
    assert a1.calls == 3                                # initial + 2 brief retries


# --- AIMD pacing ---------------------------------------------------------------

def test_rate_limit_seeds_pacing_and_success_raises_it():
    clock = FakeClock()
    store = MemoryHealthStore()
    a = ScriptedAdapter([RateLimited(), {"ok": 1}, {"ok": 2}])
    gov = _gov([("m1", a)], clock, store=store)
    gov.complete_json("s", "u")
    r1 = store.load("groq", "m1")["est_rate"]
    assert r1 is not None and r1 > 0
    gov.complete_json("s", "u")                         # immediate second call
    r2 = store.load("groq", "m1")["est_rate"]
    assert r2 > r1                                      # additive increase
    # the second call had to respect the pace gap (some sleep happened)
    assert any(s > 0 for s in clock.sleeps[1:])


# --- persistence -----------------------------------------------------------------

def test_breaker_state_survives_new_governor_instance():
    clock = FakeClock()
    store = MemoryHealthStore()
    a = ScriptedAdapter([RateLimited("500")])
    gov1 = _gov([("m1", a)], clock, store=store, patience=10)
    with pytest.raises(LLMUnavailable):
        gov1.complete_json("s", "u")
    fresh = ScriptedAdapter([{"ok": True}])
    gov2 = _gov([("m1", fresh)], clock, store=store)
    with pytest.raises(LLMUnavailable):
        gov2.complete_json("s", "u")
    assert fresh.calls == 0                             # skipped, no network


def test_governor_exposes_head_model_and_health():
    clock = FakeClock()
    gov = _gov([("m1", ScriptedAdapter([])), ("m2", ScriptedAdapter([]))], clock)
    assert gov.model == "m1"
    assert [h["model"] for h in gov.health()] == ["m1", "m2"]
