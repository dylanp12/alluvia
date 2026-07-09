import numpy as np
import pytest
from alluvia.store.db import connect, init_schema
from alluvia.store.vector import NumpyIndex, SqliteVecIndex, make_index


def _conn(tmp_path, dim=8):
    conn = connect(str(tmp_path / "v.db"))
    init_schema(conn, embed_dim=dim)
    return conn


def _seed(conn, rows):          # rows: [(user, note_id, vec)]
    for user, nid, vec in rows:
        arr = np.asarray(vec, dtype="float32")
        conn.execute(
            "INSERT INTO note_embeddings(user_id,note_id,dim,vec) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id,note_id) DO UPDATE SET dim=excluded.dim, vec=excluded.vec",
            (user, nid, arr.shape[0], arr.tobytes()))
    conn.commit()


ROWS = [
    ("local", "note:a", [1.0, 0.0] + [0.0] * 6),
    ("local", "note:b", [0.0, 1.0] + [0.0] * 6),
    ("other", "note:c", [1.0, 0.0] + [0.0] * 6),
]


def _protocol_suite(index):
    hits = index.search("local", [0.9, 0.1] + [0.0] * 6, k=2)
    assert hits[0][0] == "note:a"                       # nearest first
    assert {h[0] for h in hits} == {"note:a", "note:b"}  # user-scoped: no note:c
    assert index.search("nobody", [1.0] + [0.0] * 7, k=3) == []


def test_numpy_index_protocol(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn, ROWS)
    _protocol_suite(NumpyIndex(conn))


def test_sqlite_vec_index_protocol_and_rebuild(tmp_path):
    conn = _conn(tmp_path)
    _seed(conn, ROWS)
    try:
        idx = SqliteVecIndex(conn, dim=8)               # init rebuilds from note_embeddings
    except RuntimeError:
        pytest.skip("sqlite-vec extension unavailable in this environment")
    _protocol_suite(idx)
    # incremental upsert stays in sync
    idx.upsert("local", "note:d", [0.7, 0.7] + [0.0] * 6)
    assert idx.search("local", [0.7, 0.7] + [0.0] * 6, k=1)[0][0] == "note:d"


def test_make_index_env_selection_and_fallback(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    monkeypatch.setenv("ALLUVIA_VECTOR_BACKEND", "numpy")
    assert isinstance(make_index(conn, dim=8), NumpyIndex)
    monkeypatch.delenv("ALLUVIA_VECTOR_BACKEND", raising=False)
    idx = make_index(conn, dim=8)                        # default sqlite-vec...
    assert isinstance(idx, (SqliteVecIndex, NumpyIndex))  # ...or logged numpy fallback


def test_repo_search_routes_through_index(repo):
    from alluvia.models import Note
    repo.upsert_notes([Note(id="note:a", user_id="local", session_id="s", span_ref="",
                            kind="idea", text="alpha", created_at=None)])
    repo.set_embedding("local", "note:a", [1.0, 0.0] + [0.0] * 6)
    assert repo.search_notes("local", [1.0, 0.0] + [0.0] * 6, k=1)[0][0] == "note:a"
