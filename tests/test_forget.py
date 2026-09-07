from datetime import datetime
from alluvia.models import Note
from alluvia.recall import recall
from tests.test_recall_ranking import RealisticEmbedder

BASE = datetime(2026, 1, 1)


def test_suppressed_notes_never_come_back(repo):
    notes = [Note(id="note:good", user_id="local", session_id="claude-code:s", span_ref="msg:0",
                  kind="decision", text="auth token rotation lock added", created_at=BASE),
             Note(id="note:wrong", user_id="local", session_id="claude-code:s", span_ref="msg:1",
                  kind="decision", text="auth tokens live forever", created_at=BASE)]
    repo.upsert_notes(notes)
    emb = RealisticEmbedder()
    for n in notes:
        repo.set_embedding("local", n.id, emb.embed([n.text])[0])
    repo.suppress_note("local", "note:wrong", reason="distilled a hypothetical as a decision")
    assert repo.suppressed_note_ids("local") == {"note:wrong"}
    cited = {c for h in recall(repo, emb, "local", "auth token") for c in h.cites}
    assert cited == {"note:good"}
    repo.unsuppress_note("local", "note:wrong")
    assert repo.suppressed_note_ids("local") == set()


def test_suppressions_are_judgments(repo):
    from alluvia.inspect import storage_report
    repo.upsert_notes([Note(id="note:x", user_id="local", session_id="claude-code:s",
                            span_ref="msg:0", kind="idea", text="x", created_at=BASE)])
    repo.suppress_note("local", "note:x", reason="wrong")
    assert storage_report(repo)["data_classes"]["judgments"]["rows"] == 1
