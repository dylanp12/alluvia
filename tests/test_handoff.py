"""The block injected at session start: what is true for THIS repo, from
distilled notes only, each line traceable to a session. Nothing → None."""
from datetime import datetime, timezone
from alluvia.handoff import build_project_handoff
from alluvia.models import Message, Note, RawSession, Theme, content_hash

T0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _sess(native, project, when, branch="main"):
    msgs = [Message(role="user", text="work")]
    return RawSession(id=f"claude-code:{native}", user_id="local", source="claude-code",
                      native_id=native, title="t", started_at=when, ended_at=when,
                      messages=msgs, content_hash=content_hash(msgs), project=project, branch=branch)


def _seed(repo):
    repo.upsert_session(_sess("old1", "/work/acme", T0))
    repo.upsert_session(_sess("new1", "/work/acme", T1, branch="feat/rotation"))
    repo.upsert_session(_sess("other", "/work/other", T1))
    notes = [
        Note(id="n:old-dec", user_id="local", session_id="claude-code:old1", span_ref="msg:0",
             kind="decision", text="rotate refresh tokens server-side", created_at=T0),
        Note(id="n:new-dec", user_id="local", session_id="claude-code:new1", span_ref="msg:0",
             kind="decision", text="pin clock skew in auth/refresh.py", created_at=T1),
        Note(id="n:new-prob", user_id="local", session_id="claude-code:new1", span_ref="msg:0",
             kind="problem", text="two tabs still race on rotation", created_at=T1),
        Note(id="n:other", user_id="local", session_id="claude-code:other", span_ref="msg:0",
             kind="decision", text="use postgres for the other app", created_at=T1),
    ]
    repo.upsert_notes(notes)
    for s in ("old1", "new1", "other"):
        repo.mark_distilled("local", f"claude-code:{s}")
    repo.replace_themes("local", [Theme(id="theme:auth", user_id="local", label="Auth token lifecycle",
                                        summary="", note_ids=["n:old-dec", "n:new-dec", "n:new-prob"],
                                        session_count=2, source_count=1, status="open")])


def test_handoff_is_scoped_recent_first_and_cited(repo):
    _seed(repo)
    text = build_project_handoff(repo, "local", "/work/acme", now=T1)
    assert text.startswith("alluvia · prior context for this repo (acme)")
    assert "last session 2026-09-01 on feat/rotation" in text
    assert "[decision] pin clock skew in auth/refresh.py" in text
    assert "[problem] two tabs still race on rotation" in text
    assert "open here: Auth token lifecycle" in text
    assert "earlier decisions here" in text and "rotate refresh tokens server-side" in text
    assert "session new1" in text                         # every line has its receipt
    assert "postgres" not in text                         # other repo never leaks in
    assert "verify against the code" in text
    assert len(text) <= 1500


def test_handoff_is_none_when_nothing_is_known(repo):
    assert build_project_handoff(repo, "local", "/work/empty") is None


def test_handoff_reports_pending_sessions_honestly(repo):
    _seed(repo)
    repo.upsert_session(_sess("pending", "/work/acme", T1))      # ingested, not distilled
    text = build_project_handoff(repo, "local", "/work/acme", now=T1)
    assert "1 session not yet distilled" in text and "alluvia refresh" in text


def test_suppressed_notes_are_left_out(repo):
    _seed(repo)
    repo.suppress_note("local", "n:new-dec", reason="wrong")
    assert "pin clock skew" not in build_project_handoff(repo, "local", "/work/acme", now=T1)


def test_last_session_lines_lead_with_the_latest_decisions(repo):
    """Within the last session, later messages carry the settled view: the
    decision made at msg 40 outranks the one made at msg 3."""
    _seed(repo)
    from alluvia.models import Note
    repo.upsert_notes([
        Note(id="n:late", user_id="local", session_id="claude-code:new1", span_ref="msg:40",
             kind="decision", text="zzz final call: rotate refresh tokens hourly", created_at=T1),
        Note(id="n:early", user_id="local", session_id="claude-code:new1", span_ref="msg:3",
             kind="decision", text="aaa first thought: rotate daily", created_at=T1),
    ])
    text = build_project_handoff(repo, "local", "/work/acme", now=T1)
    lines = [l for l in text.splitlines() if l.startswith("- [decision]")]
    assert lines[0].startswith("- [decision] zzz final call")
    assert lines[1].startswith("- [decision] pin clock skew") or lines[1].startswith("- [decision] aaa")


def test_handoff_returns_its_note_ids_and_asks_for_a_verdict(repo):
    from alluvia.handoff import build_project_handoff_with_ids
    _seed(repo)
    text, ids = build_project_handoff_with_ids(repo, "local", "/work/acme", now=T1)
    assert set(ids) >= {"n:new-dec", "n:new-prob", "n:old-dec"}
    assert "n:other" not in ids
    assert "useful? alluvia handoff --kept" in text and "--noise" in text
    assert build_project_handoff_with_ids(repo, "local", "/work/empty") == (None, [])


def test_footer_counts_sessions_grammatically(repo):
    _seed(repo)
    repo.upsert_session(_sess("solo", "/work/solo", T1))
    from alluvia.models import Note
    repo.upsert_notes([Note(id="n:solo", user_id="local", session_id="claude-code:solo", span_ref="msg:0",
                            kind="decision", text="one thing", created_at=T1)])
    repo.mark_distilled("local", "claude-code:solo")
    assert "1 session in this repo" in build_project_handoff(repo, "local", "/work/solo", now=T1)
    assert "2 sessions in this repo" in build_project_handoff(repo, "local", "/work/acme", now=T1)
