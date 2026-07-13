"""First five minutes: distill newest-first, cap the very first run so a
stranger sees a living map in minutes — and label/status keep budget headroom."""
import json
from datetime import datetime, timedelta

from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia.engine.engine import Engine, pending_distill
from alluvia.llm.client import FakeLLM
from alluvia.models import Message, RawSession, content_hash, session_id

from tests.test_cli_m1 import ScriptedEmbedder

runner = CliRunner()
BASE = datetime(2026, 1, 1)


def _sess(native, text, day):
    ts = BASE + timedelta(days=day)
    msgs = [Message(role="user", text=text, ts=ts)]
    return RawSession(id=session_id("claude-code", native), user_id="local",
                      source="claude-code", native_id=native, title=text,
                      started_at=ts, ended_at=ts, messages=msgs,
                      content_hash=content_hash(msgs))


def test_pending_distill_is_newest_first(repo):
    repo.upsert_session(_sess("old", "auth alpha", 1))
    repo.upsert_session(_sess("new", "auth beta", 90))
    repo.upsert_session(_sess("mid", "auth gamma", 45))
    todo = pending_distill(repo, "local")
    assert [s.native_id for s in todo] == ["new", "mid", "old"]


def test_undated_sessions_sort_last(repo):
    repo.upsert_session(_sess("dated", "auth alpha", 10))
    undated = _sess("undated", "auth beta", 0)
    undated.started_at = None
    repo.upsert_session(undated)
    assert [s.native_id for s in pending_distill(repo, "local")] == [
        "dated", "undated"]


def test_first_run_caps_and_reports_backfill(repo, monkeypatch):
    monkeypatch.setattr(Engine, "FIRST_RUN_CAP", 2)
    for i in range(5):
        repo.upsert_session(_sess(f"s{i}", f"auth topic {i}", i))
    llm = FakeLLM([
        {"notes": [{"kind": "idea", "text": "auth topic 4", "span": "msg:0"}]},
        {"notes": [{"kind": "idea", "text": "auth topic 3", "span": "msg:0"}]},
        {"label": "Auth", "summary": "a"},
    ])
    eng = Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)
    stats = eng.refresh("local", now=BASE + timedelta(days=10))
    # only the 2 NEWEST distilled; 3 deferred, honestly reported
    assert stats["distill"]["ok"] == 2
    assert stats["distill"]["deferred"] == 3
    assert repo.session_ids_with_notes("local") == {
        "claude-code:s4", "claude-code:s3"}


def test_second_run_backfills_uncapped(repo, monkeypatch):
    monkeypatch.setattr(Engine, "FIRST_RUN_CAP", 2)
    for i in range(5):
        repo.upsert_session(_sess(f"s{i}", f"auth topic {i}", i))
    def _llm(n):
        return FakeLLM([{"notes": [{"kind": "idea", "text": f"auth t{j}",
                                    "span": "msg:0"}]} for j in range(n)]
                       + [{"label": "Auth", "summary": "a"}] * 4)
    eng = Engine(repo, ScriptedEmbedder(), _llm(2), min_cluster_size=2)
    eng.refresh("local", now=BASE + timedelta(days=10))
    eng2 = Engine(repo, ScriptedEmbedder(), _llm(3), min_cluster_size=2)
    stats2 = eng2.refresh("local", now=BASE + timedelta(days=10))
    assert stats2["distill"]["ok"] == 3          # backfill completes, no cap
    assert stats2["distill"]["deferred"] == 0


def test_cap_disabled_via_env(repo, monkeypatch):
    monkeypatch.setenv("ALLUVIA_FIRST_RUN_CAP", "0")
    for i in range(4):
        repo.upsert_session(_sess(f"s{i}", f"auth topic {i}", i))
    llm = FakeLLM([{"notes": [{"kind": "idea", "text": f"auth t{j}",
                               "span": "msg:0"}]} for j in range(4)]
                  + [{"label": "Auth", "summary": "a"}] * 2)
    eng = Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)
    stats = eng.refresh("local", now=BASE + timedelta(days=10))
    assert stats["distill"]["ok"] == 4 and stats["distill"]["deferred"] == 0


def test_cli_reports_deferred_backfill(tmp_path, monkeypatch):
    from tests.test_cli_degraded import _seed_logs, _engine_factory, DISTILL
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("ALLUVIA_FIRST_RUN_CAP", "2")
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    llm = FakeLLM(DISTILL[:2] + [{"label": "A", "summary": "a"}])
    monkeypatch.setattr(cli, "build_engine", _engine_factory(llm))
    logs = _seed_logs(tmp_path)
    runner.invoke(cli.app, ["ingest", "--source", "claude-code",
                            "--path", str(logs)])
    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 0, r.output
    assert "2 more" in r.output and "backfill" in r.output
