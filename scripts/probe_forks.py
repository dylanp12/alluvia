"""Probe VS-Code-fork state.vscdb files for chat-bearing keys.

Usage: uv run python scripts/probe_forks.py [--limit-dbs 8] [--value-head 160]
Prints, per flavor: tables found, keys matching chat-ish patterns, value sizes,
and a truncated value head so extractor KEY_PATTERNS can be set from reality.
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import re
import shutil
import sqlite3
import tempfile

from alluvia.platform import fork_roots

ROOTS = {
    "cursor": next(iter(fork_roots("Cursor")), ""),
    "windsurf": next(iter(fork_roots("Windsurf")), ""),
    "antigravity": next(iter(fork_roots("Antigravity")), ""),
}
KEY_RX = re.compile(r"chat|composer|aichat|cascade|agent|conversation|generation|bubble",
                    re.IGNORECASE)


def db_paths(root: str) -> list[str]:
    out = glob.glob(os.path.join(root, "User", "workspaceStorage", "*", "state.vscdb"))
    g = os.path.join(root, "User", "globalStorage", "state.vscdb")
    if os.path.exists(g):
        out.append(g)
    return sorted(out)


def copy_db(path: str, tmpdir: str) -> str:
    dst = os.path.join(tmpdir, "probe.vscdb")
    shutil.copy2(path, dst)
    for ext in ("-wal", "-shm"):
        if os.path.exists(path + ext):
            shutil.copy2(path + ext, dst + ext)
    return dst


def probe_db(path: str, value_head: int) -> list[str]:
    lines: list[str] = []
    tmpdir = tempfile.mkdtemp(prefix="alluvia-probe-")
    try:
        conn = sqlite3.connect(f"file:{copy_db(path, tmpdir)}?mode=ro", uri=True)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        lines.append(f"  tables: {tables}")
        for table in ("ItemTable", "cursorDiskKV"):
            if table not in tables:
                continue
            for key, val in conn.execute(f"SELECT key, value FROM {table}"):
                if not KEY_RX.search(str(key)):
                    continue
                raw = val if isinstance(val, (bytes, bytearray)) else str(val).encode()
                head = raw[:value_head].decode("utf-8", errors="replace")
                shape = ""
                try:
                    obj = json.loads(raw.decode("utf-8", errors="replace"))
                    if isinstance(obj, dict):
                        shape = f" dict-keys={sorted(obj.keys())[:8]}"
                    elif isinstance(obj, list):
                        shape = f" list[{len(obj)}]"
                except (json.JSONDecodeError, UnicodeDecodeError):
                    shape = " (not-json)"
                lines.append(f"  [{table}] {key}  ({len(raw)}B){shape}")
                lines.append(f"      head: {head!r}")
        conn.close()
    except Exception as e:  # probe never crashes the report
        lines.append(f"  !! {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-dbs", type=int, default=8)
    ap.add_argument("--value-head", type=int, default=160)
    args = ap.parse_args()
    for flavor, root in ROOTS.items():
        print(f"\n===== {flavor} ({root}) =====")
        paths = db_paths(root)
        print(f"{len(paths)} DBs found; probing {min(len(paths), args.limit_dbs)} "
              f"(globalStorage always included if present)")
        keep = paths[-args.limit_dbs:]  # newest-ish tail + globalStorage (sorted last)
        for p in keep:
            print(f"\n-- {p}")
            for line in probe_db(p, args.value_head):
                print(line)


if __name__ == "__main__":
    main()
