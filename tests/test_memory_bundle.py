"""Portable memory: derived + judgments, never raw; idempotent merge."""
import json
from alluvia.engine.embed import FakeEmbedder
from alluvia.engine.engine import Engine, pending_distill
from alluvia.llm.client import FakeLLM
from alluvia.memory_bundle import export_bundle, import_bundle
from alluvia.models import Message, Note, RawSession, content_hash
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo


def _seed(repo):
    ms = [Message(role="user", text="rotate the refresh token")]
    repo.upsert_session(RawSession(id="claude-code:s1", user_id="local", source="claude-code",
                                   native_id="s1", title="t", started_at=None, ended_at=None,
                                   messages=ms, content_hash=content_hash(ms),
                                   project="/work/acme", branch="main"))
    repo.upsert_notes([Note(id="n:a", user_id="local", session_id="claude-code:s1", span_ref="msg:0",
                            kind="decision", text="rotate refresh tokens server-side", created_at=None),
                       Note(id="n:secret", user_id="local", session_id="claude-code:s1", span_ref="msg:0",
                            kind="insight", text="key sk-ant-TESTKEYTESTKEY0123456789 works", created_at=None),
                       Note(id="n:wrong", user_id="local", session_id="claude-code:s1", span_ref="msg:0",
                            kind="idea", text="tokens live forever", created_at=None)])
    repo.mark_distilled("local", "claude-code:s1")
    repo.suppress_note("local", "n:wrong", reason="wrong")
    repo.mute_label("local", "Noise")


def _other(tmp_path):
    other = Repo(connect(str(tmp_path / "o.db"))); init_schema(other.conn, embed_dim=8)
    return other


def test_export_has_no_raw_no_secrets_no_suppressed(repo):
    _seed(repo)
    recs = list(export_bundle(repo, "local"))
    assert recs[0]["kind"] == "header" and recs[0]["format"] == "alluvia-memory"
    assert "rotate the refresh token" not in json.dumps(recs)          # raw message text never leaves
    assert not any(r.get("id") == "n:wrong" for r in recs if r["kind"] == "note")
    assert any("[REDACTED]" in r["text"] for r in recs if r["kind"] == "note")
    assert {r["kind"] for r in recs} == {"header", "session", "note", "suppressed", "muted"}
    assert "title" not in [k for r in recs if r["kind"] == "session" for k in r]


def test_import_into_empty_store_is_idempotent_and_never_distills(repo, tmp_path):
    _seed(repo)
    recs = list(export_bundle(repo, "local"))
    other = _other(tmp_path)
    r1 = import_bundle(other, "local", recs, embedder=FakeEmbedder(dim=8))
    assert r1 == {"sessions_added": 1, "notes_added": 2, "notes_present": 0,
                  "judgments_added": 2, "skipped": 0}
    assert other.get_session("local", "claude-code:s1").messages == []
    assert other.session_origins("local")["claude-code:s1"]
    assert other.distill_coverage("local") == {"sessions": 1, "distilled": 1, "pending": 0}
    assert pending_distill(other, "local") == []                         # never sent to the LLM
    assert other.note_ids_with_embeddings("local") == {"n:a", "n:secret"}
    assert other.suppressed_note_ids("local") == {"n:wrong"} and other.muted_labels("local") == {"noise"}
    r2 = import_bundle(other, "local", recs, embedder=FakeEmbedder(dim=8))
    assert r2["notes_added"] == 0 and r2["notes_present"] == 2 and r2["sessions_added"] == 0
    eng = Engine(other, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2)
    eng.refresh("local")                                                 # no LLM call, no note loss
    assert {n.id for n in other.get_notes("local")} == {"n:a", "n:secret"}
    assert eng.distill_session("local", "claude-code:s1", force=True) != [] or \
        {n.id for n in other.get_notes("local")} == {"n:a", "n:secret"}   # forcing an import is a no-op


def test_local_raw_wins_over_an_import(repo):
    _seed(repo)
    recs = list(export_bundle(repo, "local"))
    before = repo.get_session("local", "claude-code:s1")
    import_bundle(repo, "local", recs, embedder=FakeEmbedder(dim=8))
    after = repo.get_session("local", "claude-code:s1")
    assert after.messages == before.messages and repo.session_origins("local") == {}


def test_project_relative_export_binds_to_the_importers_root(repo, tmp_path):
    _seed(repo)
    recs = list(export_bundle(repo, "local", project="/work/acme", project_relative=True))
    assert all(r.get("project") is None and r.get("project_rel") == "." for r in recs if r["kind"] == "session")
    other = _other(tmp_path)
    import_bundle(other, "local", recs, embedder=None, bind_project="/home/x/acme")
    assert other.session_projects("local") == {"claude-code:s1": "/home/x/acme"}
    assert other.note_ids_with_embeddings("local") == set()               # embedder None: SQLite only


def test_malformed_records_are_skipped_not_fatal(repo):
    recs = [{"kind": "header", "format": "alluvia-memory", "version": 1, "origin": "x", "pipeline_version": 3},
            {"kind": "note"}, {"nonsense": True}, "not even a dict"]
    out = import_bundle(repo, "local", recs, embedder=None)
    assert out["skipped"] == 3 and out["notes_added"] == 0


def test_a_retracted_suppression_unsuppresses_locally(repo):
    """A forget undone in the app must be undone on every machine: the
    importer applies a retracted suppression; a 0.9.1-shaped record still
    suppresses."""
    _seed(repo)
    assert "n:wrong" in repo.suppressed_note_ids("local")
    out = import_bundle(repo, "local", [
        {"kind": "suppressed", "note_id": "n:wrong", "reason": "wrong", "retracted": True,
         "retracted_at": "2026-09-08T10:00:00+00:00"},
        {"kind": "suppressed", "note_id": "n:never", "retracted": True}])       # never suppressed here: no-op
    assert "n:wrong" not in repo.suppressed_note_ids("local")
    assert out["judgments_added"] == 1 and out["skipped"] == 0
    import_bundle(repo, "local", [{"kind": "suppressed", "note_id": "n:wrong", "reason": "wrong again"}])
    assert "n:wrong" in repo.suppressed_note_ids("local")


def test_header_carries_backlog_and_version(repo):
    """The app's backlog trigger needs to know how many sessions wait on this
    machine; the header is the only place a push says so."""
    _seed(repo)
    head = next(export_bundle(repo, "local", extra={"pending_sessions": 1}))
    assert head["kind"] == "header" and head["pending_sessions"] == 1 and head["cli_version"]
