"""The judgment loop: a kept typed finding is PROMOTED — candidate →
confirmed edge + human-confirmed judgment event. A dismissed one just
records the verdict. Predictions never become facts without this step."""
from datetime import datetime, timezone

from alluvia.engine.relate import judge_candidate
from alluvia.llm.client import FakeLLM
from alluvia.engine.relate import type_links
from alluvia.models import Link, Note

NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)


def _note(nid, text):
    return Note(id=nid, user_id="local", session_id=f"claude-code:s-{nid}",
                span_ref="msg:2", kind="decision", text=text,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _seed_typed(repo):
    repo.upsert_notes([_note("note:a", "trust client ids"),
                       _note("note:b", "never trust client ids")])
    repo.replace_links("local", [Link(
        id="link:x", user_id="local", from_note_id="note:a",
        to_note_id="note:b", from_theme_id="t0", to_theme_id="t1",
        kind="cross_source_surprise", weight=2.0)])
    type_links(repo, "local", FakeLLM([{
        "relation": "CONTRADICTS", "confidence": 0.9, "why": "w"}]), now=NOW)
    return "cand:rel:link:x"


def test_keep_promotes_to_edge_and_judgment_event(repo):
    cid = _seed_typed(repo)
    out = judge_candidate(repo, "local", cid, "keep", now=NOW)
    assert out == {"id": cid, "status": "confirmed", "promoted": True}
    assert repo.list_candidates("local")[0]["status"] == "confirmed"
    edges = repo.list_edges("local")
    assert len(edges) == 1
    e = edges[0]
    assert (e["subject_id"], e["relation"], e["object_id"]) == \
        ("note:a", "CONTRADICTS", "note:b")
    assert e["weight"] == 0.9
    events = repo.list_events("local")
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "judgment" and ev["relation"] == "CONTRADICTS"
    assert ev["human_confirmed"] is True
    assert ev["evidence"] == ["claude-code:s-note:a/msg:2",
                               "claude-code:s-note:b/msg:2"]
    assert e["event_id"] == ev["id"]


def test_dismiss_records_without_promotion(repo):
    cid = _seed_typed(repo)
    out = judge_candidate(repo, "local", cid, "dismiss", now=NOW)
    assert out == {"id": cid, "status": "dismissed", "promoted": False}
    assert repo.list_edges("local") == [] and repo.list_events("local") == []


def test_unknown_candidate_errors_as_value(repo):
    out = judge_candidate(repo, "local", "cand:rel:nope", "keep", now=NOW)
    assert "error" in out


def test_bad_verdict_errors_as_value(repo):
    cid = _seed_typed(repo)
    assert "error" in judge_candidate(repo, "local", cid, "maybe", now=NOW)


def test_re_keep_is_idempotent(repo):
    cid = _seed_typed(repo)
    judge_candidate(repo, "local", cid, "keep", now=NOW)
    out = judge_candidate(repo, "local", cid, "keep", now=NOW)
    assert out["status"] == "confirmed"
    assert len(repo.list_edges("local")) == 1
    assert len(repo.list_events("local")) == 1
