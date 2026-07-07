from datetime import datetime, timezone
from alluvia.models import Note, Theme
from alluvia.engine.engine import Engine
from alluvia.engine.embed import FakeEmbedder
from alluvia.llm.client import FakeLLM


def _theme(tid, label, status="open"):
    return Theme(id=tid, user_id="local", label=label, summary="s",
                 note_ids=["note:1"],
                 first_seen=datetime(2025, 1, 1, tzinfo=timezone.utc),
                 last_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
                 session_count=3, source_count=1, status=status)


def _seed(repo):
    repo.upsert_notes([Note(id="note:1", user_id="local", session_id="claude-code:s",
                            span_ref="msg:0", kind="idea", text="meta chatter",
                            created_at=None)])
    repo.replace_themes("local", [_theme("t1", "Autonomous Work"),
                                  _theme("t2", "Real Work")])


def test_mute_hides_from_unfinished_and_candidates_and_recall(repo):
    _seed(repo)
    repo.mute_label("local", "Autonomous Work")
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2)
    assert [t.label for t in eng.unfinished("local")] == ["Real Work"]

    from alluvia.engine.propose import candidates
    assert all(c.source_ref != "t1" for c in candidates(repo, "local"))

    import alluvia.mcp_server as m

    class _D:
        def __init__(self, r):
            self.repo = r
    out = m.unfinished_threads_impl(_D(repo))
    assert [t["label"] for t in out["threads"]] == ["Real Work"]
    out2 = m.recall_themes_impl(_D(repo), query=None)
    assert all(t["label"] != "Autonomous Work" for t in out2["themes"])


def test_unmute_restores(repo):
    _seed(repo)
    repo.mute_label("local", "autonomous work")          # case-insensitive
    repo.unmute_label("local", "AUTONOMOUS WORK")
    eng = Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2)
    assert {t.label for t in eng.unfinished("local")} == {"Autonomous Work", "Real Work"}
