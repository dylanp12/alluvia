from alluvia.store.db import connect, init_schema
from alluvia.models import Link, Theme


def test_migration_is_idempotent_and_adds_m2a_objects(tmp_path):
    p = str(tmp_path / "t.db")
    conn = connect(p)
    init_schema(conn, embed_dim=8)
    init_schema(conn, embed_dim=8)          # run twice: must not raise
    names = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    assert {"links", "theme_status_cache"} <= names
    cols = {r[1] for r in conn.execute("PRAGMA table_info(themes)")}
    assert "status" in cols


def _link(lid, w, user="local"):
    return Link(id=lid, user_id=user, from_note_id="note:a", to_note_id="note:b",
                from_theme_id="theme:0", to_theme_id="theme:1",
                kind="cross_source_surprise", weight=w)


def test_links_replace_list_ordered_and_scoped(repo):
    repo.replace_links("local", [_link("link:1", 0.5), _link("link:2", 0.9)])
    repo.replace_links("other", [_link("link:3", 0.1, user="other")])
    got = repo.list_links("local")
    assert [l.id for l in got] == ["link:2", "link:1"]        # weight desc
    assert repo.list_links("local", limit=1)[0].id == "link:2"
    repo.set_link_why("local", "link:2", "because X")
    assert repo.list_links("local", limit=1)[0].why == "because X"


def test_status_cache_roundtrip_and_scope(repo):
    assert repo.get_status_cache("local", "h1") is None
    repo.set_status_cache("local", "h1", "open")
    assert repo.get_status_cache("local", "h1") == "open"
    assert repo.get_status_cache("other", "h1") is None


def test_theme_status_persists(repo):
    t = Theme(id="theme:0", user_id="local", label="L", summary="S",
              note_ids=["note:a"], session_count=2, source_count=1, status="open")
    repo.replace_themes("local", [t])
    assert repo.list_themes("local")[0].status == "open"
