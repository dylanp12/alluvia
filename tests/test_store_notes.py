from alluvia.models import Note


def _note(nid, user="local", text="t"):
    return Note(id=nid, user_id=user, session_id="claude-code:s1", span_ref="msg:0",
                kind="idea", text=text, created_at=None)


def test_notes_upsert_and_scope(repo):
    repo.upsert_notes([_note("note:a"), _note("note:b")])
    repo.upsert_notes([_note("note:c", user="other")])
    ids = {n.id for n in repo.get_notes("local")}
    assert ids == {"note:a", "note:b"}
    assert repo.session_ids_with_notes("local") == {"claude-code:s1"}


def test_embeddings_roundtrip_and_search(repo):
    repo.upsert_notes([_note("note:a", text="alpha"), _note("note:b", text="beta")])
    repo.set_embedding("local", "note:a", [1.0, 0.0] + [0.0] * 6)
    repo.set_embedding("local", "note:b", [0.0, 1.0] + [0.0] * 6)
    assert repo.note_ids_with_embeddings("local") == {"note:a", "note:b"}
    hits = repo.search_notes("local", [0.9, 0.1] + [0.0] * 6, k=1)
    assert hits[0][0] == "note:a"
