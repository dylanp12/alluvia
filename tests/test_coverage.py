"""Distill coverage is a number the user sees: recall can only find what was
distilled, and a store that is 20% distilled must never look healthy."""
from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia.doctor import run_doctor
from alluvia.inspect import storage_report
from alluvia.models import Message, RawSession, content_hash


def _seed(repo, n=4, distilled=1):
    for i in range(n):
        msgs = [Message(role="user", text=f"topic {i}")]
        repo.upsert_session(RawSession(id=f"claude-code:s{i}", user_id="local", source="claude-code",
                                       native_id=f"s{i}", title="t", started_at=None, ended_at=None,
                                       messages=msgs, content_hash=content_hash(msgs)))
    for i in range(distilled):
        repo.mark_distilled("local", f"claude-code:s{i}")


def test_coverage_counts(repo):
    _seed(repo)
    assert repo.distill_coverage("local") == {"sessions": 4, "distilled": 1, "pending": 3}
    assert storage_report(repo)["coverage"] == {"sessions": 4, "distilled": 1, "pending": 3}


def test_status_and_doctor_say_it_loudly(repo, monkeypatch):
    _seed(repo)
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    out = CliRunner().invoke(cli.app, ["status"]).output
    assert "distilled   1/4 sessions (25%)" in out and "3 pending" in out
    f = next(f for f in run_doctor(repo, check_only=True) if f.name == "coverage")
    assert f.status == "warn" and "3" in f.detail and "alluvia refresh" in f.remedy


def test_refresh_summary_prints_coverage_and_pause(capsys):
    cli._echo_refresh_summary({"distill": {"todo": 3, "ok": 1, "zero_note": 0, "failed": 0,
                                           "cold": True, "deferred": 0},
                               "themes": {}, "degraded": True,
                               "retry_at": "2026-09-05T12:00:00+00:00"},
                              coverage={"sessions": 4, "distilled": 2, "pending": 2})
    out = capsys.readouterr().out
    assert "coverage: 2/4 sessions distilled (50%)" in out
    assert "paused" in out and "2 pending" in out
