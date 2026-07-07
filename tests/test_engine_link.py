from datetime import datetime
from alluvia.models import Note
from alluvia.engine.link import compute_links


def _note(nid, theme_day):        # theme_day: (theme_id, created_day)
    theme, day = theme_day
    return Note(id=nid, user_id="local", session_id="claude-code:s", span_ref="",
                kind="idea", text=nid, created_at=datetime(2026, 1, day))


def test_cross_theme_pair_links_within_theme_pair_does_not():
    # a,b nearly identical & CROSS-theme -> edge ; a,c nearly identical but SAME theme -> no edge
    notes = {"a": _note("a", ("t0", 1)), "b": _note("b", ("t1", 1)),
             "c": _note("c", ("t0", 1))}
    ids = ["a", "b", "c"]
    mat = [[1.0, 0.0], [0.99, 0.01], [0.98, 0.02]]     # all near direction [1,0]
    note_theme = {"a": "t0", "b": "t1", "c": "t0"}
    links = compute_links("local", notes, ids, mat, note_theme, floor=0.6, top_k=50)
    pairs = {frozenset([l.from_note_id, l.to_note_id]) for l in links}
    assert frozenset(["a", "b"]) in pairs        # cross-theme -> linked
    assert frozenset(["a", "c"]) not in pairs     # same theme -> filtered
    assert frozenset(["b", "c"]) in pairs         # cross-theme -> linked


def test_weight_increases_with_time_gap():
    near = {"a": _note("a", ("t0", 1)), "b": _note("b", ("t1", 2))}      # 1 day apart
    far = {"a": _note("a", ("t0", 1)), "b": _note("b", ("t1", 31))}      # 30 days apart
    ids, mat, nt = ["a", "b"], [[1.0, 0.0], [1.0, 0.0]], {"a": "t0", "b": "t1"}
    w_near = compute_links("local", near, ids, mat, nt)[0].weight
    w_far = compute_links("local", far, ids, mat, nt)[0].weight
    assert w_far > w_near


def test_top_k_bound():
    notes, ids, mat, nt = {}, [], [], {}
    for i in range(6):
        nid = f"n{i}"
        notes[nid] = _note(nid, (f"t{i}", 1)); ids.append(nid)
        mat.append([1.0, 0.0]); nt[nid] = f"t{i}"
    links = compute_links("local", notes, ids, mat, nt, top_k=3)
    assert len(links) == 3
