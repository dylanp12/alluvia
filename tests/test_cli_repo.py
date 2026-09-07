from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia.models import Message, Note, RawSession, content_hash
from alluvia.repo_share import share_file


def test_repo_share_cli(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_repo", lambda: repo)
    root = tmp_path / "acme"; (root / ".git").mkdir(parents=True)
    monkeypatch.chdir(root)
    ms = [Message(role="user", text="hi")]
    repo.upsert_session(RawSession(id="claude-code:s1", user_id="local", source="claude-code", native_id="s1",
                                   title="t", started_at=None, ended_at=None, messages=ms,
                                   content_hash=content_hash(ms), project=str(root), branch="main"))
    repo.upsert_notes([Note(id="n:a", user_id="local", session_id="claude-code:s1", span_ref="msg:0",
                            kind="decision", text="use postgres", created_at=None)])
    r = CliRunner().invoke(cli.app, ["repo", "status"])
    assert r.exit_code == 0 and "off" in r.output
    r = CliRunner().invoke(cli.app, ["repo", "share", "on"])
    assert r.exit_code == 0, r.output
    assert share_file(str(root)).exists() and "1 note" in r.output
    assert "commit" in r.output.lower()                       # tells the user what to do next
    r = CliRunner().invoke(cli.app, ["repo", "status"])
    assert "on" in r.output and "1 note" in r.output
    r = CliRunner().invoke(cli.app, ["repo", "share", "off"])
    assert r.exit_code == 0 and not share_file(str(root)).exists()
    r = CliRunner().invoke(cli.app, ["repo", "share", "sideways"])
    assert r.exit_code != 0
