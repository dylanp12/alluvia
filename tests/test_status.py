"""`alluvia status`: what lives on this machine, where, and what's running."""
import json
import os

from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia import config
from alluvia.inspect import storage_report
from alluvia.models import Message, RawSession, Note, Proposal, content_hash

runner = CliRunner()


def test_storage_report_shape_and_empty_store(repo):
    rep = storage_report(repo)
    assert set(rep["data_classes"]) == {"raw", "derived", "judgments"}
    assert rep["data_classes"]["raw"]["rows"] == 0
    assert rep["paths"]["store"]["exists"] is True
    assert rep["paths"]["store"]["bytes"] > 0
    assert rep["live"]["refresh_lock_pid"] is None
    assert rep["live"]["dashboard_port"] is None


def test_rows_land_in_the_right_data_class(repo):
    msgs = [Message(role="user", text="auth token service")]
    repo.upsert_session(RawSession(
        id="claude-code:s1", user_id="local", source="claude-code",
        native_id="s1", title="t", started_at=None, ended_at=None,
        messages=msgs, content_hash=content_hash(msgs)))
    repo.upsert_notes([Note(id="note:1", user_id="local",
                            session_id="claude-code:s1", span_ref="msg:0",
                            kind="idea", text="auth token service",
                            created_at=None)])
    repo.insert_proposal(Proposal(
        id="prop:1", user_id="local", created_at="2026-07-12T00:00:00+00:00",
        kind="theme", source_ref="theme:0", source_hash="h", title="T",
        text="do the thing", next_step="step", cites=["note:1"],
        novelty_sim=0.5, feasibility=4, risk=None, model="m"))
    rep = storage_report(repo)
    assert rep["data_classes"]["raw"]["rows"] == 1
    assert rep["data_classes"]["raw"]["content_bytes"] > 0
    assert rep["data_classes"]["derived"]["rows"] >= 1
    assert rep["data_classes"]["judgments"]["rows"] == 1


def test_lock_probe_reports_holder(repo):
    from alluvia.lockfile import acquire
    store = repo.conn.execute("PRAGMA database_list").fetchone()[2]
    held = acquire(store + ".refresh.lock")
    try:
        assert storage_report(repo)["live"]["refresh_lock_pid"] == os.getpid()
    finally:
        held.release()


def test_status_cli_json_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    r = runner.invoke(cli.app, ["status", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert "data_classes" in data and "paths" in data and "live" in data


def test_status_cli_human_mentions_data_classes(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    r = runner.invoke(cli.app, ["status"])
    assert r.exit_code == 0
    out = r.output.lower()
    assert "raw" in out and "judgments" in out and "rebuildable" in out
