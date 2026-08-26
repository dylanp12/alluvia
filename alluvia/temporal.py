"""Deterministic time-scope parsing: "last Tuesday" is a date range, not a
search term. A small closed grammar of the expressions people actually type
at recall — no LLM, no locale guessing, `now` injectable for tests. Queries
without a time expression parse to None and cost one regex scan."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_WEEKDAYS = {n: i for i, n in enumerate(
    ("monday", "tuesday", "wednesday", "thursday", "friday",
     "saturday", "sunday"))}
_MONTHS = {n: i for i, n in enumerate(
    ("january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"), start=1)}

# an optional leading word rides along in the phrase: since/before change the
# range's shape; in/from/on/during are swallowed so cleaning removes them too
_PRE = (r"(?:(?P<mod>since|before|after|until)\s+"
        r"|(?P<prep>in|from|on|during)\s+)?")


@dataclass
class TimeScope:
    start: datetime | None      # inclusive, UTC midnight
    end: datetime | None       # exclusive, UTC midnight
    phrase: str                # the matched text, for surfaces to echo
    cleaned: str               # the query with the phrase removed


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_start(dt: datetime) -> datetime:
    return _day(dt) - timedelta(days=dt.weekday())


def _month_start(y: int, m: int) -> datetime:
    return datetime(y, m, 1, tzinfo=timezone.utc)


def _month_range(y: int, m: int) -> tuple[datetime, datetime]:
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return _month_start(y, m), _month_start(ny, nm)


def _shift_month(y: int, m: int, back: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) - back
    return idx // 12, idx % 12 + 1


def _r_weekday(m, now):
    wd = _WEEKDAYS[m.group("wd").lower()]
    delta = (now.weekday() - wd - 1) % 7 + 1      # most recent, never today
    d = _day(now) - timedelta(days=delta)
    return d, d + timedelta(days=1)


def _r_yesterday(m, now):
    d = _day(now) - timedelta(days=1)
    return d, d + timedelta(days=1)


def _r_today(m, now):
    d = _day(now)
    return d, d + timedelta(days=1)


def _r_last_week(m, now):
    ws = _week_start(now)
    return ws - timedelta(days=7), ws


def _r_this_week(m, now):
    return _week_start(now), None


def _r_last_month(m, now):
    y, mo = _shift_month(now.year, now.month, 1)
    return _month_range(y, mo)


def _r_this_month(m, now):
    return _month_start(now.year, now.month), None


def _r_last_year(m, now):
    return (datetime(now.year - 1, 1, 1, tzinfo=timezone.utc),
            datetime(now.year, 1, 1, tzinfo=timezone.utc))


def _r_ago(m, now):
    n, unit = int(m.group("n")), m.group("unit").lower()
    if unit == "day":
        d = _day(now) - timedelta(days=n)
        return d, d + timedelta(days=1)
    if unit == "week":
        ws = _week_start(now - timedelta(days=7 * n))
        return ws, ws + timedelta(days=7)
    y, mo = _shift_month(now.year, now.month, n)
    return _month_range(y, mo)


def _r_month(m, now):
    mo = _MONTHS[m.group("mon").lower()]
    yr = m.group("yr")
    y = int(yr) if yr else (now.year if mo <= now.month else now.year - 1)
    return _month_range(y, mo)


def _r_year(m, now):
    y = int(m.group("year"))
    return (datetime(y, 1, 1, tzinfo=timezone.utc),
            datetime(y + 1, 1, 1, tzinfo=timezone.utc))


_WD = "|".join(_WEEKDAYS)
_MON = "|".join(_MONTHS)
_GRAMMAR = [(re.compile(_PRE + pat, re.IGNORECASE), fn) for pat, fn in (
    (rf"(?:last|past)\s+(?P<wd>{_WD})\b", _r_weekday),
    (r"\byesterday\b", _r_yesterday),
    (r"\btoday\b", _r_today),
    (r"(?:last|past)\s+week\b", _r_last_week),
    (r"\bthis\s+week\b", _r_this_week),
    (r"(?:last|past)\s+month\b", _r_last_month),
    (r"\bthis\s+month\b", _r_this_month),
    (r"(?:last|past)\s+year\b", _r_last_year),
    (r"(?P<n>\d{1,2})\s+(?P<unit>day|week|month)s?\s+ago\b", _r_ago),
    (rf"(?P<mon>{_MON})(?:\s+(?P<yr>20\d\d))?\b", _r_month),
    (r"(?P<year>20[2-3]\d)\b", _r_year),
)]


def parse_time_scope(query: str, now: datetime | None = None) -> TimeScope | None:
    now = _utc(now) if now else datetime.now(timezone.utc)
    for rx, resolve in _GRAMMAR:
        for m in rx.finditer(query):
            # "may" is usually the modal verb — accept it only with a year or
            # a leading preposition making the temporal reading unambiguous
            if (resolve is _r_month and m.group("mon").lower() == "may"
                    and not (m.group("yr") or m.group("mod") or m.group("prep"))):
                continue
            start, end = resolve(m, now)
            mod = (m.group("mod") or "").lower()
            if mod in ("since", "after"):
                start, end = start, None
            elif mod in ("before", "until"):
                start, end = None, start
            cleaned = " ".join((query[:m.start()] + " " + query[m.end():]).split())
            return TimeScope(start=start, end=end, phrase=m.group(0).strip(),
                             cleaned=cleaned)
    return None
