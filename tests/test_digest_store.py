from alluvia.models import Theme


def _items():
    return [{"kind": "connection", "ref": "link:1", "theme_ref": "t1", "snapshot": "A↔B"},
            {"kind": "nudge", "ref": "t2", "theme_ref": "t2", "snapshot": "open thing"}]


def test_insert_latest_items_roundtrip(repo):
    did = repo.insert_digest("local", "2026-07-04T00:00:00+00:00", _items())
    assert repo.latest_digest("local")[0] == did
    items = repo.digest_items("local", did)
    assert [i["n"] for i in items] == [1, 2]
    assert items[0]["snapshot"] == "A↔B" and items[0]["outcome"] == "shown"


def test_shown_refs_window_and_dismissal_counts(repo):
    d1 = repo.insert_digest("local", "2026-06-01T00:00:00+00:00",
                            [{"kind": "nudge", "ref": "tOld", "theme_ref": "tOld",
                              "snapshot": "x"}])
    d2 = repo.insert_digest("local", "2026-06-08T00:00:00+00:00",
                            [{"kind": "nudge", "ref": "tNew", "theme_ref": "tNew",
                              "snapshot": "y"}])
    d3 = repo.insert_digest("local", "2026-06-15T00:00:00+00:00", _items())
    assert repo.shown_refs("local", kinds=("nudge",)) == {"tOld", "tNew", "t2"}
    recent = repo.shown_refs("local", kinds=("nudge",), last_n_digests=2)
    assert "tOld" not in recent and "tNew" in recent
    repo.set_digest_item_outcome("local", d1, 1, "dismissed")
    repo.set_digest_item_outcome("local", d2, 1, "dismissed")
    counts = repo.dismissed_theme_counts("local")
    assert counts == {"tOld": 1, "tNew": 1}


def test_digests_survive_map_rebuilds(repo):
    did = repo.insert_digest("local", "2026-07-04T00:00:00+00:00", _items())
    repo.replace_themes("local", [Theme(id="tX", user_id="local", label="L", summary="S")])
    repo.replace_links("local", [])
    assert repo.digest_items("local", did)[0]["snapshot"] == "A↔B"   # snapshot durable
