"""Recall: the front door. Retrieval-only fusion over notes, themes, links,
and status into a few high-signal, cited hits — plus a paste-ready handoff
for whatever assistant you're in right now.

Zero LLM spend by design: ranking is vector search you already computed,
"why" is assembled from stored evidence (cached link whys, match counts,
time gaps), and the git cross-reference reads `git log` locally. Recall
works even when the last refresh was degraded — it says so instead of
staying quiet."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from alluvia.models import to_utc

SEARCH_K = 25
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
           git_root: str | None = None) -> list[RecallHit]:
    notes = {n.id: n for n in repo.get_notes(user_id)}
    if not notes:
        return []
    scored = dict(repo.search_notes(user_id, embedder.embed([query])[0],
                                    k=SEARCH_K))
    hot = {nid: s for nid, s in scored.items() if nid in notes and s > 0.15}
    if not hot:
        return []

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

    if git_root:
        _attach_git_refs(out, git_root)
    return out


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
