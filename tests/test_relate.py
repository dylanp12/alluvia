"""Typed-relation pass: surprise links get classified into directional,
evidence-bearing relation candidates. Predictions land in the candidates
store — never asserted as facts."""
from datetime import datetime, timezone

from alluvia.engine.relate import RELATIONS, type_links
from alluvia.llm.client import FakeLLM
from alluvia.models import Link, Note

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _note(nid, text):
    return Note(id=nid, user_id="local", session_id=f"claude-code:s-{nid}",
                span_ref="msg:2", kind="decision", text=text,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _seed(repo):
    repo.upsert_notes([_note("note:a", "trust client ids for uploads"),
                       _note("note:b", "never trust client-supplied ids")])
    repo.replace_links("local", [Link(
        id="link:x", user_id="local", from_note_id="note:a",
        to_note_id="note:b", from_theme_id="t0", to_theme_id="t1",
        kind="cross_source_surprise", weight=2.0)])


def test_typed_relation_stored_with_evidence(repo):
    _seed(repo)
    llm = FakeLLM([{"relation": "CONTRADICTS", "confidence": 0.9,
                     "why": "B forbids what A assumes"}])
    stats = type_links(repo, "local", llm, now=NOW)
    assert stats == {"examined": 1, "typed": 1, "skipped": 0, "errors": 0}
    cands = repo.list_candidates("local", status="pending")
    assert len(cands) == 1
    c = cands[0]
    assert c["relation"] == "CONTRADICTS"
    assert c["subject_id"] == "note:a" and c["object_id"] == "note:b"
    assert c["score"] == 0.9
    assert c["why"] == "B forbids what A assumes"
    assert c["evidence"] == ["claude-code:s-note:a/msg:2",
                              "claude-code:s-note:b/msg:2"]
    assert c["policy_version"] == "relate-v1"
    assert c["created_at"] == NOW.isoformat()


def test_none_relation_stores_nothing(repo):
    _seed(repo)
    llm = FakeLLM([{"relation": "NONE", "confidence": 0.2, "why": "unrelated"}])
    stats = type_links(repo, "local", llm, now=NOW)
    assert stats["typed"] == 0 and stats["skipped"] == 1
    assert repo.list_candidates("local") == []


def test_second_run_dedupes(repo):
    _seed(repo)
    llm = FakeLLM([{"relation": "SUPERSEDES", "confidence": 0.8, "why": "w"}])
    type_links(repo, "local", llm, now=NOW)
    stats = type_links(repo, "local", FakeLLM([]), now=NOW)   # no LLM calls left
    assert stats["examined"] == 0
    assert len(repo.list_candidates("local")) == 1


def test_bad_payloads_counted_never_raised(repo):
    _seed(repo)
    llm = FakeLLM(["not a dict"])
    stats = type_links(repo, "local", llm, now=NOW)
    assert stats == {"examined": 1, "typed": 0, "skipped": 0, "errors": 1}
    assert repo.list_candidates("local") == []
    assert set(RELATIONS) == {"CONTRADICTS", "SUPERSEDES", "ADDRESSES",
                               "RECURS_AS", "TRANSFERS_TO"}


def test_transfers_to_is_typed(repo):
    _seed(repo)
    llm = FakeLLM([{"relation": "TRANSFERS_TO", "confidence": 0.75,
                     "why": "same invariant, different project"}])
    stats = type_links(repo, "local", llm, now=NOW)
    assert stats["typed"] == 1
    assert repo.list_candidates("local")[0]["relation"] == "TRANSFERS_TO"


def test_engine_wires_the_relate_role(repo):
    from alluvia.engine.engine import Engine

    class _NullEmbedder:
        def embed(self, texts):
            return [[0.0] * 8 for _ in texts]

    _seed(repo)
    eng = Engine(repo, _NullEmbedder(),
                 FakeLLM([{"relation": "ADDRESSES", "confidence": 0.7,
                            "why": "w"}]))
    stats = eng.type_top_links("local", now=NOW)
    assert stats["typed"] == 1
    assert repo.list_candidates("local")[0]["relation"] == "ADDRESSES"
