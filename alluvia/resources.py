"""Live resource usage (issue #10): what alluvia processes are consuming
right now — CPU, RAM, disk I/O — plus the app's own network accounting.

Per-process network bytes are not visible to unprivileged userland on any
OS, so alluvia doesn't fake them: its only network traffic is LLM calls,
and the governor counts those at the source (calls + bytes per model,
persisted with the breaker state). OS metrics come from psutil; process
discovery is a strict match on the program being run, never on paths that
merely contain the name."""
from __future__ import annotations

import os
import time

ROLE_COMMANDS = None      # any subcommand is a role; first arg wins


def _basename(part: str) -> str:
    return os.path.basename(part.replace("\\", "/")).lower()


def _entry_index(cmdline: list[str]) -> int | None:
    """Index of the alluvia entrypoint in argv, or None.

    Accepts: argv[0] basename == alluvia (console script) · a python
    binary running the alluvia script (argv[1]) · `python -m alluvia`."""
    if not cmdline:
        return None
    first = _basename(cmdline[0])
    exe = first.removesuffix(".exe")
    if exe == "alluvia":
        return 0
    if exe.startswith("python"):
        if len(cmdline) > 1 and _basename(cmdline[1]) == "alluvia":
            return 1
        if (len(cmdline) > 2 and cmdline[1] == "-m"
                and cmdline[2].lower() == "alluvia"):
            return 2
    return None


def find_role(cmdline: list[str]) -> str | None:
    """The subcommand a running alluvia process is serving, or None if the
    process isn't alluvia at all."""
    i = _entry_index(cmdline)
    if i is None:
        return None
    for part in cmdline[i + 1:]:
        if not part.startswith("-"):
            return part
    return "cli"


def snapshot(procs=None, sample_s: float = 0.4) -> list[dict]:
    """Metrics for every running alluvia process. `procs` is injectable for
    tests; by default psutil scans the machine. CPU is sampled: prime every
    candidate, wait `sample_s`, then read."""
    if procs is None:
        import psutil
        procs = list(psutil.process_iter(["pid", "cmdline", "create_time"]))
    matched = []
    for p in procs:
        try:
            role = find_role(p.info.get("cmdline") or [])
        except Exception:
            continue
        if role is not None:
            matched.append((p, role))
    for p, _role in matched:                      # prime CPU counters
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    if matched and sample_s:
        time.sleep(sample_s)
    now = time.time()
    rows = []
    for p, role in matched:
        try:
            io = None
            try:
                io = p.io_counters()
            except Exception:
                pass                              # unsupported on some OSes
            rows.append({
                "pid": p.info["pid"] if isinstance(p.info.get("pid"), int) else p.pid,
                "role": role,
                "cpu_pct": round(p.cpu_percent(None), 1),
                "rss_bytes": p.memory_info().rss,
                "disk_read_bytes": getattr(io, "read_bytes", None),
                "disk_write_bytes": getattr(io, "write_bytes", None),
                "uptime_s": int(now - p.info.get("create_time", now)),
            })
        except Exception:
            continue                              # died mid-scan: skip quietly
    return sorted(rows, key=lambda r: r["pid"])


def machine_context() -> dict:
    """One line of context so per-process numbers mean something."""
    import psutil
    vm = psutil.virtual_memory()
    return {"cpu_count": psutil.cpu_count() or 1,
            "cpu_pct": psutil.cpu_percent(interval=0.1),
            "mem_total_bytes": vm.total,
            "mem_used_pct": vm.percent}


def llm_traffic(repo) -> list[dict]:
    """Cumulative LLM traffic per model — alluvia's entire network story."""
    rows = [r for r in repo.llm_health_all()
            if (r.get("calls") or 0) > 0]
    return sorted(({"provider": r["provider"], "model": r["model"],
                    "calls": int(r.get("calls") or 0),
                    "sent_bytes": int(r.get("sent_bytes") or 0),
                    "recv_bytes": int(r.get("recv_bytes") or 0)}
                   for r in rows),
                  key=lambda r: -r["calls"])
