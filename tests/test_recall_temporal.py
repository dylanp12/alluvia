"""Temporal recall: an explicit time expression scopes the search to that
window (honestly empty when nothing is there); without one, freshness only
breaks ties — it never buries a 14-month-old rediscovery."""
from __future__ import annotations
from datetime import datetime, timezone

from alluvia.models import Note
from alluvia.recall import recall

NOW = datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc)   # Wednesday
OLD = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
LAST_TUESDAY = datetime(2026, 8, 11, 9, 0, tzinfo=timezone.utc)
LAST_WEEK = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)


class TopicEmbedder:
    dim = 8

    def embed(self, texts):
        return [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                if ("auth" in t.lower() or "refresh" in t.lower()
                    or "deadlock" in t.lower())
                else [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]
                for t in texts]


def _note(nid, text, created, sid="claude-code:s1"):
    return Note(id=nid, user_id="local", session_id=sid, span_ref="msg:0",
                kind="insight", text=text, created_at=created)


def _seed(repo, notes):
    repo.upsert_notes(notes)
    emb = TopicEmbedder()
    for n in notes:
        repo.set_embedding("local", n.id, emb.embed([n.text])[0])


def test_explicit_window_returns_only_notes_inside_it(repo):
    _seed(repo, [_note("note:old", "auth refresh deadlock (january)", OLD),
                 _note("note:new", "auth refresh deadlock (august)", LAST_TUESDAY)])
    hits = recall(repo, TopicEmbedder(), "local", "auth fix last tuesday", now=NOW)
    cited = {c for h in hits for c in h.cites}
    assert "note:new" in cited and "note:old" not in cited


def test_empty_window_is_honestly_empty(repo):
    _seed(repo, [_note("note:old", "auth refresh deadlock (january)", OLD)])
    assert recall(repo, TopicEmbedder(), "local",
                  "auth deadlock last week", now=NOW) == []


def test_without_a_window_freshness_only_breaks_ties(repo):
    # identical topical strength, no lexical overlap with the query —
    # the fresher note should lead, the older one must still be cited
    _seed(repo, [_note("note:old", "auth refresh deadlock (january)", OLD),
                 _note("note:new", "auth refresh deadlock (august)", LAST_TUESDAY)])
    # "refresh" carries the topic; "troubles" blocks the 2-token lexical
    # threshold, so no lexical hit — the dense tie is all there is
    hits = recall(repo, TopicEmbedder(), "local", "refresh troubles", now=NOW)
    note_hits = [h for h in hits if h.kind == "note"]
    assert note_hits and note_hits[0].cites == ["note:new"]
    assert "note:old" in {c for h in hits for c in h.cites}


def test_undated_notes_are_excluded_from_windows_but_not_from_search(repo):
    _seed(repo, [_note("note:undated", "auth refresh deadlock (undated)", None),
                 _note("note:new", "auth refresh deadlock (august)", LAST_TUESDAY)])
    scoped = recall(repo, TopicEmbedder(), "local", "auth fix last tuesday",
                    now=NOW)
    assert "note:undated" not in {c for h in scoped for c in h.cites}
    unscoped = recall(repo, TopicEmbedder(), "local", "auth deadlock", now=NOW)
    assert "note:undated" in {c for h in unscoped for c in h.cites}


def test_time_words_do_not_pollute_exact_matching(repo):
    _seed(repo, [_note("note:err",
                       "worker pool dies with ECONNREFUSED on cold start",
                       LAST_WEEK)])
    hits = recall(repo, TopicEmbedder(), "local", "ECONNREFUSED last week",
                  now=NOW)
    assert "note:err" in {c for h in hits for c in h.cites}


def test_now_defaults_to_wall_clock(repo):
    _seed(repo, [_note("note:new", "auth refresh deadlock", LAST_TUESDAY)])
    assert isinstance(recall(repo, TopicEmbedder(), "local",
                             "auth fix last tuesday"), list)
