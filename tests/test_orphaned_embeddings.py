from alluvia.models import Note
from alluvia.engine.engine import Engine
from alluvia.engine.embed import FakeEmbedder
from alluvia.llm.client import FakeLLM


def test_build_links_survives_orphaned_embeddings(repo):
    # a real note with an embedding + an orphaned embedding whose note was purged
    repo.upsert_notes([Note(id="note:real", user_id="local", session_id="claude-code:s",
                            span_ref="", kind="idea", text="real", created_at=None)])
    repo.set_embedding("local", "note:real", [1.0, 0.0] + [0.0] * 6)
    repo.set_embedding("local", "note:ghost", [0.9, 0.1] + [0.0] * 6)   # no note row
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2)
    eng._build_links("local")                       # must not raise
    assert all(l.from_note_id != "note:ghost" and l.to_note_id != "note:ghost"
               for l in repo.list_links("local"))
