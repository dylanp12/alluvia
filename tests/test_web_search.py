import json
import threading
import urllib.request
from datetime import datetime, timezone

from alluvia.models import Note, Theme
import alluvia.web as web


class _Emb:
    dim = 8

    def embed(self, texts):
        return [([1.0, 0.0] + [0.0] * 6) if "auth" in t.lower()
                else ([0.0, 1.0] + [0.0] * 6) for t in texts]


def _seed(repo):
    repo.upsert_notes([Note(id="note:a", user_id="local",
                            session_id="claude-code:s", span_ref="msg:0",
                            kind="idea", text="auth token rotation idea",
                            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))])
    repo.set_embedding("local", "note:a", [1.0, 0.0] + [0.0] * 6)
    repo.replace_themes("local", [Theme(id="t1", user_id="local",
        label="Auth hygiene", summary="s", note_ids=["note:a"],
        session_count=3, source_count=1, status="open")])


def test_search_returns_theme_and_note_hits(repo):
    _seed(repo)
    out = web.search_data(repo, "local", "auth stuff", embedder=_Emb())
    assert out["themes"][0]["label"] == "Auth hygiene"
    assert out["notes"][0]["id"] == "note:a"
    assert out["notes"][0]["theme"]["label"] == "Auth hygiene"


def test_search_without_embedder_still_matches_themes(repo):
    _seed(repo)
    out = web.search_data(repo, "local", "auth", embedder=None)
    assert out["themes"] and out["notes"] == []


def test_search_endpoint_over_http(repo):
    _seed(repo)
    server = web.serve(repo, "local", port=0, embedder_factory=lambda: _Emb())
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/search?q=auth%20stuff") as r:
            data = json.loads(r.read())
            assert data["notes"] and data["themes"]
    finally:
        server.shutdown()
