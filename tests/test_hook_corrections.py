"""Corrections must reach the next actual hook, not only a fresh renderer."""
import json
import sqlite3

import pytest
from typer.testing import CliRunner

from alluvia import cli, cloud_memory, config
from alluvia.engine.embed import FakeEmbedder
from alluvia.engine.engine import Engine
from alluvia.hooks import handoff_path, run_capture, run_session_start, write_handoff
from alluvia.llm.client import FakeLLM
from alluvia.memory_bundle import import_bundle
from alluvia.models import Message, Note, RawSession, content_hash
from alluvia.repo_share import share_file


NOTE_ID = "note:queue"
NOTE_TEXT = "Use a bounded queue for background jobs."


@pytest.fixture
def project(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoffs"))
    config.reset_toml_cache()
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    monkeypatch.setattr(cli, "_recall_embedder", lambda: FakeEmbedder(dim=8))
    root = tmp_path / "sample"
    (root / ".git").mkdir(parents=True)
    messages = [Message(role="user", text=NOTE_TEXT)]
    repo.upsert_session(RawSession(
        id="claude-code:queue", user_id="local", source="claude-code", native_id="queue",
        title="Queue", started_at=None, ended_at=None, messages=messages,
        content_hash=content_hash(messages), project=str(root), branch="main"))
    repo.upsert_notes([Note(
        id=NOTE_ID, user_id="local", session_id="claude-code:queue", span_ref="msg:0",
        kind="decision", text=NOTE_TEXT, created_at=None)])
    repo.mark_distilled("local", "claude-code:queue")
    write_handoff(repo, "local", str(root))
    return root


def _start(project):
    result = CliRunner().invoke(cli.app, ["hook", "session-start"], input=json.dumps({
        "cwd": str(project), "source": "startup"}))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["hookSpecificOutput"]["additionalContext"] if result.output.strip() else None


def test_cli_forget_is_honored_by_the_next_cached_start(repo, project):
    assert NOTE_TEXT in _start(project)
    before = len(repo.list_handoff_events("local"))
    result = CliRunner().invoke(cli.app, ["forget", NOTE_ID])
    assert result.exit_code == 0, result.output
    assert _start(project) is None
    assert len(repo.list_handoff_events("local")) == before


def test_cli_undo_restores_context_even_when_the_empty_cache_was_removed(repo, project):
    repo.suppress_note("local", NOTE_ID)
    write_handoff(repo, "local", str(project))
    assert not handoff_path(str(project)).exists()
    result = CliRunner().invoke(cli.app, ["unforget", NOTE_ID])
    assert result.exit_code == 0, result.output
    assert NOTE_TEXT in _start(project)
    assert repo.latest_handoff_event("local", str(project))["note_ids"] == [NOTE_ID]


@pytest.mark.parametrize("source", ["shared-file", "cli-import", "bundle-import"])
@pytest.mark.parametrize("undo", [False, True])
def test_correction_only_import_changes_the_next_start(repo, project, tmp_path, source, undo):
    if undo:
        repo.suppress_note("local", NOTE_ID)
        write_handoff(repo, "local", str(project))
    records = [{"kind": "suppressed", "note_id": NOTE_ID, "retracted": undo}]
    if source == "shared-file":
        path = share_file(str(project))
        path.parent.mkdir()
        path.write_text(json.dumps(records[0]) + "\n")
    elif source == "cli-import":
        path = tmp_path / "correction.jsonl"
        path.write_text(json.dumps(records[0]) + "\n")
        result = CliRunner().invoke(cli.app, ["memory", "import", str(path)])
        assert result.exit_code == 0, result.output
    else:
        imported = import_bundle(repo, "local", records)
        assert imported["judgments_added"] == 1
        assert imported["notes_added"] == imported["sessions_added"] == 0
    context = _start(project)
    if undo:
        assert NOTE_TEXT in context
    else:
        assert context is None


def test_cli_import_into_an_empty_store_is_available_on_first_start(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoffs"))
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    monkeypatch.setattr(cli, "_recall_embedder", lambda: FakeEmbedder(dim=8))
    project = tmp_path / "clone"
    (project / ".git").mkdir(parents=True)
    records = [
        {"kind": "session", "id": "claude-code:remote", "source": "claude-code",
         "native_id": "remote", "project": str(project), "branch": "main"},
        {"kind": "note", "id": NOTE_ID, "session_id": "claude-code:remote",
         "note_kind": "decision", "span_ref": "msg:0", "text": NOTE_TEXT},
    ]
    path = tmp_path / "import.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records))
    result = CliRunner().invoke(cli.app, ["memory", "import", str(path)])
    assert result.exit_code == 0, result.output
    assert NOTE_TEXT in _start(project)


@pytest.mark.parametrize("damage", ["missing", "invalid-encoding", "wrong-text", "bad-sidecar"])
def test_current_records_take_precedence_over_missing_or_corrupt_cache(repo, project, damage):
    cache = handoff_path(str(project))
    if damage == "missing":
        cache.unlink()
    elif damage == "invalid-encoding":
        cache.write_bytes(b"\xff\xfe")
    elif damage == "wrong-text":
        cache.write_text("stale instruction from another store")
    else:
        cache.with_suffix(".json").write_text("not json")
    assert NOTE_TEXT in _start(project)
    assert repo.latest_handoff_event("local", str(project))["note_ids"] == [NOTE_ID]


def test_unknown_project_never_injects_an_orphaned_cache(repo, project, tmp_path):
    other = tmp_path / "unknown"
    (other / ".git").mkdir(parents=True)
    handoff_path(str(other)).write_text("left over from an obsolete store")
    assert _start(other) is None
    assert repo.latest_handoff_event("local", str(other)) is None


def test_unreadable_current_records_do_not_fall_back_to_old_text(repo, project, monkeypatch):
    def unreadable(*args, **kwargs):
        raise sqlite3.OperationalError("store unavailable")
    monkeypatch.setattr(repo, "get_notes", unreadable)
    assert _start(project) is None
    assert repo.list_handoff_events("local") == []


def test_uncertain_shared_corrections_do_not_reinject_old_text(repo, project, monkeypatch):
    import alluvia.hooks as hooks
    def unreadable(*args, **kwargs):
        raise OSError("shared memory cannot be read")
    monkeypatch.setattr(hooks, "import_share_if_changed", unreadable)
    assert _start(project) is None
    assert repo.list_handoff_events("local") == []


def test_malformed_optional_share_record_does_not_hide_local_memory(repo, project):
    path = share_file(str(project))
    path.parent.mkdir()
    path.write_text("not a memory record\n")
    handoff_path(str(project)).unlink()
    assert NOTE_TEXT in _start(project)


def test_start_builds_context_without_a_model_or_cloud(repo, project, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("session start must stay local and model-free")
    monkeypatch.setattr(cli, "build_engine", forbidden)
    monkeypatch.setattr(cloud_memory, "pull", forbidden)
    monkeypatch.setattr(cloud_memory, "sync", forbidden)
    handoff_path(str(project)).unlink()
    assert NOTE_TEXT in _start(project)


@pytest.mark.parametrize("push_ok", [True, False])
def test_capture_rebuilds_other_project_cache_after_cloud_correction(repo, project, tmp_path, monkeypatch, push_ok):
    from tests.test_hooks import _transcript
    other = tmp_path / "other"
    transcript = _transcript(tmp_path, other)
    def sync(repo_, user):
        pulled = import_bundle(repo_, user, [{"kind": "suppressed", "note_id": NOTE_ID}])
        return {"ok": push_ok, "pull": {"ok": True, **pulled}, "push": {"ok": push_ok}}
    monkeypatch.setattr(cloud_memory, "sync", sync)
    engine = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": []}]), min_cluster_size=2)
    run_capture({"transcript_path": str(transcript), "cwd": str(other)}, repo, engine)
    assert not handoff_path(str(project)).exists()
    assert run_session_start({"cwd": str(project)}, repo) is None
