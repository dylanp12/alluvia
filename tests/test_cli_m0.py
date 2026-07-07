from pathlib import Path
from typer.testing import CliRunner
from alluvia.cli import app

runner = CliRunner()


def test_ingest_then_show(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "cli.db"))
    fixtures = str(Path(__file__).parent / "fixtures")
    r1 = runner.invoke(app, ["ingest", "--source", "claude-code", "--path", fixtures])
    assert r1.exit_code == 0, r1.output
    assert "1 session" in r1.output
    r2 = runner.invoke(app, ["show", "claude-code:sess-1"])
    assert r2.exit_code == 0, r2.output
    assert "token service" in r2.output
