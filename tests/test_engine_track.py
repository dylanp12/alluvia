from datetime import datetime
from alluvia.models import Note, Theme
from alluvia.llm.client import FakeLLM
from alluvia.engine.track import classify_status

NOW = datetime(2026, 7, 1)


def _theme(sessions, first_day, last_day, note_ids=("n1",)):
    return Theme(id="theme:0", user_id="local", label="L", summary="S",
                 note_ids=list(note_ids), first_seen=datetime(2026, 1, first_day),
                 last_seen=datetime(2026, 1, last_day), session_count=sessions, source_count=1)


def _notes(ids):
    return {i: Note(id=i, user_id="local", session_id="s", span_ref="", kind="idea",
                    text=i, created_at=None) for i in ids}


class _Cache:
    def __init__(self):
        self.d = {}
    def get(self, u, h):
        return self.d.get(h)
    def set(self, u, h, s):
        self.d[h] = s


def test_non_recurring_is_unknown_and_calls_no_llm():
    llm = FakeLLM([])                       # would IndexError if called
    t = _theme(sessions=1, first_day=1, last_day=1)      # single session -> not recurring
    assert classify_status("local", t, _notes(["n1"]), llm, _Cache(), now=NOW) == "unknown"


def test_recurring_open_then_dormant_overlay():
    llm = FakeLLM([{"status": "open"}])
    fresh = _theme(sessions=3, first_day=1, last_day=20)     # Jan 20 is >60d before Jul 1
    assert classify_status("local", fresh, _notes(["n1"]), llm, _Cache(), now=NOW,
                           stale_days=60) == "dormant"


def test_cache_hit_skips_llm():
    cache = _Cache()
    t = _theme(sessions=3, first_day=1, last_day=25)
    classify_status("local", t, _notes(["n1"]), FakeLLM([{"status": "resolved"}]), cache, now=NOW)
    # second call with an empty FakeLLM must not call it (cache hit)
    assert classify_status("local", t, _notes(["n1"]), FakeLLM([]), cache, now=NOW) == "resolved"


def test_mixed_aware_naive_datetimes_do_not_crash():
    # regression: real adapters emit tz-AWARE timestamps while now()/tests were
    # naive -> TypeError on first live run (caught at the M2b mini-gate)
    from datetime import timezone
    t = _theme(sessions=3, first_day=1, last_day=20)
    t.first_seen = t.first_seen.replace(tzinfo=timezone.utc)   # aware
    t.last_seen = t.last_seen.replace(tzinfo=timezone.utc)     # aware
    status = classify_status("local", t, _notes(["n1"]),
                             FakeLLM([{"status": "open"}]), _Cache(),
                             now=NOW)                          # naive now
    assert status == "dormant"                                 # jan vs jul: stale
