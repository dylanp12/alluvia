from datetime import datetime, timezone
from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo
from alluvia.models import Link, Note, Proposal, Theme

runner = CliRunner()


def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("SIFT_PENDING_FLAG", str(tmp_path / "pending"))
    conn = connect(str(tmp_path / "d.db"))
    init_schema(conn, embed_dim=8)
    return Repo(conn), tmp_path / "pending"


def _seed(repo):
    repo.upsert_notes([
        Note(id="note:a", user_id="local", session_id="claude-code:s", span_ref="msg:0",
             kind="idea", text="alpha idea", created_at=None),
        Note(id="note:b", user_id="local", session_id="cursor:s", span_ref="msg:0",
             kind="idea", text="beta idea", created_at=None)])
    repo.replace_links("local", [Link(id="link:1", user_id="local",
        from_note_id="note:a", to_note_id="note:b", from_theme_id="tA",
        to_theme_id="tB", kind="cross_source_surprise", weight=2.0)])
    repo.replace_themes("local", [Theme(
        id="tA", user_id="local", label="Alpha", summary="s", note_ids=["note:a"],
        first_seen=datetime(2025, 1, 1, tzinfo=timezone.utc),
        last_seen=datetime(2026, 6, 1, tzinfo=timezone.utc),
        session_count=4, source_count=1, status="open")])


def test_run_show_flag_lifecycle(tmp_path, monkeypatch):
    repo, flag = _env(tmp_path, monkeypatch)
    _seed(repo)
    r = runner.invoke(cli.app, ["digest", "run", "--force"])
    assert r.exit_code == 0, r.output
    assert "CONNECTION" in r.output and flag.exists()
    r2 = runner.invoke(cli.app, ["digest", "show"])
    assert r2.exit_code == 0 and "digest #" in r2.output
    assert not flag.exists()                                 # show clears flag
    # if-due right after: silent no-op, no new digest
    r3 = runner.invoke(cli.app, ["digest", "run", "--if-due"])
    assert r3.exit_code == 0 and r3.output.strip() == ""


def test_dismiss_routes_proposal_to_rated_via_digest(tmp_path, monkeypatch):
    repo, _ = _env(tmp_path, monkeypatch)
    repo.insert_proposal(Proposal(
        id="prop:d1", user_id="local", created_at="2026-07-04T00:00:00+00:00",
        kind="link", source_ref="l", source_hash="h", title="T", text="b",
        next_step="n", cites=["note:1"], novelty_sim=None, feasibility=3,
        risk=None, model="m"))
    repo.insert_digest("local", "2026-07-04T00:00:00+00:00",
                       [{"kind": "proposal", "ref": "prop:d1", "theme_ref": None,
                         "snapshot": "PROPOSAL [prop:d1] T"}])
    r = runner.invoke(cli.app, ["digest", "dismiss", "1"])
    assert r.exit_code == 0, r.output
    p = repo.get_proposal("local", "prop:d1")
    assert p.outcome == "dismissed" and p.rated_via == "digest"


def test_get_digest_mcp_shape(tmp_path, monkeypatch):
    repo, _ = _env(tmp_path, monkeypatch)
    repo.insert_digest("local", "2026-07-04T00:00:00+00:00",
                       [{"kind": "nudge", "ref": "tA", "theme_ref": "tA",
                         "snapshot": "UNFINISHED: Alpha"}])
    import alluvia.mcp_server as m

    class _D:
        def __init__(self, r):
            self.repo = r
    out = m.get_digest_impl(_D(repo))
    assert out["digest"]["items"][0]["snapshot"].startswith("UNFINISHED")
    assert out["pending"] is False
