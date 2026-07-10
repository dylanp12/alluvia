from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia.llm.client import FakeLLM
from alluvia.models import Link, Note
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo

runner = CliRunner()


class _Emb:                     # explain() never calls embed(); a stub suffices
    dim = 8
    def embed(self, texts):
        return [[0.0] * 8 for _ in texts]


def test_connections_shows_edge_and_fills_why(tmp_path, monkeypatch):
    dbpath = str(tmp_path / "c.db")
    monkeypatch.setenv("ALLUVIA_DB", dbpath)
    conn = connect(dbpath); init_schema(conn, embed_dim=8); repo = Repo(conn)
    repo.upsert_notes([
        Note(id="note:a", user_id="local", session_id="s", span_ref="", kind="idea",
             text="auth tokens", created_at=None),
        Note(id="note:b", user_id="local", session_id="s", span_ref="", kind="idea",
             text="auth middleware", created_at=None),
    ])
    repo.replace_links("local", [Link(id="link:1", user_id="local",
        from_note_id="note:a", to_note_id="note:b", from_theme_id="t0", to_theme_id="t1",
        kind="cross_source_surprise", weight=0.9, why=None)])

    def fake_build_engine(r, reporter=None):
        from alluvia.engine.engine import Engine
        return Engine(r, _Emb(), FakeLLM([{"why": "both about auth"}]))
    monkeypatch.setattr(cli, "build_engine", fake_build_engine)

    r = runner.invoke(cli.app, ["connections"])
    assert r.exit_code == 0, r.output
    assert "both about auth" in r.output                       # lazy why filled + shown
    assert Repo(connect(dbpath)).list_links("local")[0].why == "both about auth"
