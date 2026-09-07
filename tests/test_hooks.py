"""Claude Code hooks: the surface that makes memory deterministic. Start
injects the cached handoff for this repo (fast, no model, no LLM); end and
pre-compact ingest the live transcript, distill that one session, and rebuild
the cache. Hooks never fail the user's session."""
import json
from alluvia.engine.engine import Engine
from alluvia.engine.embed import FakeEmbedder
from alluvia.hooks import run_capture, run_session_start, handoff_path
from alluvia.llm.client import FakeLLM


def _transcript(tmp_path, project):
    (project / ".git").mkdir(parents=True, exist_ok=True)
    p = tmp_path / "abc123.jsonl"
    rec = lambda t, c: json.dumps({"type": t, "cwd": str(project), "gitBranch": "main",
                                   "message": {"role": t, "content": c}})
    p.write_text(rec("user", "fix the token race") + "\n"
                 + rec("assistant", [{"type": "text", "text": "Pinned clock skew."},
                                     {"type": "tool_use", "name": "Edit",
                                      "input": {"file_path": str(project / "auth/refresh.py")}}]) + "\n")
    return p


def test_capture_then_start_round_trip(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    project = tmp_path / "acme"
    transcript = _transcript(tmp_path, project)
    # nothing known yet → start injects nothing
    assert run_session_start({"cwd": str(project), "source": "startup"}, repo) is None
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": [
        {"kind": "decision", "text": "pin clock skew in auth/refresh.py", "span": "msg:1"}]}]),
                 min_cluster_size=2)
    stats = run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert stats["ingested"] and stats["notes"] == 1 and stats["handoff_written"]
    assert handoff_path(str(project)).exists()
    out = run_session_start({"cwd": str(project / "src"), "source": "compact"}, repo)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "pin clock skew in auth/refresh.py" in out["hookSpecificOutput"]["additionalContext"]
    assert repo.get_meta("hook:last_run")


def test_capture_survives_a_cold_provider(repo, tmp_path, monkeypatch):
    from alluvia.llm.governor import LLMUnavailable
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    project = tmp_path / "acme"
    transcript = _transcript(tmp_path, project)

    class Cold:
        def complete_json(self, *a, **k):
            raise LLMUnavailable(0, "cooling")
    eng = Engine(repo, FakeEmbedder(dim=8), Cold(), min_cluster_size=2)
    stats = run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert stats["ingested"] and stats["notes"] == 0 and stats["pending"] is True
    assert repo.list_session_meta("local", project=str(project))      # raw kept


def test_hook_cli_never_fails_and_only_prints_json_on_start(repo, tmp_path, monkeypatch):
    import alluvia.cli as cli
    from typer.testing import CliRunner
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    r = CliRunner().invoke(cli.app, ["hook", "session-start"], input="not json at all")
    assert r.exit_code == 0 and r.output.strip() == ""
    r = CliRunner().invoke(cli.app, ["hook", "session-end"],
                           input=json.dumps({"transcript_path": "/nope.jsonl"}))
    assert r.exit_code == 0 and r.output.strip() == ""
    log = tmp_path / "handoff" / "hooks.log"
    assert log.exists() and "nope.jsonl" in log.read_text()


def test_capture_still_rebuilds_the_handoff_when_distill_blows_up(repo, tmp_path, monkeypatch):
    """Any distill failure is recorded, never raised: the raw session is kept
    and the handoff is rebuilt from what is already known."""
    from alluvia.models import Note
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    project = tmp_path / "acme"
    transcript = _transcript(tmp_path, project)
    # something is already known about this repo from an earlier session
    from alluvia.models import Message, RawSession, content_hash
    msgs = [Message(role="user", text="earlier")]
    repo.upsert_session(RawSession(id="claude-code:earlier", user_id="local", source="claude-code",
                                   native_id="earlier", title="t", started_at=None, ended_at=None,
                                   messages=msgs, content_hash=content_hash(msgs),
                                   project=str(project), branch="main"))
    repo.upsert_notes([Note(id="n:e", user_id="local", session_id="claude-code:earlier",
                            span_ref="msg:0", kind="decision", text="rotate tokens server-side",
                            created_at=None)])
    repo.mark_distilled("local", "claude-code:earlier")

    class Boom:
        def complete_json(self, *a, **k):
            raise RuntimeError("provider returned garbage")
    eng = Engine(repo, FakeEmbedder(dim=8), Boom(), min_cluster_size=2)
    stats = run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert stats["ingested"] and stats["notes"] == 0
    assert "garbage" in stats["distill_error"]
    assert stats["handoff_written"]
    assert "rotate tokens server-side" in handoff_path(str(project)).read_text()


def test_refresh_handoffs_writes_every_known_repo_and_clears_empty_ones(repo, tmp_path, monkeypatch):
    """After a backfill the FIRST session in each repo should already get its
    handoff, not wait for a session-end hook to have run there."""
    from alluvia.hooks import refresh_handoffs
    from alluvia.models import Message, Note, RawSession, content_hash
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    msgs = [Message(role="user", text="work")]
    for native, project in (("a", "/work/acme"), ("b", "/work/other"), ("c", None)):
        repo.upsert_session(RawSession(id=f"claude-code:{native}", user_id="local", source="claude-code",
                                       native_id=native, title="t", started_at=None, ended_at=None,
                                       messages=msgs, content_hash=content_hash(msgs),
                                       project=project, branch=None))
    repo.upsert_notes([Note(id="n:a", user_id="local", session_id="claude-code:a", span_ref="msg:0",
                            kind="decision", text="acme uses postgres", created_at=None)])
    stale = handoff_path("/work/other"); stale.parent.mkdir(parents=True); stale.write_text("old")
    written = refresh_handoffs(repo, "local")
    assert written == 1
    assert "acme uses postgres" in handoff_path("/work/acme").read_text()
    assert not stale.exists(), "a repo with nothing known must not keep a stale handoff"
