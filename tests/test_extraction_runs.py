from datetime import datetime, timezone

from alluvia.models import ExtractionRun, Note


def _run(rid="run:abc", model="m-live"):
    return ExtractionRun(id=rid, user_id="local", session_id="claude-code:s1",
                         stage="distill", model=model, pipeline_version=3,
                         prompt_hash="ph", created_at="2026-07-17T00:00:00+00:00")


def test_record_and_list_runs(repo):
    repo.record_extraction_run(_run())
    repo.record_extraction_run(_run())          # idempotent on same id
    runs = repo.list_extraction_runs("local")
    assert len(runs) == 1
    assert runs[0].model == "m-live" and runs[0].stage == "distill"


def test_notes_round_trip_run_id(repo):
    n = Note(id="note:1", user_id="local", session_id="claude-code:s1",
             span_ref="msg:0", kind="problem", text="x",
             created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
             run_id="run:abc")
    repo.upsert_notes([n])
    got = repo.get_notes("local")[0]
    assert got.run_id == "run:abc"
    assert got.pipeline_version is not None      # populated from PIPELINE_VERSION
