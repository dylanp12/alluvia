"""Issue #10: live resource usage — process discovery, metrics snapshot,
and the governor's own network-traffic accounting."""
import time
from types import SimpleNamespace

from alluvia.resources import (find_role, machine_context, snapshot)


# --- discovery: which processes are alluvia, and what role ------------------

def test_find_role_matches_the_console_script():
    assert find_role(["/home/u/.venv/bin/alluvia", "refresh"]) == "refresh"
    assert find_role(["/usr/local/bin/alluvia", "serve", "--open"]) == "serve"
    assert find_role(["alluvia", "mcp"]) == "mcp"
    assert find_role(["alluvia"]) == "cli"


def test_find_role_matches_python_running_the_script():
    assert find_role(["/x/.venv/bin/python", "/x/.venv/bin/alluvia", "mcp"]) == "mcp"
    assert find_role(["python3", "-m", "alluvia", "themes"]) == "themes"


def test_find_role_rejects_lookalikes():
    # a path merely CONTAINING the name is not the program
    assert find_role(["vim", "/home/u/alluvia/notes.txt"]) is None
    assert find_role(["/home/u/alluvia/dev/tool", "run"]) is None
    assert find_role(["grep", "alluvia", "log.txt"]) is None
    assert find_role([]) is None


# --- snapshot over injectable processes --------------------------------------

class FakeProc:
    def __init__(self, pid, cmdline, rss=1024 * 1024, cpu=1.5,
                 read=2048, write=4096, created=None):
        self.pid = pid
        self.info = {"pid": pid, "cmdline": cmdline,
                     "create_time": created or (time.time() - 60)}
        self._rss, self._cpu, self._read, self._write = rss, cpu, read, write

    def cpu_percent(self, interval=None):
        return self._cpu

    def memory_info(self):
        return SimpleNamespace(rss=self._rss)

    def io_counters(self):
        return SimpleNamespace(read_bytes=self._read, write_bytes=self._write)


def test_snapshot_keeps_only_alluvia_processes_with_metrics():
    procs = [
        FakeProc(11, ["/v/bin/alluvia", "refresh"]),
        FakeProc(12, ["python", "/v/bin/alluvia", "mcp"], rss=2 * 1024 * 1024),
        FakeProc(13, ["chrome", "--stuff"]),
    ]
    rows = snapshot(procs=procs, sample_s=0)
    assert [(r["pid"], r["role"]) for r in rows] == [(11, "refresh"), (12, "mcp")]
    assert rows[0]["rss_bytes"] == 1024 * 1024
    assert rows[0]["cpu_pct"] == 1.5
    assert rows[0]["disk_read_bytes"] == 2048
    assert rows[0]["uptime_s"] >= 59


def test_snapshot_survives_processes_dying_mid_scan():
    class Vanishing(FakeProc):
        def memory_info(self):
            raise ProcessLookupError

    rows = snapshot(procs=[Vanishing(9, ["alluvia", "serve"]),
                           FakeProc(10, ["alluvia", "themes"])], sample_s=0)
    assert [r["pid"] for r in rows] == [10]


def test_machine_context_shape():
    ctx = machine_context()
    assert ctx["cpu_count"] >= 1
    assert ctx["mem_total_bytes"] > 0
    assert 0 <= ctx["mem_used_pct"] <= 100


# --- governor accounts its own network traffic --------------------------------

def test_governor_counts_calls_and_bytes(repo):
    from alluvia.llm.governor import Governor
    from alluvia.store.repo import LLMHealthStore
    from tests.test_llm_governor import FakeClock, ScriptedAdapter

    clock = FakeClock()
    store = LLMHealthStore(repo)
    gov = Governor("groq", [("m1", ScriptedAdapter([{"ok": True}, {"two": 2}]))],
                   store=store, clock=clock, sleeper=clock.sleep)
    gov.complete_json("sys prompt", "user body")
    gov.complete_json("sys prompt", "user body")
    st = repo.llm_health_load("groq", "m1")
    assert st["calls"] == 2
    assert st["sent_bytes"] >= 2 * len("sys promptuser body")
    assert st["recv_bytes"] > 0


def test_llm_traffic_rollup(repo):
    from alluvia.resources import llm_traffic
    repo.llm_health_save("groq", "m1", {"calls": 3, "sent_bytes": 300,
                                        "recv_bytes": 900})
    rows = llm_traffic(repo)
    assert rows[0]["model"] == "m1" and rows[0]["calls"] == 3


# --- CLI ----------------------------------------------------------------------

def test_top_cli_smoke(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    import alluvia.cli as cli
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    r = CliRunner().invoke(cli.app, ["top"])
    assert r.exit_code == 0, r.output
    out = r.output.lower()
    assert "machine" in out
    assert "llm traffic" in out
