"""The block injected at session start: what is true for THIS repo, from
distilled notes only, each line traceable to a session. Nothing → None."""
from datetime import datetime, timezone

import pytest

from alluvia.handoff import (
    build_project_handoff, build_project_handoff_struct,
    build_project_handoff_with_ids, render_handoff,
)
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


def test_structure_and_text_are_one_thing(repo):
    """The app renders the structure; the plugin injects the text. They must
    never disagree, so the text is rendered from the structure."""
    from alluvia.handoff import build_project_handoff_struct, build_project_handoff_with_ids, render_handoff
    _seed(repo)
    s = build_project_handoff_struct(repo, "local", "/work/acme")
    assert s["project"] == "acme" and s["head"].startswith("last session")
    assert [i["note_kind"] for i in s["last"]][:1] == ["decision"]
    assert all(i["session_native"] for i in s["last"] + s["earlier"])
    assert s["open"] and s["open"][0]["label"] == "Auth token lifecycle"
    assert s["footer"][0].endswith("in this repo")
    assert render_handoff(s) == build_project_handoff(repo, "local", "/work/acme")
    assert s["shown"] == build_project_handoff_with_ids(repo, "local", "/work/acme")[1]


def test_earlier_decisions_choose_recent_sessions_before_message_positions(repo):
    _seed(repo)
    middle = datetime(2026, 8, 15, tzinfo=timezone.utc)
    recent = datetime(2026, 8, 25, tzinfo=timezone.utc)
    repo.upsert_session(_sess("middle", "/work/acme", middle))
    repo.upsert_session(_sess("recent", "/work/acme", recent))
    repo.upsert_notes([
        Note(id=f"n:old-{i}", user_id="local", session_id="claude-code:old1",
             span_ref=f"msg:{900 + i}", kind="decision", text=f"older decision {i}", created_at=T0)
        for i in range(3)
    ] + [
        Note(id="n:middle", user_id="local", session_id="claude-code:middle", span_ref="msg:50",
             kind="decision", text="middle decision", created_at=middle),
        Note(id="n:recent-early", user_id="local", session_id="claude-code:recent", span_ref="msg:1",
             kind="decision", text="aaa recent earlier message", created_at=recent),
        Note(id="n:recent-late", user_id="local", session_id="claude-code:recent", span_ref="msg:2",
             kind="decision", text="zzz recent later message", created_at=recent),
    ])

    structure = build_project_handoff_struct(repo, "local", "/work/acme")

    assert [item["id"] for item in structure["earlier"]] == [
        "n:recent-late", "n:recent-early", "n:middle",
    ]
    assert "older decision" not in render_handoff(structure)
    assert "postgres" not in render_handoff(structure)


def test_session_timestamp_ties_use_session_ids_before_message_positions(repo):
    for native in ("tie-c", "tie-a", "tie-b", "tie-d"):
        repo.upsert_session(_sess(native, "/work/acme", T1))
    repo.upsert_notes([
        Note(id=f"n:{native}", user_id="local", session_id=f"claude-code:{native}",
             span_ref=f"msg:{position}", kind="decision", text=native, created_at=T1)
        for native, position in (("tie-a", 900), ("tie-b", 50), ("tie-c", 1), ("tie-d", 0))
    ])

    structure = build_project_handoff_struct(repo, "local", "/work/acme")

    assert [item["id"] for item in structure["last"]] == ["n:tie-d"]
    assert [item["id"] for item in structure["earlier"]] == ["n:tie-c", "n:tie-b", "n:tie-a"]


@pytest.mark.parametrize("max_chars", [0, 1, 2, 30])
def test_tiny_handoff_limits_never_claim_note_ids_or_exceed_the_budget(repo, max_chars):
    _seed(repo)

    text, ids = build_project_handoff_with_ids(repo, "local", "/work/acme", max_chars=max_chars)

    assert len(text) <= max_chars
    assert ids == []
    assert text == ("…" if max_chars else "")


@pytest.mark.parametrize("max_chars, expected_ids", [
    (180, ["n:new-dec"]),
    (240, ["n:new-dec", "n:new-prob"]),
    (1500, ["n:new-dec", "n:new-prob", "n:old-dec"]),
])
def test_handoff_ids_only_include_complete_visible_note_lines(repo, max_chars, expected_ids):
    _seed(repo)
    note_lines = {
        "n:new-dec": "- [decision] pin clock skew in auth/refresh.py (session new1)",
        "n:new-prob": "- [problem] two tabs still race on rotation (session new1)",
        "n:old-dec": "- rotate refresh tokens server-side (session old1)",
    }

    text, ids = build_project_handoff_with_ids(repo, "local", "/work/acme", max_chars=max_chars)

    assert ids == expected_ids
    assert len(text) <= max_chars
    for note_id, line in note_lines.items():
        assert (line in text.splitlines()) == (note_id in ids)
    assert text == render_handoff(build_project_handoff_struct(repo, "local", "/work/acme"), max_chars)


def test_identical_note_lines_do_not_count_a_truncated_duplicate(repo):
    repo.upsert_session(_sess("solo", "/work/acme", T1))
    repo.upsert_notes([
        Note(id=note_id, user_id="local", session_id="claude-code:solo", span_ref="msg:1",
             kind="decision", text="same decision", created_at=T1)
        for note_id in ("n:second", "n:first")
    ])

    text, ids = build_project_handoff_with_ids(repo, "local", "/work/acme", max_chars=150)

    assert text.splitlines().count("- [decision] same decision (session solo)") == 1
    assert ids == ["n:first"]


def test_default_budget_does_not_claim_notes_after_an_oversized_topic(repo):
    _seed(repo)
    repo.replace_themes("local", [
        Theme(id="theme:long", user_id="local", label="long topic " * 150,
              summary="", note_ids=["n:new-dec"], session_count=1, source_count=1, status="open"),
    ])

    text, ids = build_project_handoff_with_ids(repo, "local", "/work/acme")

    assert len(text) <= 1500
    assert ids == ["n:new-dec", "n:new-prob"]
    assert "rotate refresh tokens server-side" not in text


@pytest.mark.parametrize("spare_chars, expected_ids", [(1, []), (2, ["n:new-dec"])])
def test_note_line_requires_room_for_the_truncation_marker(repo, spare_chars, expected_ids):
    _seed(repo)
    prefix = (
        "alluvia · prior context for this repo (acme)\n"
        "last session 2026-09-01 on feat/rotation:\n"
        "- [decision] pin clock skew in auth/refresh.py (session new1)"
    )
    max_chars = len(prefix) + spare_chars

    text, ids = build_project_handoff_with_ids(repo, "local", "/work/acme", max_chars=max_chars)

    assert len(text) <= max_chars
    assert ids == expected_ids
    assert (text == prefix + "\n…") == bool(expected_ids)


def test_capped_note_text_still_counts_when_its_complete_line_and_source_fit(repo):
    repo.upsert_session(_sess("solo", "/work/acme", T1))
    repo.upsert_notes([
        Note(id="n:long", user_id="local", session_id="claude-code:solo", span_ref="msg:1",
             kind="decision", text="a" * 200, created_at=T1),
    ])

    text, ids = build_project_handoff_with_ids(repo, "local", "/work/acme", max_chars=300)

    assert "- [decision] " + "a" * 139 + "… (session solo)" in text.splitlines()
    assert ids == ["n:long"]
