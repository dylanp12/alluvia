"""Issue #4: the engine reports stage progress through the reporter seam,
the governor reports its waits, and the CLI surfaces both. MCP and default
callers stay silent (NullReporter)."""
import re

from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia.engine.engine import Engine
from alluvia.llm.client import FakeLLM

from tests.test_cli_m1 import ScriptedEmbedder
from tests.test_cli_degraded import DISTILL, _seed_logs, _engine_factory

runner = CliRunner()


class RecordingReporter:
    def __init__(self):
        self.events = []

    def start(self, stage, total=None):
        self.events.append(("start", stage, total))

    def advance(self, n=1):
        self.events.append(("advance", n))

    def note(self, msg):
        self.events.append(("note", msg))

    def finish(self):
        self.events.append(("finish",))

    def close(self):
        self.events.append(("close",))


def _fake_llm():
    return FakeLLM(DISTILL + [{"label": "Auth", "summary": "a"},
                              {"label": "Deploy", "summary": "d"}])


def _seed_sessions(repo):
    from tests.test_engine_refresh import _sess
    repo.upsert_session(_sess("s1", ["auth token service"]))
    repo.upsert_session(_sess("s2", ["auth middleware"]))
    repo.upsert_session(_sess("s3", ["deploy to fly"]))
    repo.upsert_session(_sess("s4", ["deploy pipeline"]))


def test_refresh_reports_stages_with_totals(repo):
    _seed_sessions(repo)
    rep = RecordingReporter()
    eng = Engine(repo, ScriptedEmbedder(), _fake_llm(), min_cluster_size=2)
    eng.refresh("local", reporter=rep)
    starts = [(e[1], e[2]) for e in rep.events if e[0] == "start"]
    stages = [s for s, _ in starts]
    assert stages[0].startswith("distilling") and starts[0][1] == 4
    assert any(s.startswith("embedding") for s in stages)
    assert any(s.startswith("mapping") for s in stages)
    assert any(s.startswith("linking") for s in stages)
    distill_advances = 0
    for e in rep.events:
        if e[0] == "start":
            counting = e[1].startswith("distilling")
        elif e[0] == "advance" and counting:
            distill_advances += e[1]
    assert distill_advances == 4


def test_embedding_runs_in_batches_so_progress_moves(repo, monkeypatch):
    _seed_sessions(repo)

    class CountingEmbedder(ScriptedEmbedder):
        def __init__(self):
            self.batch_sizes = []

        def embed(self, texts):
            self.batch_sizes.append(len(texts))
            return super().embed(texts)

    monkeypatch.setattr(Engine, "EMBED_BATCH", 3)
    emb = CountingEmbedder()
    eng = Engine(repo, emb, _fake_llm(), min_cluster_size=2)
    eng.refresh("local", reporter=RecordingReporter())
    assert emb.batch_sizes == [3, 1]             # 4 notes in batches of 3


def test_governor_reports_waits_through_on_wait():
    from alluvia.llm.governor import Governor, MemoryHealthStore
    from tests.test_llm_governor import FakeClock, ScriptedAdapter, RateLimited

    clock = FakeClock()
    waits = []
    gov = Governor("groq", [("m1", ScriptedAdapter([RateLimited("30"), {"ok": 1}]))],
                   store=MemoryHealthStore(), clock=clock, sleeper=clock.sleep,
                   patience=600, on_wait=lambda model, s: waits.append((model, s)))
    assert gov.complete_json("s", "u") == {"ok": 1}
    assert waits == [("m1", 30.0)]


def test_refresh_cli_shows_progress_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    monkeypatch.setattr(cli, "build_engine", _engine_factory(_fake_llm()))
    logs = _seed_logs(tmp_path)
    runner.invoke(cli.app, ["ingest", "--source", "claude-code", "--path", str(logs)])
    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 0, r.output
    assert "distilling" in r.output              # a user can SEE it working
    assert "mapping" in r.output


def test_ingest_cli_shows_running_count(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    logs = _seed_logs(tmp_path)
    r = runner.invoke(cli.app, ["ingest", "--source", "claude-code", "--path", str(logs)])
    assert r.exit_code == 0
    assert "ingesting" in r.output


def test_version_flag(monkeypatch):
    r = runner.invoke(cli.app, ["--version"])
    assert r.exit_code == 0
    assert re.search(r"alluvia \d+\.\d+\.\d+", r.output)
