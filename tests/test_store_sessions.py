from alluvia.models import RawSession, Message, session_id, content_hash


def _session(user="local", native="s1", text="hi"):
    msgs = [Message(role="user", text=text)]
    return RawSession(
        id=session_id("claude-code", native), user_id=user, source="claude-code",
        native_id=native, title="t", started_at=None, ended_at=None,
        messages=msgs, content_hash=content_hash(msgs),
    )


def test_upsert_is_idempotent_on_content_hash(repo):
    s = _session()
    assert repo.upsert_session(s) is True     # inserted
    assert repo.upsert_session(s) is False    # unchanged -> no-op
    assert len(repo.list_sessions("local")) == 1


def test_changed_content_updates_and_reports_true(repo):
    repo.upsert_session(_session(text="hi"))
    assert repo.upsert_session(_session(text="different")) is True
    got = repo.get_session("local", "claude-code:s1")
    assert got.messages[0].text == "different"


def test_user_isolation(repo):
    repo.upsert_session(_session(user="a", native="x"))
    repo.upsert_session(_session(user="b", native="y"))
    assert [s.native_id for s in repo.list_sessions("a")] == ["x"]
    assert repo.get_session("a", "claude-code:y") is None


def test_session_project_and_branch_round_trip(repo):
    s = _session(native="p1")
    s.project = "/work/acme"
    s.branch = "feat/x"
    repo.upsert_session(s)
    got = repo.get_session("local", "claude-code:p1")
    assert got.project == "/work/acme" and got.branch == "feat/x"
    # legacy rows (no project) read back as None, never crash
    repo.upsert_session(_session(native="legacy"))
    assert repo.get_session("local", "claude-code:legacy").project is None


def test_session_meta_and_projects_do_not_load_messages(repo):
    a = _session(native="a", text="alpha"); a.project = "/work/acme"
    b = _session(native="b", text="beta");  b.project = "/work/other"
    repo.upsert_session(a); repo.upsert_session(b)
    meta = repo.list_session_meta("local", project="/work/acme")
    assert [m["id"] for m in meta] == ["claude-code:a"]
    assert set(meta[0]) >= {"id", "title", "started_at", "ended_at", "project", "branch"}
    assert repo.session_projects("local") == {"claude-code:a": "/work/acme",
                                              "claude-code:b": "/work/other"}


def test_changed_raw_content_drops_that_sessions_derived_notes(repo):
    """Derived is rebuildable from raw. When a session's raw content changes
    (a better adapter, a live transcript that grew), notes distilled from the
    OLD content are invalid: gone with their vectors and marker, so the next
    pass distills fresh and 'no record' beats a stale one. Unchanged upserts
    leave everything alone."""
    from alluvia.models import Note
    repo.upsert_session(_session(native="s1", text="first version"))
    repo.upsert_notes([Note(id="note:old", user_id="local", session_id="claude-code:s1",
                            span_ref="msg:0", kind="idea", text="stale", created_at=None)])
    repo.set_embedding("local", "note:old", [1.0] + [0.0] * 7)
    repo.mark_distilled("local", "claude-code:s1")
    assert repo.upsert_session(_session(native="s1", text="first version")) is False
    assert [n.id for n in repo.get_notes("local")] == ["note:old"]          # unchanged: kept
    assert repo.upsert_session(_session(native="s1", text="second version")) is True
    assert repo.get_notes("local") == []
    assert repo.note_ids_with_embeddings("local") == set()
    assert repo.distilled_session_ids("local") == set()
    assert repo.distill_coverage("local")["pending"] == 1
