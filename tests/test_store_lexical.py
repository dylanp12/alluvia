"""Lexical note search: the exact-match channel of hybrid recall.

Dense embeddings miss the queries developers actually paste — error strings,
file paths, snake_case identifiers. The store answers those with FTS5.
"""
from __future__ import annotations
from datetime import datetime

from alluvia.models import Note

BASE = datetime(2026, 1, 1)


def _note(nid: str, text: str, user: str = "local") -> Note:
    return Note(id=nid, user_id=user, session_id="claude-code:s1",
                span_ref="msg:0", kind="insight", text=text, created_at=BASE)


def test_finds_exact_error_string(repo):
    repo.upsert_notes([
        _note("note:e1", "worker pool dies with ECONNREFUSED 127.0.0.1:5432 on cold start"),
        _note("note:x1", "deploy pipeline caching layer"),
    ])
    hits = repo.search_notes_lexical("local", "ECONNREFUSED", k=5)
    assert [h[0] for h in hits] == ["note:e1"]


def test_finds_snake_case_identifier_case_insensitively(repo):
    repo.upsert_notes([
        _note("note:c1", "force-honor DATABASE_URL over the config default"),
        _note("note:x1", "database migrations run twice"),
    ])
    hits = repo.search_notes_lexical("local", "database_url", k=5)
    assert hits and hits[0][0] == "note:c1"
    # the plain word must not outrank the exact identifier
    assert "note:x1" not in [h[0] for h in hits[:1]]


def test_finds_file_path_by_its_segments(repo):
    repo.upsert_notes([
        _note("note:p1", "fixed the rotation race in auth/refresh.py with a lock"),
        _note("note:x1", "landing page hero copy"),
    ])
    hits = repo.search_notes_lexical("local", "refresh.py", k=5)
    assert [h[0] for h in hits] == ["note:p1"]


def test_results_are_scoped_to_the_user(repo):
    repo.upsert_notes([
        _note("note:mine", "ECONNREFUSED in the worker", user="local"),
        _note("note:theirs", "ECONNREFUSED in the worker", user="other"),
    ])
    hits = repo.search_notes_lexical("local", "ECONNREFUSED", k=5)
    assert [h[0] for h in hits] == ["note:mine"]


def test_upserted_text_replaces_the_old_index_entry(repo):
    repo.upsert_notes([_note("note:u1", "alpha_marker_one is the culprit")])
    assert repo.search_notes_lexical("local", "alpha_marker_one", k=5)
    repo.upsert_notes([_note("note:u1", "beta_marker_two is the culprit")])
    assert repo.search_notes_lexical("local", "alpha_marker_one", k=5) == []
    assert [h[0] for h in repo.search_notes_lexical("local", "beta_marker_two", k=5)] \
        == ["note:u1"]


def test_survives_fts_query_syntax_in_user_queries(repo):
    repo.upsert_notes([_note("note:s1", "quoted star dash paren survivors")])
    # none of these may raise: FTS5 operators arrive quoted/stripped, not parsed
    for q in ('"quoted" AND (paren)', "star* NEAR dash", "-dash OR ^caret", "()"):
        repo.search_notes_lexical("local", q, k=5)
    assert [h[0] for h in repo.search_notes_lexical("local", 'the "quoted" star', k=5)] \
        == ["note:s1"]


def test_backfills_notes_written_before_the_index_existed(repo):
    """Legacy stores: notes rows exist, notes_fts is empty — first lexical
    search rebuilds the index instead of silently returning nothing."""
    repo.upsert_notes([_note("note:b1", "legacy ECONNREFUSED note")])
    repo.conn.execute("DELETE FROM notes_fts")          # simulate a pre-FTS store
    repo.conn.commit()
    hits = repo.search_notes_lexical("local", "ECONNREFUSED", k=5)
    assert [h[0] for h in hits] == ["note:b1"]
