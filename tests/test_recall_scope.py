from datetime import datetime
from alluvia.models import Message, Note, RawSession, content_hash
from alluvia.recall import recall
from tests.test_recall_ranking import RealisticEmbedder

BASE = datetime(2026, 1, 1)


def _sess(native, project):
    msgs = [Message(role="user", text="auth token work")]
    return RawSession(id=f"claude-code:{native}", user_id="local", source="claude-code",
                      native_id=native, title="t", started_at=BASE, ended_at=BASE,
                      messages=msgs, content_hash=content_hash(msgs), project=project)


def test_project_scope_hides_other_repos(repo):
    repo.upsert_session(_sess("a", "/work/acme"))
    repo.upsert_session(_sess("b", "/work/other"))
    notes = [Note(id="note:a", user_id="local", session_id="claude-code:a", span_ref="msg:0",
                  kind="decision", text="auth token rotation lock added", created_at=BASE),
             Note(id="note:b", user_id="local", session_id="claude-code:b", span_ref="msg:0",
                  kind="decision", text="auth token refresh handled by proxy", created_at=BASE)]
    repo.upsert_notes(notes)
    emb = RealisticEmbedder()
    for n in notes:
        repo.set_embedding("local", n.id, emb.embed([n.text])[0])
    everywhere = {c for h in recall(repo, emb, "local", "auth token") for c in h.cites}
    here = {c for h in recall(repo, emb, "local", "auth token", project="/work/acme") for c in h.cites}
    assert everywhere == {"note:a", "note:b"} and here == {"note:a"}
