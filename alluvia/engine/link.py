from __future__ import annotations
import numpy as np
from alluvia.models import Link, Note, link_id, to_utc

FLOOR = 0.6
W_TIME = 1.0
W_SRC = 0.5
TOP_K = 200


def _days_apart(a: Note, b: Note) -> float:
    if a.created_at and b.created_at:
        return abs((to_utc(a.created_at) - to_utc(b.created_at)).days)
    return 0.0


def _source_of(note: Note) -> str:
    return note.session_id.split(":", 1)[0]


def compute_links(user_id: str, notes_by_id: dict[str, Note], ids: list[str],
                  mat, note_theme: dict[str, str], *,
                  floor: float = FLOOR, w_time: float = W_TIME,
                  w_src: float = W_SRC, top_k: int = TOP_K,
                  chunk_size: int = 1024) -> list[Link]:
    """Cross-theme surprise edges: similar (>=floor) notes in DIFFERENT themes,
    weighted by cosine similarity x time distance. Similarities are computed in
    row blocks so memory stays bounded as the corpus grows."""
    n = len(ids)
    if n < 2:
        return []
    X = np.asarray(mat, dtype="float64")
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    candidates = []
    for start in range(0, n, chunk_size):
        stop = min(start + chunk_size, n)
        block = X[start:stop] @ X.T                    # (block, n) — bounded memory
        for i in range(start, stop):
            row = block[i - start]
            for j in range(i + 1, n):
                a_id, b_id = ids[i], ids[j]
                if note_theme.get(a_id) == note_theme.get(b_id):
                    continue                              # same theme -> not surprising
                sim = float(row[j])
                if sim < floor:
                    continue
                gap = _days_apart(notes_by_id[a_id], notes_by_id[b_id])
                diff_src = _source_of(notes_by_id[a_id]) != _source_of(notes_by_id[b_id])
                weight = sim * (1.0 + w_time * min(gap / 90.0, 1.0)
                                + w_src * (1.0 if diff_src else 0.0))
                candidates.append((weight, a_id, b_id))
    candidates.sort(key=lambda c: c[0], reverse=True)
    out = []
    for weight, a_id, b_id in candidates[:top_k]:
        out.append(Link(
            id=link_id(a_id, b_id), user_id=user_id,
            from_note_id=a_id, to_note_id=b_id,
            from_theme_id=note_theme.get(a_id), to_theme_id=note_theme.get(b_id),
            kind="cross_source_surprise", weight=weight, why=None,
        ))
    return out
