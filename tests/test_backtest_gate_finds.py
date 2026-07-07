"""The M2b gate's known-real discoveries, recreated synthetically: the candidate
picker must surface exactly this material first. If a future change stops
selecting it, these tests fail — the gate's finds are now permanent fixtures."""
from datetime import datetime, timezone
from alluvia.models import Link, Note, Theme
from alluvia.engine.propose import candidates


def _note(nid, source, text, day, month=1, year=2026):
    return Note(id=nid, user_id="local", session_id=f"{source}:s-{nid}",
                span_ref="msg:0", kind="problem", text=text,
                created_at=datetime(year, month, day, tzinfo=timezone.utc))


def test_track_id_style_cross_source_bridge_is_first_candidate(repo):
    # the gate find: 2026 claude-code security note <-> 2025 cursor root-cause note
    repo.upsert_notes([
        _note("note:sec", "claude-code",
              "no cross-check between track_id and artist_id enables forgery", 8, 6),
        _note("note:root", "cursor",
              "metadata service not storing track_id from upload service", 2, 4,
              year=2025),
        _note("note:x", "claude-code", "unrelated lint cleanup", 1),
    ])
    repo.replace_links("local", [
        Link(id="link:gate", user_id="local", from_note_id="note:sec",
             to_note_id="note:root", from_theme_id="t0", to_theme_id="t1",
             kind="cross_source_surprise", weight=2.5),       # strongest
        Link(id="link:weak", user_id="local", from_note_id="note:sec",
             to_note_id="note:x", from_theme_id="t0", to_theme_id="t2",
             kind="cross_source_surprise", weight=0.7),
    ])
    cands = candidates(repo, "local")
    assert cands[0].kind == "link" and cands[0].source_ref == "link:gate"


def test_388_day_open_thread_is_top_theme_candidate(repo):
    repo.upsert_notes([_note("note:t1", "claude-code", "test infra is disorganized", 1,
                             year=2025),
                       _note("note:t2", "claude-code", "quick one-off question", 1)])
    repo.replace_themes("local", [
        Theme(id="th:infra", user_id="local", label="Test Infra", summary="s",
              note_ids=["note:t1"], first_seen=datetime(2025, 4, 15, tzinfo=timezone.utc),
              last_seen=datetime(2026, 5, 8, tzinfo=timezone.utc),   # ~388 days
              session_count=4, source_count=1, status="open"),
        Theme(id="th:oneoff", user_id="local", label="One-off", summary="s",
              note_ids=["note:t2"], session_count=1, source_count=1, status="unknown"),
    ])
    cands = candidates(repo, "local")
    theme_cands = [c for c in cands if c.kind == "theme"]
    assert theme_cands and theme_cands[0].source_ref == "th:infra"
    assert all(c.source_ref != "th:oneoff" for c in cands)      # non-open excluded
