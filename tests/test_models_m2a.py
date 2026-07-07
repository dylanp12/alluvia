from alluvia.models import Link, Theme, link_id


def test_link_id_is_order_independent():
    assert link_id("note:a", "note:b") == link_id("note:b", "note:a")
    assert link_id("note:a", "note:b") != link_id("note:a", "note:c")


def test_theme_defaults_status_unknown():
    t = Theme(id="theme:0", user_id="local", label="L", summary="S")
    assert t.status == "unknown"


def test_link_construct():
    link = Link(id="link:x", user_id="local", from_note_id="note:a", to_note_id="note:b",
                from_theme_id="theme:0", to_theme_id="theme:1", kind="cross_source_surprise",
                weight=1.2, why=None)
    assert link.weight == 1.2 and link.why is None
