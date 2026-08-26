"""Deterministic time-scope parsing: "last Tuesday" is a date range, not a
search term. No LLM, no locale guessing — a small closed grammar of the
expressions people actually type at recall."""
from __future__ import annotations
from datetime import datetime, timezone

from alluvia.temporal import parse_time_scope

# Wednesday, mid-August
NOW = datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc)


def _day(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


def test_last_weekday_is_the_most_recent_past_occurrence():
    s = parse_time_scope("what did we fix last tuesday", now=NOW)
    assert s.start == _day(2026, 8, 11) and s.end == _day(2026, 8, 12)
    assert s.cleaned == "what did we fix"


def test_last_weekday_never_means_today():
    s = parse_time_scope("last wednesday", now=NOW)      # today is Wednesday
    assert s.start == _day(2026, 8, 5) and s.end == _day(2026, 8, 6)


def test_yesterday_and_today():
    y = parse_time_scope("the bug from yesterday", now=NOW)
    assert y.start == _day(2026, 8, 11) and y.end == _day(2026, 8, 12)
    t = parse_time_scope("what broke today", now=NOW)
    assert t.start == _day(2026, 8, 12) and t.end == _day(2026, 8, 13)


def test_last_week_is_the_previous_calendar_week():
    s = parse_time_scope("deploy issues last week", now=NOW)
    assert s.start == _day(2026, 8, 3) and s.end == _day(2026, 8, 10)
    assert s.cleaned == "deploy issues"


def test_month_names_resolve_to_their_most_recent_occurrence():
    s = parse_time_scope("the auth call in march", now=NOW)
    assert s.start == _day(2026, 3, 1) and s.end == _day(2026, 4, 1)
    s2 = parse_time_scope("september outage", now=NOW)   # future month -> last year
    assert s2.start == _day(2025, 9, 1) and s2.end == _day(2025, 10, 1)


def test_month_with_explicit_year():
    s = parse_time_scope("march 2025 migration", now=NOW)
    assert s.start == _day(2025, 3, 1) and s.end == _day(2025, 4, 1)
    assert s.cleaned == "migration"


def test_n_units_ago():
    d = parse_time_scope("3 days ago", now=NOW)
    assert d.start == _day(2026, 8, 9) and d.end == _day(2026, 8, 10)
    w = parse_time_scope("that refactor 2 weeks ago", now=NOW)
    assert w.start == _day(2026, 7, 27) and w.end == _day(2026, 8, 3)


def test_since_and_before_open_the_range():
    s = parse_time_scope("auth changes since march", now=NOW)
    assert s.start == _day(2026, 3, 1) and s.end is None
    b = parse_time_scope("what we believed before march", now=NOW)
    assert b.start is None and b.end == _day(2026, 3, 1)


def test_bare_year_is_a_year_range():
    s = parse_time_scope("the 2025 rewrite", now=NOW)
    assert s.start == _day(2025, 1, 1) and s.end == _day(2026, 1, 1)


def test_may_needs_a_preposition_or_year():
    assert parse_time_scope("how may we improve retries", now=NOW) is None
    s = parse_time_scope("the incident in may", now=NOW)
    assert s.start == _day(2026, 5, 1) and s.end == _day(2026, 6, 1)


def test_no_temporal_expression_returns_none():
    assert parse_time_scope("auth token refresh race", now=NOW) is None
    assert parse_time_scope("ECONNREFUSED worker pool", now=NOW) is None


def test_cleaned_query_collapses_whitespace():
    s = parse_time_scope("the fix  from last tuesday  for auth", now=NOW)
    assert s.cleaned == "the fix for auth"
