"""Substrate slice: graph tables exist and legacy stores upgrade in place."""
from alluvia.store.db import connect, init_schema


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_substrate_tables_exist(repo):
    for table, needed in {
        "extraction_runs": {"id", "user_id", "session_id", "stage", "model",
                             "pipeline_version", "prompt_hash", "created_at"},
        "events": {"id", "user_id", "event_type", "relation", "participants_json",
                    "event_time_start", "event_time_end", "derived_at", "run_id",
                    "confidence", "human_confirmed", "evidence_json",
                    "derivation_json"},
        "edges": {"id", "user_id", "subject_id", "relation", "object_id",
                   "event_id", "weight"},
        "candidates": {"id", "user_id", "relation", "subject_id", "object_id",
                        "score", "uncertainty_json", "evidence_json", "status",
                        "created_at", "policy_version"},
        "slates": {"id", "user_id", "surface", "policy_version", "created_at",
                    "items_json"},
    }.items():
        assert needed <= _cols(repo.conn, table), table


def test_notes_gain_run_id_column(repo):
    assert "run_id" in _cols(repo.conn, "notes")


def test_legacy_store_upgrades(tmp_path):
    conn = connect(str(tmp_path / "old.db"))
    conn.executescript(
        "CREATE TABLE notes (id TEXT NOT NULL, user_id TEXT NOT NULL, "
        "session_id TEXT NOT NULL, span_ref TEXT, kind TEXT, text TEXT NOT NULL, "
        "created_at TEXT, canonical_id TEXT, pipeline_version INTEGER NOT NULL, "
        "PRIMARY KEY (user_id, id));")
    init_schema(conn, embed_dim=8)
    assert "run_id" in _cols(conn, "notes")
    assert "extraction_runs" in {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
