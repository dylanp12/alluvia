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


def _shared_repo_with_memory(tmp_path):
    """A clone that carries a memory file from another machine."""
    from alluvia.repo_share import share_dir
    import json as _json
    clone = tmp_path / "clone"; (clone / ".git").mkdir(parents=True)
    share_dir(str(clone)).mkdir()
    recs = [{"kind": "header", "format": "alluvia-memory", "version": 1, "origin": "laptop-2", "pipeline_version": 3},
            {"kind": "session", "id": "claude-code:remote1", "source": "claude-code", "native_id": "remote1",
             "started_at": "2026-09-01T00:00:00+00:00", "ended_at": "2026-09-01T01:00:00+00:00",
             "project": None, "project_rel": ".", "branch": "main", "content_hash": "h"},
            {"kind": "note", "id": "n:remote", "session_id": "claude-code:remote1", "span_ref": "msg:0",
             "note_kind": "decision", "text": "queue runs on postgres, not redis", "created_at": "2026-09-01T00:30:00+00:00"}]
    (share_dir(str(clone)) / "memory.jsonl").write_text("\n".join(_json.dumps(r) for r in recs) + "\n")
    return clone


def test_session_start_imports_the_repos_shared_memory_first(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    clone = _shared_repo_with_memory(tmp_path)
    out = run_session_start({"cwd": str(clone), "source": "startup"}, repo)
    assert out is not None, "a fresh clone with a memory file must get its handoff on the first start"
    assert "queue runs on postgres" in out["hookSpecificOutput"]["additionalContext"]
    assert repo.session_origins("local") == {"claude-code:remote1": "laptop-2"}
    # the sidecar/event machinery is exercised in the proof tasks; here: idempotent on the second start
    again = run_session_start({"cwd": str(clone), "source": "resume"}, repo)
    assert "queue runs on postgres" in again["hookSpecificOutput"]["additionalContext"]


def test_capture_and_refresh_rewrite_the_share_when_on(repo, tmp_path, monkeypatch):
    from alluvia.repo_share import is_shared, set_shared, share_file
    from alluvia.hooks import refresh_handoffs
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    project = tmp_path / "acme"
    transcript = _transcript(tmp_path, project)
    set_shared(str(project), True)
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": [
        {"kind": "decision", "text": "pin clock skew in auth/refresh.py", "span": "msg:1"}]}]),
                 min_cluster_size=2)
    run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert share_file(str(project)).exists()
    assert "pin clock skew" in share_file(str(project)).read_text()
    share_file(str(project)).unlink()
    refresh_handoffs(repo, "local")
    assert share_file(str(project)).exists(), "refresh rewrites shares for repos that opted in"
    set_shared(str(project), False)
    refresh_handoffs(repo, "local")
    assert not share_file(str(project)).exists() and not is_shared(str(project))


def test_injection_records_an_event_with_the_note_ids(repo, tmp_path, monkeypatch):
    """Proof of use starts with knowing what was shown, when, and where."""
    import json as _json
    from alluvia.hooks import write_handoff, handoff_path
    from alluvia.models import Message, Note, RawSession, content_hash
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    project = tmp_path / "acme"; (project / ".git").mkdir(parents=True)
    msgs = [Message(role="user", text="x")]
    repo.upsert_session(RawSession(id="claude-code:s", user_id="local", source="claude-code", native_id="s",
                                   title="t", started_at=None, ended_at=None, messages=msgs,
                                   content_hash=content_hash(msgs), project=str(project), branch="main"))
    repo.upsert_notes([Note(id="n:d", user_id="local", session_id="claude-code:s", span_ref="msg:0",
                            kind="decision", text="use postgres", created_at=None)])
    assert write_handoff(repo, "local", str(project))
    sidecar = handoff_path(str(project)).with_suffix(".json")
    assert _json.loads(sidecar.read_text())["note_ids"] == ["n:d"]
    assert repo.list_handoff_events("local") == []                      # writing is not showing
    out = run_session_start({"cwd": str(project), "source": "startup"}, repo)
    assert out
    ev = repo.latest_handoff_event("local", str(project))
    assert ev["note_ids"] == ["n:d"] and ev["source"] == "startup" and ev["chars"] > 0
    run_session_start({"cwd": str(tmp_path / "elsewhere"), "source": "startup"}, repo)
    assert len(repo.list_handoff_events("local")) == 1                  # nothing shown, no event


def _sync_stub(result, calls=None):
    def sync(repo, user, **kw):
        if calls is not None:
            calls.append(user)
        if isinstance(result, Exception):
            raise result
        return result
    return sync


def test_capture_syncs_memory_and_never_fails_on_it(repo, tmp_path, monkeypatch):
    """Sign in once: every capture carries memory up and down. Signed out, the
    hook says so and touches nothing. A failing sync costs the user nothing."""
    from alluvia import cloud_memory
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    project = tmp_path / "acme"
    transcript = _transcript(tmp_path, project)
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": [
        {"kind": "decision", "text": "pin clock skew in auth/refresh.py", "span": "msg:1"}]}] * 3),
                 min_cluster_size=2)
    stats = run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert stats["cloud"] == {"ok": False, "skipped": "not signed in"}      # no session file
    calls = []
    monkeypatch.setattr(cloud_memory, "sync", _sync_stub(
        {"ok": True, "pull": {"ok": True, "notes_added": 0}, "push": {"ok": True, "notes": 1}}, calls))
    stats = run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert calls == ["local"] and stats["cloud"]["ok"] is True
    monkeypatch.setattr(cloud_memory, "sync", _sync_stub(RuntimeError("dns is down")))
    stats = run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert stats["handoff_written"] and "dns is down" in stats["cloud"]["error"]


def test_capture_rebuilds_handoffs_for_what_the_pull_brought(repo, tmp_path, monkeypatch):
    """Another machine's notes arrive during the pull; the NEXT session start in
    that repo must already see them, so every known repo's handoff is rebuilt."""
    from alluvia import cloud_memory
    from alluvia.models import Message, Note, RawSession, content_hash
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    project = tmp_path / "acme"
    transcript = _transcript(tmp_path, project)
    other = str(tmp_path / "other")

    def pulling_sync(repo_, user, **kw):
        msgs = [Message(role="user", text="remote")]
        repo_.upsert_session(RawSession(id="claude-code:r1", user_id=user, source="claude-code",
                                        native_id="r1", title="", started_at=None, ended_at=None,
                                        messages=[], content_hash=content_hash(msgs),
                                        project=other, branch="main"), imported_from="laptop-2")
        repo_.mark_distilled(user, "claude-code:r1")
        repo_.upsert_notes([Note(id="n:r", user_id=user, session_id="claude-code:r1", span_ref="msg:0",
                                 kind="decision", text="queue runs on postgres", created_at=None)])
        return {"ok": True, "pull": {"ok": True, "notes_added": 1}, "push": {"ok": True, "notes": 2}}
    monkeypatch.setattr(cloud_memory, "sync", pulling_sync)
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": [
        {"kind": "decision", "text": "pin clock skew in auth/refresh.py", "span": "msg:1"}]}]),
                 min_cluster_size=2)
    run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert "queue runs on postgres" in handoff_path(other).read_text()
    assert "pin clock skew" in handoff_path(str(project)).read_text()
