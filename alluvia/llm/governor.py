"""Provider-agnostic resilience for LLM calls.

The governor never reads provider payloads. Every provider is reduced to one
of five abstract outcomes per call, and all behavior — escalating cooldown
ladder, per-model circuit breaker, chain fallthrough, AIMD pacing — is derived
from the sequence of outcomes over time. HTTP status codes and the standard
`Retry-After` header are the only universal signals consulted, and both are
optional fast-paths, never dependencies. A new provider therefore needs only
a working `complete_json`.
"""
from __future__ import annotations

import logging
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

log = logging.getLogger(__name__)

SUCCESS = "success"
RATE_LIMITED = "rate_limited"
SERVER_ERROR = "server_error"
CLIENT_ERROR = "client_error"
UNKNOWN = "unknown"

# Cooldown ladder: which rung a model sits on is learned purely from repeated
# failure — a per-minute limit clears on the low rungs, a daily budget climbs
# to the multi-hour rungs on its own. Past the last rung we pin at 24h.
RUNGS = (5.0, 30.0, 120.0, 900.0, 3600.0, 21600.0)
PIN = 86400.0

DEFAULT_PATIENCE = 90.0      # max seconds one call may spend sleeping on limits
_SERVER_RETRIES = 2          # brief in-call retries for 5xx/unknown blips
_SERVER_WAITS = (1.0, 3.0)
_RATE_FLOOR = 1.0 / 120.0    # AIMD never paces slower than one call per 2 min
_RATE_SEED = 0.25            # first 429 seeds pacing at 4s between calls
_RATE_STEP = 0.05
_RATE_CEIL = 2.0
_PACE_CAP = 30.0

_FRESH = {"cooldown_until": 0.0, "rung": 0, "consecutive": 0,
          "est_rate": None, "last_success": 0.0, "last_call": 0.0,
          "calls": 0, "sent_bytes": 0, "recv_bytes": 0}


class LLMUnavailable(Exception):
    """Every candidate model is cooling down. Not an error in the user's data —
    callers degrade gracefully and retry after `cooldown_until`."""

    def __init__(self, cooldown_until: float, detail: str = ""):
        self.cooldown_until = cooldown_until
        when = datetime.fromtimestamp(cooldown_until, tz=timezone.utc)
        super().__init__(
            f"llm provider is rate-limited; retry after {when:%Y-%m-%d %H:%M} UTC"
            + (f" ({detail})" if detail else ""))


def _status_of(exc: Exception) -> int | None:
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(code) if code is not None else None
    except (TypeError, ValueError):
        return None


def classify_exception(exc: Exception) -> str:
    """Default classifier: HTTP status is the one universal signal."""
    code = _status_of(exc)
    if code == 429:
        return RATE_LIMITED
    if code is not None and code >= 500:
        return SERVER_ERROR
    if code is not None and 400 <= code < 500:
        return CLIENT_ERROR
    return UNKNOWN


def retry_after_seconds(exc: Exception) -> float | None:
    """Standard `Retry-After` header (RFC 9110) only — seconds or HTTP-date.
    Defensive: any absence or parse failure returns None and the ladder rules."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        pass
    try:
        dt = parsedate_to_datetime(str(raw))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


class MemoryHealthStore:
    """Process-lifetime state. The SQLite-backed store lives in the repo layer."""

    def __init__(self):
        self._rows: dict[tuple[str, str], dict] = {}

    def load(self, provider: str, model: str) -> dict | None:
        row = self._rows.get((provider, model))
        return dict(row) if row else None

    def save(self, provider: str, model: str, state: dict) -> None:
        self._rows[(provider, model)] = dict(state)


class Governor:
    """Wraps an ordered chain of (model, adapter) candidates behind the same
    `complete_json` interface. State is keyed per (provider, model) so a wall
    hit by one model leaves the others usable."""

    def __init__(self, provider: str, candidates: list[tuple[str, object]],
                 store=None, clock=time.time, sleeper=time.sleep,
                 patience: float | None = None, rungs=RUNGS, on_wait=None):
        if not candidates:
            raise ValueError("governor needs at least one (model, adapter)")
        self.provider = provider
        self.candidates = list(candidates)
        self.store = store if store is not None else MemoryHealthStore()
        self.clock = clock
        self.sleeper = sleeper
        self.patience = DEFAULT_PATIENCE if patience is None else float(patience)
        self.rungs = tuple(rungs)
        self.on_wait = on_wait       # callable(model, seconds): a deliberate
        #                              wait must never look like a hang

    _NOTIFY_WAIT = 2.0               # don't narrate sub-2s sleeps

    def _wait(self, model: str, seconds: float) -> None:
        if self.on_wait and seconds >= self._NOTIFY_WAIT:
            self.on_wait(model, seconds)
        self.sleeper(seconds)

    @property
    def model(self) -> str:
        return self.candidates[0][0]

    def _load(self, model: str) -> dict:
        return {**_FRESH, **(self.store.load(self.provider, model) or {})}

    def _save(self, model: str, st: dict) -> None:
        self.store.save(self.provider, model, st)

    def _rung_wait(self, rung: int) -> float:
        return self.rungs[rung] if rung < len(self.rungs) else PIN

    def health(self) -> list[dict]:
        return [{"model": m, "provider": self.provider, **self._load(m)}
                for m, _ in self.candidates]

    def _pace(self, model: str, st: dict) -> None:
        if not st["est_rate"] or not st["last_call"]:
            return
        due = st["last_call"] + 1.0 / st["est_rate"]
        wait = due - self.clock()
        if wait > 0:
            self._wait(model, min(wait, _PACE_CAP))

    def complete_json(self, system: str, user: str):
        budget = self.patience
        soonest: float | None = None
        last_exc: Exception | None = None

        for model, adapter in self.candidates:
            st = self._load(model)
            if st["cooldown_until"] > self.clock():        # breaker OPEN: skip, no call
                soonest = min(soonest or st["cooldown_until"], st["cooldown_until"])
                continue
            server_tries = 0
            while True:                                    # CLOSED (or half-open probe)
                self._pace(model, st)
                st["last_call"] = self.clock()
                try:
                    result = adapter.complete_json(system, user)
                except Exception as exc:
                    outcome = classify_exception(exc)
                    if outcome == CLIENT_ERROR:
                        last_exc = exc                     # terminal for this model
                        self._save(model, st)
                        break
                    if outcome in (SERVER_ERROR, UNKNOWN):
                        if server_tries < _SERVER_RETRIES:
                            wait = min(_SERVER_WAITS[server_tries], budget)
                            server_tries += 1
                            budget -= wait
                            self._wait(model, wait)
                            continue
                        last_exc = exc
                        self._save(model, st)
                        break
                    # RATE_LIMITED
                    st["consecutive"] += 1
                    if st["consecutive"] >= 2:             # kept failing -> climb
                        st["rung"] = min(st["rung"] + 1, len(self.rungs))
                    st["est_rate"] = (max(st["est_rate"] / 2.0, _RATE_FLOOR)
                                      if st["est_rate"] else _RATE_SEED)
                    hint = retry_after_seconds(exc)
                    wait = min(hint if hint is not None else
                               self._rung_wait(st["rung"]), PIN)
                    if wait <= budget:
                        budget -= wait
                        self._save(model, st)
                        self._wait(model, wait)
                        continue
                    st["cooldown_until"] = self.clock() + wait   # can't afford: OPEN
                    self._save(model, st)
                    log.info("llm %s/%s cooling for %.0fs (rate limited)",
                             self.provider, model, wait)
                    soonest = min(soonest or st["cooldown_until"],
                                  st["cooldown_until"])
                    break
                else:
                    st.update(rung=0, consecutive=0, cooldown_until=0.0,
                              last_success=self.clock())
                    # network accounting: LLM calls are alluvia's only
                    # traffic, so counting here covers all of it
                    import json as _json
                    st["calls"] = int(st.get("calls") or 0) + 1
                    st["sent_bytes"] = int(st.get("sent_bytes") or 0) + \
                        len(system.encode()) + len(user.encode())
                    try:
                        st["recv_bytes"] = int(st.get("recv_bytes") or 0) + \
                            len(_json.dumps(result, default=str).encode())
                    except (TypeError, ValueError):
                        pass
                    if st["est_rate"]:
                        st["est_rate"] = min(st["est_rate"] + _RATE_STEP, _RATE_CEIL)
                    self._save(model, st)
                    return result

        if soonest is not None:
            raise LLMUnavailable(soonest)
        raise last_exc if last_exc else RuntimeError("no llm candidates")
