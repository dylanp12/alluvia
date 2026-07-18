"""VectorIndex seam. Source of truth is ALWAYS note_embeddings; any backend's
index structure is derived and rebuildable, so switching backends never
migrates data. Default backend sqlite-vec; numpy fallback if the loadable
extension can't initialize (logged once)."""
from __future__ import annotations
import logging
import os
import sqlite3
from typing import Protocol

import numpy as np

log = logging.getLogger(__name__)


class VectorIndex(Protocol):
    def upsert(self, user_id: str, note_id: str, vec: list[float]) -> None: ...
    def delete(self, user_id: str, note_id: str) -> None: ...
    def search(self, user_id: str, vec: list[float], k: int) -> list[tuple[str, float]]: ...


class NumpyIndex:
    """Brute-force cosine over note_embeddings (reads SoT directly; no state)."""
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def upsert(self, user_id: str, note_id: str, vec: list[float]) -> None:
        pass                                    # reads SoT directly; nothing to maintain

    def delete(self, user_id: str, note_id: str) -> None:
        pass

    def search(self, user_id: str, vec: list[float], k: int) -> list[tuple[str, float]]:
        rows = self.conn.execute(
            "SELECT note_id, vec FROM note_embeddings WHERE user_id=? ORDER BY note_id",
            (user_id,)).fetchall()
        if not rows:
            return []
        ids = [r[0] for r in rows]
        mat = np.stack([np.frombuffer(r[1], dtype="float32") for r in rows])
        q = np.asarray(vec, dtype="float32")
        qn = q / (np.linalg.norm(q) + 1e-9)
        mn = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9)
        sims = mn @ qn
        order = np.argsort(-sims)[:k]
        return [(ids[i], float(sims[i])) for i in order]


class SqliteVecIndex:
    """sqlite-vec vec0 virtual table in the same DB file; rebuilt from
    note_embeddings whenever row counts disagree. Raises RuntimeError if the
    extension can't load (make_index catches -> numpy fallback)."""
    def __init__(self, conn: sqlite3.Connection, dim: int):
        self.conn = conn
        self.dim = dim
        try:
            import sqlite_vec
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS note_vec USING vec0("
                f"user_id TEXT partition key, note_id TEXT, embedding float[{dim}])")
        except Exception as e:
            raise RuntimeError(f"sqlite-vec unavailable: {e}") from e
        self._sync()

    def _sync(self) -> None:
        n_vec = self.conn.execute("SELECT count(*) FROM note_vec").fetchone()[0]
        n_src = self.conn.execute("SELECT count(*) FROM note_embeddings").fetchone()[0]
        if n_vec == n_src:
            return
        log.info("note_vec rebuild: %s -> %s rows", n_vec, n_src)
        self.conn.execute("DELETE FROM note_vec")
        for user_id, note_id, blob in self.conn.execute(
                "SELECT user_id, note_id, vec FROM note_embeddings"):
            self.conn.execute(
                "INSERT INTO note_vec(user_id, note_id, embedding) VALUES (?,?,?)",
                (user_id, note_id, blob))
        self.conn.commit()

    def upsert(self, user_id: str, note_id: str, vec: list[float]) -> None:
        arr = np.asarray(vec, dtype="float32")
        self.conn.execute("DELETE FROM note_vec WHERE user_id=? AND note_id=?",
                          (user_id, note_id))
        self.conn.execute(
            "INSERT INTO note_vec(user_id, note_id, embedding) VALUES (?,?,?)",
            (user_id, note_id, arr.tobytes()))
        self.conn.commit()

    def delete(self, user_id: str, note_id: str) -> None:
        self.conn.execute("DELETE FROM note_vec WHERE user_id=? AND note_id=?",
                          (user_id, note_id))
        self.conn.commit()

    def search(self, user_id: str, vec: list[float], k: int) -> list[tuple[str, float]]:
        q = np.asarray(vec, dtype="float32")
        rows = self.conn.execute(
            "SELECT note_id, distance FROM note_vec "
            "WHERE user_id = ? AND embedding MATCH ? AND k = ? ORDER BY distance",
            (user_id, q.tobytes(), k)).fetchall()
        # vec0 returns L2 distance; our embeddings are normalized, so
        # cos = 1 - d^2/2 — both backends speak cosine (higher = closer)
        return [(r[0], float(1.0 - (r[1] * r[1]) / 2.0)) for r in rows]


def make_index(conn: sqlite3.Connection, dim: int) -> VectorIndex:
    backend = os.environ.get("ALLUVIA_VECTOR_BACKEND", "sqlite-vec")
    if backend == "numpy":
        return NumpyIndex(conn)
    try:
        return SqliteVecIndex(conn, dim=dim)
    except RuntimeError as e:
        log.warning("falling back to numpy vector search (%s)", e)
        return NumpyIndex(conn)
