"""Store additions for portable memory and proof of use."""
from alluvia.models import Message, RawSession, content_hash


def _sess(native, project="/work/acme", msgs=("hi",)):
    ms = [Message(role="user", text=t) for t in msgs]
    return RawSession(id=f"claude-code:{native}", user_id="local", source="claude-code",
                      native_id=native, title="t", started_at=None, ended_at=None,
                      messages=ms, content_hash=content_hash(ms), project=project, branch="main")


def test_imported_sessions_carry_origin_and_empty_messages(repo):
    s = _sess("imp", msgs=())
    s.content_hash = "abc"
    repo.upsert_session(s, imported_from="laptop-2")
    got = repo.get_session("local", "claude-code:imp")
    assert got.messages == [] and got.content_hash == "abc"
    assert repo.session_origins("local") == {"claude-code:imp": "laptop-2"}
    assert repo.session_content_hash("local", "claude-code:imp") == "abc"


def test_handoff_events_and_verdicts(repo):
    eid = repo.record_handoff_event("local", "/work/acme", ["n:1", "n:2"], chars=400, source="startup")
    assert eid
    ev = repo.latest_handoff_event("local", "/work/acme")
    assert ev["note_ids"] == ["n:1", "n:2"] and ev["referenced_note_ids"] == []
    repo.record_verdict("local", eid, "kept", note_id=None)
    repo.record_verdict("local", eid, "noise", note_id="n:2")
    assert [v["verdict"] for v in repo.list_verdicts("local")] == ["kept", "noise"]
    repo.set_event_references("local", eid, ["n:1"])
    assert repo.latest_handoff_event("local", "/work/acme")["referenced_note_ids"] == ["n:1"]
    assert repo.latest_handoff_event("local", "/work/other") is None
    assert len(repo.list_handoff_events("local")) == 1


def test_usage_counters(repo):
    repo.bump_counter("local", "recall_refused")
    repo.bump_counter("local", "recall_refused")
    repo.bump_counter("local", "recall_answered")
    assert repo.counters("local") == {"recall_answered": 1, "recall_refused": 2}


def test_new_tables_are_judgments(repo):
    from alluvia.inspect import storage_report
    repo.record_handoff_event("local", "/work/acme", ["n:1"], chars=10, source="startup")
    repo.bump_counter("local", "recall_answered")
    assert storage_report(repo)["data_classes"]["judgments"]["rows"] == 2
