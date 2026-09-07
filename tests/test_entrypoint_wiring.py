"""The CLI/MCP entrypoints must wire role-routed, governed LLMs backed by the
SQLite health store — otherwise breaker state dies with the process and every
fresh `alluvia` invocation re-hammers an exhausted model (issue #3 §7)."""
import alluvia.cli as cli
from alluvia.llm.client import RoleRouter
from alluvia.llm.governor import Governor
from alluvia.store.repo import LLMHealthStore


def _groq(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("ALLUVIA_LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "k")


def test_build_engine_wires_role_router_with_sqlite_health(tmp_path, monkeypatch):
    _groq(monkeypatch, tmp_path)
    repo = cli._repo()
    eng = cli.build_engine(repo)
    assert isinstance(eng.llm, RoleRouter)
    gov = eng.llm.for_role("label")
    assert isinstance(gov, Governor)
    assert isinstance(gov.store, LLMHealthStore)
    assert gov.store.repo is repo


def test_propose_deps_share_the_same_persistent_health(tmp_path, monkeypatch):
    _groq(monkeypatch, tmp_path)
    repo = cli._repo()
    gen, critic, _ = cli.build_propose_deps(repo)
    assert isinstance(gen, Governor) and isinstance(critic, Governor)
    assert isinstance(gen.store, LLMHealthStore)
    assert len(gen.candidates) == 1               # propose never falls through
    assert len(critic.candidates) >= 2            # status chain does


def test_mcp_deps_use_sqlite_health(tmp_path, monkeypatch):
    _groq(monkeypatch, tmp_path)
    from alluvia.mcp_server import SiftDeps
    deps = SiftDeps()
    assert isinstance(deps.gen_llm.store, LLMHealthStore)


def test_mcp_dependency_excludes_the_2x_rename():
    """Dogfooding 2026-09-06: a fresh `uv tool install alluvia` resolved mcp 2.x,
    where FastMCP was renamed, and `alluvia mcp` crashed on import — every new
    install showed "1 MCP server failed". The lockfile hid it from the suite.
    Pin below 2 until the server is migrated."""
    import re, tomllib, pathlib
    py = tomllib.loads(pathlib.Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text())
    spec = next(d for d in py["project"]["dependencies"] if re.match(r"^mcp\b", d))
    assert "<2" in spec.replace(" ", ""), spec
