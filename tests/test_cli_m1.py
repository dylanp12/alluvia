import json
import hashlib
from typer.testing import CliRunner
import alluvia.cli as cli
from alluvia.llm.client import FakeLLM

runner = CliRunner()


class ScriptedEmbedder:
    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            base = [1.0, 0.0] if "auth" in t.lower() else [0.0, 1.0]
            eps = (int(hashlib.sha256(t.encode()).hexdigest(), 16) % 100) / 10000.0
            out.append(base + [eps, 0.0, 0.0, 0.0, 0.0, 0.0])
        return out


def test_refresh_and_themes(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "m1.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)

    def fake_build_engine(repo):
        from alluvia.engine.engine import Engine
        llm = FakeLLM([
            {"notes": [{"kind": "idea", "text": "auth token service", "span": "msg:0"}]},
            {"notes": [{"kind": "idea", "text": "auth middleware", "span": "msg:0"}]},
            {"notes": [{"kind": "idea", "text": "deploy to fly", "span": "msg:0"}]},
            {"notes": [{"kind": "idea", "text": "deploy pipeline", "span": "msg:0"}]},
            {"label": "Auth", "summary": "Auth architecture thinking."},
            {"label": "Deploy", "summary": "Deployment thinking."},
        ])
        return Engine(repo, ScriptedEmbedder(), llm, min_cluster_size=2)

    monkeypatch.setattr(cli, "build_engine", fake_build_engine)

    logs = tmp_path / "logs"
    logs.mkdir()
    for name, content in [("a", "auth token service"), ("b", "auth middleware"),
                          ("c", "deploy to fly"), ("d", "deploy pipeline")]:
        line = json.dumps({"type": "user", "message": {"role": "user", "content": content}})
        (logs / f"{name}.jsonl").write_text(line + "\n")

    assert runner.invoke(cli.app, ["ingest", "--source", "claude-code", "--path", str(logs)]).exit_code == 0
    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 0, r.output
    rt = runner.invoke(cli.app, ["themes"])
    assert rt.exit_code == 0, rt.output
    assert "Auth" in rt.output
