"""Recall: the front door. Retrieval-only fusion over notes, themes, links,
and status into a few high-signal, cited hits — plus a paste-ready handoff
for whatever assistant you're in right now.

Zero LLM spend by design: ranking is hybrid retrieval you already computed —
vectors for meaning plus an exact-match channel (FTS5) for the queries
embeddings go blind on: error strings, file paths, identifiers — fused on
the cosine scale. "Why" is assembled from stored evidence (cached link whys,
match counts, time gaps), and the git cross-reference reads `git log`
locally. Recall works even when the last refresh was degraded — it says so
instead of staying quiet."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone

from alluvia.models import to_utc
from alluvia.temporal import TimeScope, parse_time_scope

SEARCH_K = 25
SIM_FLOOR = 0.15          # dense entrants below this cosine are junk
LEX_SIM_CEIL = 0.95       # a top lexical match enters just below a perfect cosine
LEX_SIM_STEP = 0.04       # ...decaying by BM25 rank
LEX_BONUS = 0.05          # matching BOTH channels breaks ties toward the exact hit
RECENCY_EPS = 0.02        # freshness is a TIE-BREAK, never a decay: a stale
RECENCY_HALF_LIFE_DAYS = 28.0   # bridge must still outrank a weak fresh match
_GIT_LOG_N = 300
_GIT_MIN_OVERLAP = 3


@dataclass
class RecallHit:
    kind: str                       # theme | connection | note
    title: str
    summary: str
    why: str
    score: float
    status: str | None = None
    date_range: str | None = None
    sources: list[str] = field(default_factory=list)
    cites: list[str] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)   # {note, quote, source}
    git_ref: str | None = None


def _note_source(n) -> str:
    tool = n.session_id.split(":", 1)[0]
    date = f" · {to_utc(n.created_at).date()}" if n.created_at else ""
    return f"{tool}{date} · session {n.session_id}"


def _span(t) -> str | None:
    if t.first_seen and t.last_seen:
        return f"{to_utc(t.first_seen).date()}→{to_utc(t.last_seen).date()}"
    return None


def recall(repo, embedder, user_id: str, query: str, limit: int = 5,
           git_root: str | None = None,
           now: datetime | None = None) -> list[RecallHit]:
    notes = {n.id: n for n in repo.get_notes(user_id)}
    if not notes:
        return []
    scope = parse_time_scope(query, now=now)
    q = scope.cleaned if scope and scope.cleaned.strip() else query
    dense = [(nid, s) for nid, s in
             repo.search_notes(user_id, embedder.embed([q])[0], k=SEARCH_K)
             if nid in notes and s > SIM_FLOOR]
    lex_search = getattr(repo, "search_notes_lexical", None)
    lex = [(nid, s) for nid, s in
           (lex_search(user_id, q, k=SEARCH_K) if lex_search else [])
           if nid in notes]
    if scope:
        # an explicit time expression is a constraint, not a hint: hits
        # outside the window are wrong answers, and empty is honest
        dense = [(nid, s) for nid, s in dense if _in_scope(notes[nid], scope)]
        lex = [(nid, s) for nid, s in lex if _in_scope(notes[nid], scope)]
    hot = _fuse(dense, lex)
    if not hot:
        return []
    _boost_fresh(hot, notes, now)

    hits: list[RecallHit] = []

    themes = repo.list_themes(user_id)
    theme_hits = []
    for t in themes:
        matched = [nid for nid in t.note_ids if nid in hot]
        if not matched:
            continue
        strength = sum(hot[nid] for nid in matched)
        example = notes[matched[0]].text
        why = (f"{len(matched)} of your prior notes match — e.g. “{example}”"
               + (f"; thread status: {t.status}" if t.status else ""))
        theme_hits.append(RecallHit(
            kind="theme", title=t.label, summary=t.summary or example,
            why=why, score=strength, status=t.status, date_range=_span(t),
            sources=sorted({_note_source(notes[nid]) for nid in matched}),
            cites=matched))
    theme_hits.sort(key=lambda h: -h.score)
    hits.extend(theme_hits[: max(1, limit - 1)])

    for l in repo.list_links(user_id, limit=200):
        if l.from_note_id in hot or l.to_note_id in hot:
            a, b = notes.get(l.from_note_id), notes.get(l.to_note_id)
            if not a or not b:
                continue
            gap = ""
            if a.created_at and b.created_at:
                days = abs((to_utc(a.created_at) - to_utc(b.created_at)).days)
                gap = f" · {days // 30} months apart" if days >= 60 else ""
            tools = {a.session_id.split(':', 1)[0], b.session_id.split(':', 1)[0]}
            why = l.why or (f"bridge across {' ↔ '.join(sorted(tools))}{gap}")
            hits.append(RecallHit(
                kind="connection",
                title=f"{a.text[:60]} ↔ {b.text[:60]}",
                summary=b.text, why=why,
                score=l.weight + max(hot.get(l.from_note_id, 0),
                                     hot.get(l.to_note_id, 0)),
                sources=[_note_source(a), _note_source(b)],
                cites=[l.from_note_id, l.to_note_id]))

    cited = {c for h in hits for c in h.cites}
    for nid, s in sorted(hot.items(), key=lambda kv: -kv[1]):
        if nid not in cited and len(hits) < limit + 2:
            n = notes[nid]
            hits.append(RecallHit(
                kind="note", title=n.text[:70], summary=n.text,
                why=f"direct match ({n.kind})", score=s * 0.8,
                sources=[_note_source(n)], cites=[nid]))

    hits.sort(key=lambda h: -h.score)
    out, seen_kinds = [], set()
    for h in hits:                       # light diversity: a bridge earns a slot
        if len(out) >= limit:
            if "connection" not in seen_kinds:
                bridge = next((x for x in hits if x.kind == "connection"), None)
                if bridge and bridge not in out:
                    out[-1] = bridge
                    seen_kinds.add("connection")
            break
        out.append(h)
        seen_kinds.add(h.kind)

    _attach_receipts(out, repo, user_id, notes)
    if git_root:
        _attach_git_refs(out, git_root)
    return out


RECEIPTS_PER_HIT = 2


def _attach_receipts(hits: list[RecallHit], repo, user_id: str, notes) -> None:
    """The verbatim quote behind each hit's top cites — the receipt that
    makes an answer checkable at a glance. Stores without the seam (no raw
    sessions, no synced excerpts) yield receiptless hits, never errors."""
    getter = getattr(repo, "note_excerpt", None)
    if getter is None:
        return
    for h in hits:
        for nid in h.cites[:RECEIPTS_PER_HIT]:
            n = notes.get(nid)
            quote = getter(user_id, n) if n else None
            if quote:
                h.receipts.append({"note": nid, "quote": quote,
                                   "source": _note_source(n)})


def _in_scope(note, scope: TimeScope) -> bool:
    """Undated notes can't prove membership in a window — excluded."""
    if note.created_at is None:
        return False
    dt = to_utc(note.created_at)
    return ((scope.start is None or dt >= scope.start)
            and (scope.end is None or dt < scope.end))


def _boost_fresh(hot: dict[str, float], notes, now: datetime | None) -> None:
    """+ε for recent notes so equal matches lead with the newest evidence.
    Capped at RECENCY_EPS: freshness breaks ties, it never buries the
    14-month-old rediscovery that is the whole point of this product."""
    ref = to_utc(now) if now else datetime.now(timezone.utc)
    for nid in hot:
        dt = notes[nid].created_at
        if dt is None:
            continue
        age_days = max(0.0, (ref - to_utc(dt)).total_seconds() / 86400.0)
        hot[nid] += RECENCY_EPS * 2.0 ** (-age_days / RECENCY_HALF_LIFE_DAYS)


def _fuse(dense: list[tuple[str, float]],
          lex: list[tuple[str, float]]) -> dict[str, float]:
    """Hybrid admission on the cosine scale the surfaces were tuned for:
    dense entrants keep their similarity untouched; a lexical match admits
    a note the embedder missed at just-below-top strength; matching in BOTH
    channels adds a small rank-aware boost so the exact hit breaks ties.
    With no lexical hits this is exactly the old dense-only behavior."""
    hot = dict(dense)
    for rank, (nid, _bm25) in enumerate(lex):
        mapped = max(LEX_SIM_CEIL - LEX_SIM_STEP * rank, SIM_FLOOR + 0.01)
        if nid in hot:
            hot[nid] = min(1.2, max(hot[nid], mapped) + LEX_BONUS / (rank + 1))
        else:
            hot[nid] = mapped
    return hot


_word = re.compile(r"[a-z]{3,}")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "your"}


def _tokens(text: str) -> set[str]:
    return {w for w in _word.findall(text.lower())} - _STOP


def _attach_git_refs(hits: list[RecallHit], git_root: str) -> None:
    """Conservative cross-reference: a commit message sharing enough words
    with a hit earns a 'possibly implemented' label — a pointer to verify,
    never a claim."""
    try:
        r = subprocess.run(["git", "log", "--oneline", f"-{_GIT_LOG_N}"],
                           cwd=git_root, capture_output=True, text=True,
                           timeout=5)
        lines = r.stdout.splitlines() if r.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return
    commits = [(ln.split(" ", 1) + [""])[:2] for ln in lines if ln.strip()]
    for h in hits:
        want = _tokens(h.title + " " + h.summary)
        best = None
        for sha, msg in commits:
            overlap = len(want & _tokens(msg))
            if overlap >= _GIT_MIN_OVERLAP and (best is None or overlap > best[0]):
                best = (overlap, sha, msg)
        if best:
            h.git_ref = f"possibly implemented in {best[1]} — “{best[2]}”"
            if h.status == "open":
                h.why += " · a local commit may have addressed this"


def build_handoff(query: str, hits: list[RecallHit]) -> str:
    """Paste-ready context block for the assistant you're in right now."""
    if not hits:
        return f"(alluvia: no prior context found for “{query}”)"
    lines = [f"Relevant prior context from alluvia (query: “{query}”):", ""]
    for i, h in enumerate(hits, 1):
        status = f" [{h.status}]" if h.status else ""
        lines.append(f"{i}. {h.title}{status} — {h.summary}")
        lines.append(f"   why: {h.why}")
        if h.receipts:
            lines.append(f'   receipt: "{h.receipts[0]["quote"][:200]}"')
        if h.git_ref:
            lines.append(f"   {h.git_ref}")
        lines.append(f"   sources: {'; '.join(h.sources)}")
    lines += ["",
              "Treat this as prior context, not ground truth — verify against "
              "the current code.",
              "cites: " + ", ".join(sorted({c for h in hits for c in h.cites}))]
    return "\n".join(lines)


def recall_warnings(repo) -> list[str]:
    raw = repo.get_meta("last_refresh")
    if not raw:
        return ["no refresh has run yet — recall sees only what's been distilled"]
    try:
        if json.loads(raw).get("degraded"):
            return ["last refresh was degraded by provider rate limits — "
                    "some labels/statuses may be incomplete"]
    except ValueError:
        pass
    return []
