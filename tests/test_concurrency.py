"""Concurrent sessions must not interfere: WAL journal, single-writer
refresh lock, dashboard port handling."""
import os
import sqlite3

from alluvia.store.db import connect, init_schema


def test_connect_enables_wal_and_busy_timeout(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 10000


def test_reader_not_blocked_by_open_write_transaction(tmp_path):
    db = str(tmp_path / "t.db")
    w = connect(db)
    init_schema(w, embed_dim=8)
    w.execute("BEGIN IMMEDIATE")
    w.execute("INSERT INTO meta(key, value) VALUES ('k', 'v')")
    r = connect(db)                       # second connection, same store
    # under a rollback journal this read would hit "database is locked"
    assert r.execute("SELECT COUNT(*) FROM raw_sessions").fetchone()[0] == 0
    w.rollback()


def test_existing_rollback_journal_store_upgrades(tmp_path):
    db = str(tmp_path / "t.db")
    legacy = sqlite3.connect(db)
    legacy.execute("PRAGMA journal_mode=DELETE")
    legacy.execute("CREATE TABLE x(i)")
    legacy.commit()
    legacy.close()
    conn = connect(db)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_lock_acquire_and_second_acquire_fails(tmp_path):
    from alluvia.lockfile import acquire, holder_pid
    p = str(tmp_path / "r.lock")
    h1 = acquire(p)
    assert h1 is not None
    assert holder_pid(p) == os.getpid()
    assert acquire(p) is None             # separate fd, same process: held
    h1.release()
    h2 = acquire(p)
    assert h2 is not None                 # released -> acquirable again
    h2.release()


def test_refresh_exits_zero_when_lock_held(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    import alluvia.cli as cli
    from alluvia import config
    from alluvia.lockfile import acquire
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    held = acquire(config.db_path() + ".refresh.lock")   # simulate another refresh
    r = CliRunner().invoke(cli.app, ["refresh"])
    assert r.exit_code == 0
    assert "already running" in r.output and str(os.getpid()) in r.output
    held.release()


def test_holder_pid_readable_while_lock_held(tmp_path):
    """Regression: the pid must be readable by a separate reader even while
    the lock is held — on Windows the lock byte-range would block reading it
    out of the locked file, so the pid lives in an unlocked sidecar."""
    from alluvia.lockfile import acquire, holder_pid
    p = str(tmp_path / "r.lock")
    h = acquire(p)
    try:
        assert holder_pid(p) == os.getpid()      # readable concurrently with the lock
    finally:
        h.release()
    assert holder_pid(p) is None                 # sidecar cleaned on release
