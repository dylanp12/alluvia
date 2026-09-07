"""Proof of use: what the memory did, counted honestly."""
from typer.testing import CliRunner
import alluvia.cli as cli


def test_references_heuristic_terms_and_action_paths():
    from alluvia.proof import referenced_notes
    notes = {"n:a": "pin clock skew in auth/refresh.py",
             "n:b": "use postgres for the queue",
             "n:c": "retry budget"}
    session_text = ("I pinned the clock skew as planned.\n[action] Edit auth/refresh.py\n"
                    "the queue stays on redis for now")
    assert referenced_notes(notes, session_text) == ["n:a"]     # terms + action path; b, c absent
    assert referenced_notes(notes, "") == []
    # two distinctive terms (>=5 chars) suffice even without a path
    assert referenced_notes({"n:b": "use postgres for the queue"},
                            "we moved the queue onto postgres yesterday") == ["n:b"]


def test_verdict_attaches_to_latest_event_of_this_repo(repo):
    from alluvia.proof import record_verdict_for
    assert record_verdict_for(repo, "local", "/work/acme", "kept") is None     # no event yet
    eid = repo.record_handoff_event("local", "/work/acme", ["n:1"], chars=10, source="startup")
    assert record_verdict_for(repo, "local", "/work/acme", "kept") == eid
    assert record_verdict_for(repo, "local", "/work/acme", "noise", note_id="n:1") == eid
    assert [(v["verdict"], v["note_id"]) for v in repo.list_verdicts("local")] == [("kept", None), ("noise", "n:1")]


def test_handoff_verdict_cli(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    root = tmp_path / "acme"; (root / ".git").mkdir(parents=True); monkeypatch.chdir(root)
    r = CliRunner().invoke(cli.app, ["handoff", "--kept"])
    assert r.exit_code == 1 and "no handoff" in r.output.lower()
    repo.record_handoff_event("local", str(root), ["n:1"], chars=10, source="startup")
    r = CliRunner().invoke(cli.app, ["handoff", "--kept"])
    assert r.exit_code == 0 and "kept" in r.output
    r = CliRunner().invoke(cli.app, ["handoff", "--noise", "--note", "n:1"])
    assert r.exit_code == 0
    r = CliRunner().invoke(cli.app, ["handoff"])
    assert r.exit_code != 0                                                   # a verdict is required
    assert len(repo.list_verdicts("local")) == 2


def test_capture_marks_references_on_the_latest_event(repo, tmp_path, monkeypatch):
    from alluvia.engine.engine import Engine
    from alluvia.engine.embed import FakeEmbedder
    from alluvia.hooks import run_capture
    from alluvia.llm.client import FakeLLM
    from tests.test_hooks import _transcript
    monkeypatch.setenv("ALLUVIA_HANDOFF_DIR", str(tmp_path / "handoff"))
    project = tmp_path / "acme"
    transcript = _transcript(tmp_path, project)          # assistant: "Pinned clock skew." + Edit auth/refresh.py
    eid = repo.record_handoff_event("local", str(project), ["n:skew", "n:queue"], chars=10, source="startup")
    from alluvia.models import Note
    repo.upsert_notes([Note(id="n:skew", user_id="local", session_id="claude-code:x", span_ref="msg:0",
                            kind="decision", text="pin clock skew in auth/refresh.py", created_at=None),
                       Note(id="n:queue", user_id="local", session_id="claude-code:x", span_ref="msg:0",
                            kind="decision", text="use postgres for the queue", created_at=None)])
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([{"notes": []}]), min_cluster_size=2)
    run_capture({"transcript_path": str(transcript), "cwd": str(project)}, repo, eng)
    assert repo.latest_handoff_event("local", str(project))["referenced_note_ids"] == ["n:skew"]


def test_recall_counts_answers_and_refusals(repo, monkeypatch):
    from tests.test_recall_ranking import RealisticEmbedder, _seed
    from types import SimpleNamespace
    from alluvia.mcp_server import recall_now_impl
    _seed(repo)
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    monkeypatch.setattr(cli, "_recall_embedder", lambda: RealisticEmbedder())
    CliRunner().invoke(cli.app, ["recall", "auth token refresh race"])
    CliRunner().invoke(cli.app, ["recall", "my grandmother's lasagna recipe"])
    deps = SimpleNamespace(repo=repo, embedder=RealisticEmbedder())
    recall_now_impl(deps, "auth token refresh race")
    recall_now_impl(deps, "sourdough starter")
    assert repo.counters("local") == {"recall_answered": 2, "recall_refused": 2}


def test_stats_shows_the_proof_block(repo, monkeypatch):
    from alluvia.proof import stats_block
    eid = repo.record_handoff_event("local", "/work/acme", ["n:1", "n:2"], chars=10, source="startup")
    repo.set_event_references("local", eid, ["n:1"])
    repo.record_verdict("local", eid, "kept")
    repo.bump_counter("local", "recall_answered", 3)
    repo.bump_counter("local", "recall_refused", 1)
    lines = stats_block(repo, "local")
    assert lines[0] == "handoffs: 1 delivered · 2 lines · kept 1 · noise 0 · referenced (proxy) 1/2"
    assert lines[1] == "recall:   3 answered · 1 said no record"
    assert lines[2] == "forget:   0 notes suppressed"
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    out = CliRunner().invoke(cli.app, ["stats"]).output
    assert "handoffs: 1 delivered" in out and "said no record" in out
