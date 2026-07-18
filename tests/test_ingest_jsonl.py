"""Normalized-session JSONL source (#15): any feeder that writes the
documented schema becomes an ingestion source — multi-machine aggregation
and community-maintained formats without alluvia growing parsers."""
import json

from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia.ingest.jsonl_source import JsonlSourceAdapter

runner = CliRunner()


def _line(source="codex", native="x1", title="auth bug", ts="2026-06-01T10:00:00+00:00"):
    return json.dumps({
        "source": source, "native_id": native, "title": title,
        "started_at": ts, "ended_at": None,
        "messages": [{"role": "user", "text": "auth token refresh race", "ts": ts},
                     {"role": "assistant", "text": "the refresh lacks a lock", "ts": ts}],
    })


def test_reads_file_and_directory(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text(_line() + "\n" + _line(native="x2", title="second") + "\n")
    sessions = list(JsonlSourceAdapter(str(f), user_id="local").read())
    assert [s.native_id for s in sessions] == ["x1", "x2"]
    assert sessions[0].source == "codex"
    assert sessions[0].id == "codex:x1"
    assert sessions[0].messages[1].role == "assistant"

    d = tmp_path / "many"
    d.mkdir()
    (d / "one.jsonl").write_text(_line(source="opencode", native="o1") + "\n")
    (d / "two.jsonl").write_text(_line(source="pi", native="p1") + "\n")
    got = {s.id for s in JsonlSourceAdapter(str(d), user_id="local").read()}
    assert got == {"opencode:o1", "pi:p1"}


def test_invalid_lines_are_skipped_not_fatal(tmp_path):
    f = tmp_path / "a.jsonl"
    f.write_text("\n".join([
        "not json at all",
        json.dumps({"source": "codex"}),                       # missing fields
        json.dumps({"source": "codex", "native_id": "ok",
                    "messages": []}),                          # no messages
        _line(native="good"),
    ]) + "\n")
    sessions = list(JsonlSourceAdapter(str(f), user_id="local").read())
    assert [s.native_id for s in sessions] == ["good"]


def test_arbitrary_sources_flow_through_ingest_and_store(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    f = tmp_path / "pond-export.jsonl"
    f.write_text(_line(source="claude-desktop", native="cd1") + "\n")
    r = runner.invoke(cli.app, ["ingest", "--source", "jsonl", "--path", str(f)])
    assert r.exit_code == 0, r.output
    assert "1 new" in r.output
    repo = cli._repo()
    assert repo.list_sessions("local")[0].source == "claude-desktop"
    # re-ingest dedups on content hash
    r2 = runner.invoke(cli.app, ["ingest", "--source", "jsonl", "--path", str(f)])
    assert "0 new" in r2.output


def test_contract_doc_ships_and_matches_reality(tmp_path):
    import os
    doc = os.path.join(os.path.dirname(cli.__file__), "..", "docs", "SOURCES.md")
    text = open(doc).read()
    for field in ("source", "native_id", "started_at", "messages", "role", "text"):
        assert f"`{field}`" in text
    assert "jsonl" in text
