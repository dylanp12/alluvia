from datetime import datetime, timezone
from alluvia.models import Link, Note, Theme
from alluvia.llm.client import FakeLLM
import alluvia.mcp_server as m


class _Emb:
    dim = 8

    def embed(self, texts):
        return [([1.0, 0.0] + [0.0] * 6) if "auth" in t.lower()
                else ([0.0, 1.0] + [0.0] * 6) for t in texts]


class _Deps:
    def __init__(self, repo, gen=None, critic=None):
        self.repo = repo
        self._emb = _Emb()
        self._gen = gen or FakeLLM([])
        self._critic = critic or FakeLLM([])

    @property
    def embedder(self):
        return self._emb

    @property
    def gen_llm(self):
        return self._gen

    @property
    def critic_llm(self):
        return self._critic


def _seed(repo):
    repo.upsert_notes([
        Note(id="note:a", user_id="local", session_id="claude-code:sA", span_ref="msg:0",
             kind="problem", text="auth tokens leak in logs",
             created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        Note(id="note:b", user_id="local", session_id="cursor:sB", span_ref="msg:0",
             kind="idea", text="auth middleware should scrub logs",
             created_at=datetime(2026, 6, 1, tzinfo=timezone.utc)),
    ])
    repo.set_embedding("local", "note:a", [1.0, 0.0] + [0.0] * 6)
    repo.set_embedding("local", "note:b", [1.0, 0.01] + [0.0] * 6)
    repo.replace_themes("local", [Theme(
        id="t1", user_id="local", label="Auth hygiene", summary="auth stuff " * 100,
        note_ids=["note:a", "note:b"], first_seen=datetime(2025, 1, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 6, 1, tzinfo=timezone.utc),
        session_count=3, source_count=2, status="open")])
    repo.replace_links("local", [Link(id="link:1", user_id="local",
        from_note_id="note:a", to_note_id="note:b", from_theme_id="t0",
        to_theme_id="t1", kind="cross_source_surprise", weight=2.0, why="both auth")])


def test_recall_themes_query_and_truncation(repo):
    _seed(repo)
    out = m.recall_themes_impl(_Deps(repo), query="auth stuff", limit=5)
    assert out["themes"] and out["themes"][0]["label"] == "Auth hygiene"
    assert len(out["themes"][0]["summary"]) <= 403          # 400 + ellipsis


def test_find_connections_shapes(repo):
    _seed(repo)
    out = m.find_connections_impl(_Deps(repo), topic=None, limit=5)
    c = out["connections"][0]
    assert c["from"]["source"] == "claude-code" and c["to"]["source"] == "cursor"
    assert c["why"] == "both auth"


def test_unfinished_and_show_source(repo):
    _seed(repo)
    out = m.unfinished_threads_impl(_Deps(repo))
    assert out["threads"][0]["label"] == "Auth hygiene"
    src = m.show_source_impl(_Deps(repo), note_id="note:a")
    assert src["note"]["text"].startswith("auth tokens")
    assert src["session"]["source"] == "claude-code"
    missing = m.show_source_impl(_Deps(repo), note_id="note:nope")
    assert "error" in missing                                # error-as-value


def test_propose_and_rate_via_mcp(repo, monkeypatch):
    monkeypatch.setenv("ALLUVIA_MCP_WRITES", "1")   # writes are opt-in now
    _seed(repo)
    gen = FakeLLM([{"title": "Central scrubber", "proposal": "Build one scrub layer.",
                    "next_step": "Extract the filter.", "cites": ["note:a"]}])
    critic = FakeLLM([{"feasibility": 4, "risk": "low"}])
    deps = _Deps(repo, gen=gen, critic=critic)

    class _OrthEmb(_Emb):                       # proposal text must pass novelty gate
        def embed(self, texts):
            return [[0.0, 1.0] + [0.0] * 6 for _ in texts]
    deps._emb = _OrthEmb()

    out = m.propose_next_impl(deps, theme_id=None, limit=1)
    assert out["proposals"] and out["proposals"][0]["title"] == "Central scrubber"
    pid = out["proposals"][0]["id"]
    rated = m.rate_proposal_impl(deps, proposal_id=pid, verdict="keep", note="yes")
    assert rated["outcome"] == "kept"
    assert repo.get_proposal("local", pid).rated_via == "mcp"
    bad = m.rate_proposal_impl(deps, proposal_id=pid, verdict="maybe")
    assert "error" in bad


def test_list_caps_at_25(repo):
    _seed(repo)
    out = m.recall_themes_impl(_Deps(repo), query=None, limit=999)
    assert out["limit"] == 25


def test_cli_has_mcp_command():
    import alluvia.cli as cli
    cmds = [c.name or c.callback.__name__ for c in cli.app.registered_commands]
    assert "mcp" in cmds
