"""Protect keeps source authority visible and reports real verification outcomes."""
import json
import subprocess
import sys

import pytest
from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia.models import Message, Note, RawSession, content_hash


def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def project(tmp_path):
    path = tmp_path / "project"
    path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.name", "Example")
    git(path, "config", "user.email", "example@example.invalid")
    return path


def seed(repo, project, *, role="user", text="Expire previews after 20 minutes.", span="msg:0"):
    messages = [Message(role=role, text=text)]
    session = RawSession(id="claude-code:correction", user_id="local",
                         source="claude-code", native_id="correction", title="Expiry",
                         started_at=None, ended_at=None, messages=messages,
                         content_hash=content_hash(messages),
                         project=str(project) if project is not None else None,
                         branch="main")
    repo.upsert_session(session)
    repo.upsert_notes([Note(id="note:expiry", user_id="local", session_id=session.id,
                           span_ref=span, kind="decision", text="Use 20 minutes.", created_at=None)])
    return session


def source(repo, project, monkeypatch):
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    return CliRunner().invoke(cli.app, ["checks", "source", "note:expiry", "--project", str(project)])


def test_source_reports_original_role_span_and_content_without_mutating(repo, project, monkeypatch):
    session = seed(repo, project, role="assistant")
    result = source(repo, project, monkeypatch)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["kind"] == "history_note"
    assert payload["role"] == "assistant"
    assert payload["text"] == "Expire previews after 20 minutes."
    assert payload["span_ref"] == "msg:0"
    assert payload["content_hash"] == session.content_hash
    assert payload["truncated"] is False
    assert repo.get_session("local", session.id) == session


@pytest.mark.parametrize("problem", ["other_project", "unscoped", "suppressed", "bad_span", "meta"])
def test_source_refuses_unrelated_or_unusable_evidence(repo, project, tmp_path, monkeypatch, problem):
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    seed(repo, other if problem == "other_project" else None if problem == "unscoped" else project,
         span="bad:0" if problem == "bad_span" else "msg:0",
         text="Stop hook feedback: continue" if problem == "meta" else "Use 20 minutes.")
    if problem == "suppressed":
        repo.suppress_note("local", "note:expiry")
    result = source(repo, project, monkeypatch)
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["error"]


def test_source_redacts_and_marks_truncation(repo, project, monkeypatch):
    raw = "sk-" + "a" * 24 + " " + "correction " * 500
    seed(repo, project, text=raw)
    result = source(repo, project, monkeypatch)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "sk-" not in payload["text"]
    assert payload["text"].startswith("[REDACTED]")
    assert payload["truncated"] is True
    assert len(payload["text"]) <= 4000


def test_source_accepts_same_repository_from_a_nested_directory(repo, project, monkeypatch):
    seed(repo, project)
    nested = project / "service"
    nested.mkdir()
    result = source(repo, nested, monkeypatch)
    assert result.exit_code == 0, result.output


def test_verify_rejects_invalid_source_before_running(project, tmp_path):
    receipt = tmp_path / "source.json"
    receipt.write_text('{"kind": "user_instruction", "text": ""}')
    result = CliRunner().invoke(cli.app, ["checks", "verify", "tests/test_guard.py::test_limit",
        "--before", "HEAD~1", "--project", str(project), "--requirement", "Limit 20",
        "--source-file", str(receipt), "--output", str(tmp_path / "bundle")])
    assert result.exit_code == 2, result.output
    assert "source" in json.loads(result.output)["error"].lower()
    assert not (tmp_path / "bundle").exists()


def test_verify_cli_exports_an_actual_regression_and_sets_exit_status(project, tmp_path):
    module = project / "expiry.py"
    module.write_text("def expired(minutes):\n    return minutes >= 45\n")
    git(project, "add", ".")
    git(project, "commit", "-qm", "Initial expiry")
    before = git(project, "rev-parse", "HEAD")
    module.write_text("def expired(minutes):\n    return minutes >= 20\n")
    git(project, "add", ".")
    git(project, "commit", "-qm", "Correct expiry")
    tests = project / "tests"
    tests.mkdir()
    check = tests / "test_expiry_guard.py"
    check.write_text("from expiry import expired\n\ndef test_expiry():\n    assert expired(20)\n    assert not expired(19)\n")
    receipt = tmp_path / "source.json"
    receipt.write_text(json.dumps({"kind": "user_instruction", "text": "Expire after 20 minutes."}))
    args = ["checks", "verify", "tests/test_expiry_guard.py::test_expiry", "--before", before,
            "--project", str(project), "--python", sys.executable, "--requirement", "Expire at 20 minutes",
            "--source-file", str(receipt)]
    result = CliRunner().invoke(cli.app, args + ["--output", str(tmp_path / "bundle")])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "verified"
    assert (tmp_path / "bundle" / "report.json").is_file()
    result = CliRunner().invoke(cli.app, args + ["--after", before, "--output", str(tmp_path / "same")])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["status"] == "not_verified"
