import json
from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia.engine.embed import FakeEmbedder
from alluvia.models import Message, Note, RawSession, content_hash


def _seed(repo):
    ms = [Message(role="user", text="hi")]
    repo.upsert_session(RawSession(id="claude-code:s1", user_id="local", source="claude-code", native_id="s1",
                                   title="t", started_at=None, ended_at=None, messages=ms,
                                   content_hash=content_hash(ms), project="/work/acme", branch="main"))
    repo.upsert_notes([Note(id="n:a", user_id="local", session_id="claude-code:s1", span_ref="msg:0",
                            kind="decision", text="use postgres", created_at=None)])


def test_memory_export_import_cli(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    monkeypatch.setattr(cli, "_recall_embedder", lambda: FakeEmbedder(dim=8))
    _seed(repo)
    out = tmp_path / "mem.jsonl"
    r = CliRunner().invoke(cli.app, ["memory", "export", str(out)])
    assert r.exit_code == 0, r.output
    assert "1 session" in r.output and "1 note" in r.output
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert lines[0]["kind"] == "header"
    r = CliRunner().invoke(cli.app, ["memory", "import", str(out)])
    assert r.exit_code == 0, r.output
    assert "already present: 1" in r.output
    r = CliRunner().invoke(cli.app, ["memory", "export", str(tmp_path / "none.jsonl"), "--project", "/nowhere"])
    assert r.exit_code == 0 and "nothing known" in r.output
    r = CliRunner().invoke(cli.app, ["memory", "import", str(tmp_path / "missing.jsonl")])
    assert r.exit_code == 1
