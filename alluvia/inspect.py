"""Machine-footprint report: every path alluvia touches, store contents by
data class, and what's live right now. Pure (repo) -> dict; the CLI renders.

Data classes carry different guarantees, so they're reported separately:
raw is the source of truth (never mutated), derived is rebuildable from raw,
judgments are the user's own decisions and are never regenerated."""
from __future__ import annotations

import os

from alluvia import config

# table -> (data class, SQL expression estimating content bytes)
_CLASSES: dict[str, tuple[str, str | None]] = {
    "raw_sessions": ("raw", "SUM(LENGTH(messages_json))"),
    "notes": ("derived", "SUM(LENGTH(text))"),
    "note_embeddings": ("derived", "SUM(LENGTH(vec))"),
    "themes": ("derived", "SUM(LENGTH(note_ids_json) + LENGTH(COALESCE(summary,'')))"),
    "links": ("derived", "SUM(LENGTH(COALESCE(why,'')) + 64)"),
    "theme_label_cache": ("derived", "SUM(LENGTH(label) + LENGTH(summary))"),
    "theme_status_cache": ("derived", None),
    "distilled_sessions": ("derived", None),
    "llm_health": ("derived", None),
    "proposals": ("judgments", "SUM(LENGTH(title) + LENGTH(text))"),
    "digests": ("judgments", None),
    "digest_items": ("judgments", "SUM(LENGTH(snapshot))"),
    "muted_themes": ("judgments", None),
}


def _file_entry(path: str | None) -> dict:
    if not path:
        return {"path": None, "exists": False, "bytes": 0}
    exists = os.path.exists(path)
    return {"path": path, "exists": exists,
            "bytes": os.path.getsize(path) if exists and os.path.isfile(path) else
            (_dir_bytes(path) if exists else 0)}


def _dir_bytes(root: str) -> int:
    total = 0
    for r, _dirs, files in os.walk(root):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(r, fn))
            except OSError:
                pass
    return total


def model_cache_dir() -> str:
    """fastembed's cache, mirroring its own default exactly:
    FASTEMBED_CACHE_PATH env, else <tempdir>/fastembed_cache."""
    import tempfile
    return os.environ.get(
        "FASTEMBED_CACHE_PATH",
        os.path.join(tempfile.gettempdir(), "fastembed_cache"))


def _pending_flag_path() -> str:
    return os.environ.get("ALLUVIA_PENDING_FLAG",
                          os.path.expanduser("~/.alluvia/digest-pending"))


def storage_report(repo) -> dict:
    store = repo.conn.execute("PRAGMA database_list").fetchone()[2]

    classes = {c: {"rows": 0, "content_bytes": 0}
               for c in ("raw", "derived", "judgments")}
    have = {r[0] for r in repo.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for table, (cls, size_expr) in _CLASSES.items():
        if table not in have:
            continue
        rows = repo.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        classes[cls]["rows"] += rows
        if size_expr and rows:
            got = repo.conn.execute(
                f"SELECT {size_expr} FROM {table}").fetchone()[0]
            classes[cls]["content_bytes"] += int(got or 0)

    cfg = config.config_path()
    paths = {
        "config": {**_file_entry(cfg),
                   "mode": (oct(os.stat(cfg).st_mode & 0o777)[2:]
                            if os.path.exists(cfg) else None)},
        "store": _file_entry(store),
        "store_wal": _file_entry(store + "-wal"),
        "store_shm": _file_entry(store + "-shm"),
        "pending_flag": _file_entry(_pending_flag_path()),
        "model_cache": _file_entry(model_cache_dir()),
    }

    from alluvia.lockfile import acquire, holder_pid
    lock_path = store + ".refresh.lock"
    probe = acquire(lock_path)
    if probe is not None:
        probe.release()
        lock_pid = None
    else:
        lock_pid = holder_pid(lock_path)

    from alluvia.web import looks_like_alluvia
    dashboard = 8177 if looks_like_alluvia(8177, timeout=0.3) else None

    return {"paths": paths, "data_classes": classes,
            "live": {"refresh_lock_pid": lock_pid, "dashboard_port": dashboard}}
