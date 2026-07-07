from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia.models import Proposal
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo

runner = CliRunner()


def _prop(pid, feasibility, outcome="pending"):
    return Proposal(id=pid, user_id="local", created_at="2026-07-02T00:00:00+00:00",
                    kind="link", source_ref="link:x", source_hash=pid, title=f"T-{pid}",
                    text="body", next_step="do X", cites=["note:1"], novelty_sim=0.4,
                    feasibility=feasibility, risk="r", model="m", outcome=outcome)


def _seed(dbpath):
    conn = connect(dbpath)
    init_schema(conn, embed_dim=8)
    repo = Repo(conn)
    repo.insert_proposal(_prop("prop:solid", 5))
    repo.insert_proposal(_prop("prop:shaky", 1))
    repo.insert_proposal(_prop("prop:kept1", 4, outcome="kept"))
    repo.insert_proposal(_prop("prop:dis1", 3, outcome="dismissed"))
    return repo


def test_proposals_orders_feasible_first_flags_shaky(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "c.db"))
    _seed(str(tmp_path / "c.db"))
    r = runner.invoke(cli.app, ["proposals"])
    assert r.exit_code == 0, r.output
    assert r.output.index("T-prop:solid") < r.output.index("T-prop:shaky")
    assert "novel-but-shaky" in r.output


def test_rate_updates_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "c.db"))
    _seed(str(tmp_path / "c.db"))
    r = runner.invoke(cli.app, ["rate", "prop:solid", "--keep", "--note", "good one"])
    assert r.exit_code == 0, r.output
    kept = Repo(connect(str(tmp_path / "c.db"))).list_proposals(
        "local", outcomes=("kept",))
    assert any(p.id == "prop:solid" and p.rating_note == "good one" for p in kept)


def test_stats_shows_hit_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "c.db"))
    _seed(str(tmp_path / "c.db"))
    r = runner.invoke(cli.app, ["stats"])
    assert r.exit_code == 0, r.output
    assert "hit-rate" in r.output and "50" in r.output     # 1 kept / 2 rated


def test_propose_command_uses_injected_deps(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "c.db"))
    from alluvia.llm.client import FakeLLM
    from alluvia.models import Link, Note
    conn = connect(str(tmp_path / "c.db"))
    init_schema(conn, embed_dim=8)
    repo = Repo(conn)
    repo.upsert_notes([
        Note(id="note:a", user_id="local", session_id="claude-code:s", span_ref="msg:0",
             kind="idea", text="auth idea", created_at=None),
        Note(id="note:b", user_id="local", session_id="cursor:s", span_ref="msg:0",
             kind="idea", text="auth follow-up", created_at=None)])
    repo.set_embedding("local", "note:a", [1.0, 0.0] + [0.0] * 6)
    repo.set_embedding("local", "note:b", [1.0, 0.01] + [0.0] * 6)
    repo.replace_links("local", [Link(id="link:1", user_id="local",
        from_note_id="note:a", to_note_id="note:b", from_theme_id="t0",
        to_theme_id="t1", kind="cross_source_surprise", weight=2.0)])

    class _Emb:
        dim = 8

        def embed(self, texts):
            return [[0.0, 1.0] + [0.0] * 6 for _ in texts]   # orthogonal -> passes gate

    def fake_deps(_repo):
        return (FakeLLM([{"title": "Do the thing", "proposal": "New direction.",
                          "next_step": "Start with X.", "cites": ["note:a"]}]),
                FakeLLM([{"feasibility": 4, "risk": "low"}]),
                _Emb())
    monkeypatch.setattr(cli, "build_propose_deps", fake_deps)
    r = runner.invoke(cli.app, ["propose", "--limit", "1"])
    assert r.exit_code == 0, r.output
    assert "Do the thing" in r.output
