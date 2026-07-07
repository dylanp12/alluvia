from alluvia.store.db import connect, init_schema


def test_schema_creates_expected_tables(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn, embed_dim=8)
    names = {r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'")}
    assert {"raw_sessions", "notes", "note_embeddings", "themes", "meta"} <= names
