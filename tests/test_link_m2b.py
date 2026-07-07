from datetime import datetime
from alluvia.models import Note
from alluvia.engine.link import compute_links


def _note(nid, source, day):
    return Note(id=nid, user_id="local", session_id=f"{source}:s-{nid}", span_ref="",
                kind="idea", text=nid, created_at=datetime(2026, 1, day))


def test_chunked_equals_unchunked():
    notes, ids, mat, nt = {}, [], [], {}
    vecs = [[1.0, 0.02 * i] + [0.0] * 6 for i in range(9)]
    for i in range(9):
        nid = f"n{i}"
        notes[nid] = _note(nid, "claude-code", 1 + i)
        ids.append(nid)
        mat.append(vecs[i])
        nt[nid] = f"t{i % 3}"
    a = compute_links("local", notes, ids, mat, nt, chunk_size=2)
    b = compute_links("local", notes, ids, mat, nt, chunk_size=10**9)
    assert [(l.id, round(l.weight, 9)) for l in a] == [(l.id, round(l.weight, 9)) for l in b]
    assert a                                             # sanity: candidates exist


def test_cross_source_outranks_same_source_at_equal_sim_and_time():
    ids = ["a", "b", "c"]
    mat = [[1.0, 0.0] + [0.0] * 6] * 3                       # identical vectors
    notes = {"a": _note("a", "claude-code", 1),
             "b": _note("b", "chatgpt", 1),                  # cross-source vs a
             "c": _note("c", "claude-code", 1)}              # same-source vs a
    nt = {"a": "t0", "b": "t1", "c": "t2"}                   # all cross-theme
    links = compute_links("local", notes, ids, mat, nt)
    by_pair = {frozenset([l.from_note_id, l.to_note_id]): l.weight for l in links}
    assert by_pair[frozenset(["a", "b"])] > by_pair[frozenset(["a", "c"])]
