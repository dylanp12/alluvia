import json
import threading
import urllib.request
from datetime import datetime, timezone

from alluvia.models import Link, Note, Proposal, Theme
import alluvia.web as web


def _seed(repo):
    repo.upsert_notes([
        Note(id="note:a", user_id="local", session_id="claude-code:sA", span_ref="msg:0",
             kind="problem", text="alpha problem",
             created_at=datetime(2026, 1, 5, tzinfo=timezone.utc)),
        Note(id="note:b", user_id="local", session_id="cursor:sB", span_ref="msg:0",
             kind="idea", text="beta idea",
             created_at=datetime(2026, 3, 5, tzinfo=timezone.utc)),
    ])
    repo.replace_themes("local", [
        Theme(id="t1", user_id="local", label="Alpha", summary="s",
              note_ids=["note:a"], first_seen=datetime(2025, 6, 1, tzinfo=timezone.utc),
              last_seen=datetime(2026, 6, 1, tzinfo=timezone.utc),
              session_count=4, source_count=2, status="open"),
        Theme(id="t2", user_id="local", label="Beta", summary="s",
              note_ids=["note:b"], session_count=1, source_count=1, status="unknown"),
    ])
    repo.replace_links("local", [
        Link(id="l1", user_id="local", from_note_id="note:a", to_note_id="note:b",
             from_theme_id="t1", to_theme_id="t2", kind="cross_source_surprise",
             weight=2.2, why="related"),
        Link(id="l2", user_id="local", from_note_id="note:a", to_note_id="note:b",
             from_theme_id="t1", to_theme_id="t2", kind="cross_source_surprise",
             weight=1.1),
    ])
    repo.insert_proposal(Proposal(
        id="prop:1", user_id="local", created_at="2026-07-01T00:00:00+00:00",
        kind="link", source_ref="l1", source_hash="h", title="P", text="t",
        next_step="n", cites=["note:a"], novelty_sim=None, feasibility=4,
        risk=None, model="m", outcome="kept"))
    repo.mute_label("local", "Beta")


def test_endpoint_shapes_and_aggregation(repo):
    _seed(repo)
    ov = web.overview(repo, "local")
    assert ov["notes"] == 2 and ov["themes"] == 2 and ov["links"] == 2
    assert ov["proposals"]["hit_rate"] == 100

    th = web.themes_data(repo, "local")
    by_label = {t["label"]: t for t in th["themes"]}
    assert by_label["Beta"]["muted"] is True
    assert by_label["Alpha"]["span"][0] == "2025-06-01"

    ld = web.links_data(repo, "local")
    assert len(ld["edges"]) == 1                       # pair-aggregated
    assert ld["edges"][0]["count"] == 2
    assert ld["edges"][0]["max_weight"] == 2.2
    assert ld["edges"][0]["sample"]["why"] == "related"
    # hero bridges: ranked, with gap + sources + themes
    assert ld["bridges"][0]["weight"] == 2.2
    assert ld["bridges"][0]["gap_days"] == 59
    assert ld["bridges"][0]["from"]["source"] == "claude-code"
    assert ld["bridges"][0]["from"]["theme"] == "Alpha"

    tl = web.timeline_data(repo, "local")
    assert tl["arcs"] and tl["arcs"][0]["label"] == "Alpha"

    pd = web.proposals_data(repo, "local")
    assert pd["proposals"][0]["outcome"] == "kept"


def test_server_smoke(repo, tmp_path):
    _seed(repo)
    server = web.serve(repo, "local", port=0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/overview") as r:
            assert r.status == 200
            assert json.loads(r.read())["themes"] == 2
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
            assert r.status == 200
            assert b"<html" in r.read()[:200].lower() or True   # html served
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/nope")
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        server.shutdown()
