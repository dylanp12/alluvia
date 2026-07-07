import hashlib
from datetime import datetime, timezone
from alluvia.models import Link, Note, Theme
from alluvia.llm.client import FakeLLM
from alluvia.engine.propose import candidates, generate_proposal


class ScriptedEmbedder:
    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            base = [1.0, 0.0] if "auth" in t.lower() else [0.0, 1.0]
            eps = (int(hashlib.sha256(t.encode()).hexdigest(), 16) % 100) / 10000.0
            out.append(base + [eps, 0.0, 0.0, 0.0, 0.0, 0.0])
        return out


def _seed(repo):
    notes = [
        Note(id="note:a", user_id="local", session_id="claude-code:s1", span_ref="msg:0",
             kind="problem", text="auth tokens leak in logs",
             created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        Note(id="note:b", user_id="local", session_id="cursor:s2", span_ref="msg:0",
             kind="idea", text="auth middleware should scrub logs",
             created_at=datetime(2026, 6, 1, tzinfo=timezone.utc)),
        Note(id="note:c", user_id="local", session_id="claude-code:s3", span_ref="msg:0",
             kind="question", text="which deploy target",
             created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    ]
    repo.upsert_notes(notes)
    repo.set_embedding("local", "note:a", [1.0, 0.0] + [0.0] * 6)
    repo.set_embedding("local", "note:b", [1.0, 0.01] + [0.0] * 6)
    repo.set_embedding("local", "note:c", [0.0, 1.0] + [0.0] * 6)
    repo.replace_links("local", [Link(id="link:ab", user_id="local",
        from_note_id="note:a", to_note_id="note:b", from_theme_id="t0",
        to_theme_id="t1", kind="cross_source_surprise", weight=2.4)])
    repo.replace_themes("local", [Theme(
        id="t9", user_id="local", label="Deploy", summary="deploy stuff",
        note_ids=["note:c"], first_seen=datetime(2025, 1, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 1, 24, tzinfo=timezone.utc),
        session_count=4, source_count=1, status="open")])


def test_candidates_orders_links_then_open_themes(repo):
    _seed(repo)
    cands = candidates(repo, "local")
    assert cands[0].kind == "link" and cands[0].source_ref == "link:ab"
    assert any(c.kind == "theme" and c.source_ref == "t9" for c in cands)


def test_happy_path_generates_pending_proposal(repo):
    _seed(repo)
    gen = FakeLLM([{"title": "Scrub tokens at log boundary",
                    "proposal": "Deploy a log-scrubbing filter for tokens.",
                    "next_step": "Add a scrub filter to the logging config.",
                    "cites": ["note:a", "note:b"]}])
    critic = FakeLLM([{"feasibility": 4, "risk": "low"}])
    p = generate_proposal(repo, "local", candidates(repo, "local")[0],
                          gen, critic, ScriptedEmbedder())
    assert p is not None and p.outcome == "pending"
    assert p.feasibility == 4 and set(p.cites) == {"note:a", "note:b"}
    # dedup: same material is excluded from the next candidates() pass
    assert all(c.source_ref != "link:ab" for c in candidates(repo, "local"))


def test_no_cites_rejected_and_recorded(repo):
    _seed(repo)
    gen = FakeLLM([{"title": "T", "proposal": "P", "next_step": "N", "cites": []}])
    p = generate_proposal(repo, "local", candidates(repo, "local")[0],
                          gen, FakeLLM([]), ScriptedEmbedder())
    assert p is None
    rejected = repo.list_proposals("local", outcomes=("rejected",))
    assert rejected and rejected[0].reject_reason == "no_cites"


def test_paraphrase_rejected(repo):
    _seed(repo)
    # proposal text embeds in the SAME direction as the auth source notes -> cosine ~1
    gen = FakeLLM([{"title": "T", "proposal": "auth tokens leak in logs, basically",
                    "next_step": "N", "cites": ["note:a"]}])
    p = generate_proposal(repo, "local", candidates(repo, "local")[0],
                          gen, FakeLLM([]), ScriptedEmbedder())
    assert p is None
    rejected = repo.list_proposals("local", outcomes=("rejected",))
    assert rejected and rejected[0].reject_reason == "paraphrase"


def test_cites_normalized_bare_and_bracketed(repo):
    _seed(repo)
    # model cites bare hex + bracketed; hallucinated id dropped; still grounded
    gen = FakeLLM([{"title": "T", "proposal": "Deploy a scrub layer for services.",
                    "next_step": "N",
                    "cites": ["a"[:0] + "note:a"[5:], "[note:b]", "note:hallucinated"]}])
    # "note:a"[5:] == "a" -> bare id form
    critic = FakeLLM([{"feasibility": 3, "risk": "r"}])
    p = generate_proposal(repo, "local", candidates(repo, "local")[0],
                          gen, critic, ScriptedEmbedder())
    assert p is not None
    assert set(p.cites) == {"note:a", "note:b"}          # normalized + hallucination dropped


def test_excerpt_strips_wrappers(repo):
    from alluvia.models import Message, RawSession, content_hash, session_id
    from alluvia.engine.propose import _excerpt
    msgs = [Message(role="user",
                    text="<local-command-stdout>noise</local-command-stdout>real content")]
    s = RawSession(id=session_id("claude-code", "sX"), user_id="local",
                   source="claude-code", native_id="sX", title="t",
                   started_at=None, ended_at=None, messages=msgs,
                   content_hash=content_hash(msgs))
    repo.upsert_session(s)
    n = Note(id="note:e", user_id="local", session_id="claude-code:sX",
             span_ref="msg:0", kind="idea", text="x", created_at=None)
    repo.upsert_notes([n])
    ex = _excerpt(repo, "local", n)
    assert "local-command-stdout" not in ex and "real content" in ex


def test_feasibility_failure_labels_none(repo):
    _seed(repo)

    class Exploding:
        def complete_json(self, s, u):
            raise RuntimeError("429")

    gen = FakeLLM([{"title": "T", "proposal": "Deploy a scrubber.", "next_step": "N",
                    "cites": ["note:a"]}])
    p = generate_proposal(repo, "local", candidates(repo, "local")[0],
                          gen, Exploding(), ScriptedEmbedder())
    assert p is not None and p.feasibility is None and p.outcome == "pending"
