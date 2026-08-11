"""Thin dict-row CRUD for the substrate tables. Producers land in later
milestones; SP1 proves storage round-trips."""


def test_events_round_trip(repo):
    repo.insert_events("local", [{
        "id": "ev:0000000000000001", "event_type": "observation",
        "relation": None, "participants": [["observed", "note:1"]],
        "event_time_start": "2026-01-01T00:00:00+00:00", "event_time_end": None,
        "derived_at": None, "run_id": None, "confidence": None,
        "human_confirmed": False, "evidence": ["claude-code:s1/msg:0"],
        "derivation": [],
    }])
    rows = repo.list_events("local")
    assert len(rows) == 1
    assert rows[0]["participants"] == [["observed", "note:1"]]
    assert rows[0]["evidence"] == ["claude-code:s1/msg:0"]
    assert rows[0]["human_confirmed"] is False


def test_edges_round_trip(repo):
    repo.upsert_edges("local", [{
        "id": "edge:1", "subject_id": "note:1", "relation": "ADDRESSES",
        "object_id": "note:2", "event_id": "ev:0000000000000001", "weight": 0.9,
    }])
    repo.upsert_edges("local", [{
        "id": "edge:1", "subject_id": "note:1", "relation": "ADDRESSES",
        "object_id": "note:2", "event_id": None, "weight": 1.0,
    }])
    rows = repo.list_edges("local")
    assert len(rows) == 1 and rows[0]["weight"] == 1.0


def test_candidates_status_filter(repo):
    repo.insert_candidates("local", [
        {"id": "cand:1", "relation": "CONTRADICTS", "subject_id": "a",
         "object_id": "b", "score": 0.7, "uncertainty": {"epistemic": 0.2},
         "evidence": ["s/msg:1"], "status": "pending",
         "created_at": "2026-07-17T00:00:00+00:00", "policy_version": "p0"},
        {"id": "cand:2", "relation": "SUPERSEDES", "subject_id": "c",
         "object_id": "d", "score": 0.9, "uncertainty": None,
         "evidence": [], "status": "confirmed",
         "created_at": "2026-07-17T00:00:00+00:00", "policy_version": "p0"},
    ])
    assert [c["id"] for c in repo.list_candidates("local", status="pending")] == ["cand:1"]
    assert len(repo.list_candidates("local")) == 2
    assert repo.list_candidates("local", status="pending")[0]["uncertainty"] == \
        {"epistemic": 0.2}


def test_slates_round_trip(repo):
    sid = repo.insert_slate("local", surface="digest", policy_version="p0",
                            created_at="2026-07-17T00:00:00+00:00",
                            items=[{"ref": "link:1", "score": 2.5, "rank": 1}])
    slates = repo.list_slates("local", surface="digest")
    assert slates[0]["id"] == sid
    assert slates[0]["items"][0]["ref"] == "link:1"
    assert repo.list_slates("local", surface="propose") == []


def test_candidates_carry_why(repo):
    repo.insert_candidates("local", [
        {"id": "cand:w", "relation": "CONTRADICTS", "subject_id": "a",
         "object_id": "b", "score": 0.8, "uncertainty": None,
         "evidence": [], "status": "pending",
         "created_at": "2026-07-17T00:00:00+00:00", "policy_version": "p0",
         "why": "B reverses the guarantee A relies on"}])
    row = repo.list_candidates("local")[0]
    assert row["why"] == "B reverses the guarantee A relies on"


def test_candidates_why_upgrades_legacy_store(tmp_path):
    from alluvia.store.db import connect, init_schema
    conn = connect(str(tmp_path / "old.db"))
    conn.executescript(
        "CREATE TABLE candidates (id TEXT NOT NULL, user_id TEXT NOT NULL, "
        "relation TEXT NOT NULL, subject_id TEXT NOT NULL, object_id TEXT NOT NULL, "
        "score REAL, uncertainty_json TEXT, evidence_json TEXT NOT NULL DEFAULT '[]', "
        "status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL, "
        "policy_version TEXT, PRIMARY KEY (user_id, id));")
    init_schema(conn, embed_dim=8)
    assert "why" in {r[1] for r in conn.execute("PRAGMA table_info(candidates)")}
