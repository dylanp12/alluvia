"""C/Proposal lens: generate grounded next-steps from the map's best material.

Guardrails (spec §3): cite-check -> novelty gate -> feasibility LABELING
(never silent dropping). Rejections are persisted with reasons — they are the
anti-slop corpus. Proposals are judgments (durable, never rebuilt)."""
from __future__ import annotations
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from alluvia.models import Note, Proposal, to_utc
from alluvia.store.repo import Repo

log = logging.getLogger(__name__)

NOVELTY_CEIL = 0.90          # max cosine vs any source note before it's a paraphrase
EXCERPT_CHAR_CAP = 400       # per raw-span excerpt
CONTEXT_CHAR_CAP = 6000      # total grounding context

_GEN_SYSTEM = (
    "You propose ONE new, concrete next step from a developer's own prior notes. "
    "Return JSON {\"title\": short title, \"proposal\": <=120 words building on the "
    "notes but going BEYOND them, \"next_step\": ONE concrete action to start, "
    "\"cites\": [note ids you built on]}. Only cite ids given. Do not restate the "
    "notes; derive something they haven't done yet."
)
_CRITIC_SYSTEM = (
    'Rate this proposal\'s feasibility for a solo developer. Return JSON '
    '{"feasibility": 1-5 (5=clearly doable now), "risk": one sentence on the '
    'biggest practical obstacle}.'
)


@dataclass(frozen=True)
class Candidate:
    kind: str            # link | theme
    source_ref: str
    note_ids: tuple[str, ...]


def _source_hash(notes: list[Note]) -> str:
    parts = sorted(f"{n.id}:{n.text}" for n in notes)
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def candidates(repo: Repo, user_id: str, limit: int = 10) -> list[Candidate]:
    """Top surprise links, then most-circled OPEN themes — minus material
    already proposed-from (source_hash dedup: re-propose only when the
    grounding notes change)."""
    notes = {n.id: n for n in repo.get_notes(user_id)}
    seen = repo.proposal_source_hashes(user_id)
    out: list[Candidate] = []

    for link in repo.list_links(user_id, limit=limit * 2):
        ids = tuple(i for i in (link.from_note_id, link.to_note_id) if i in notes)
        if len(ids) < 2:
            continue
        if _source_hash([notes[i] for i in ids]) in seen:
            continue
        out.append(Candidate(kind="link", source_ref=link.id, note_ids=ids))
        if len(out) >= limit:
            return out

    def span_days(t):
        if t.first_seen and t.last_seen:
            return (to_utc(t.last_seen) - to_utc(t.first_seen)).days
        return 0

    muted = repo.muted_labels(user_id)
    themes = [t for t in repo.list_themes(user_id)
              if t.status == "open" and t.label.lower() not in muted]
    themes.sort(key=lambda t: t.session_count * (span_days(t) + 1), reverse=True)
    for t in themes:
        ids = tuple(i for i in t.note_ids if i in notes)
        if not ids:
            continue
        if _source_hash([notes[i] for i in ids]) in seen:
            continue
        out.append(Candidate(kind="theme", source_ref=t.id, note_ids=ids))
        if len(out) >= limit:
            break
    return out


def _excerpt(repo: Repo, user_id: str, note: Note) -> str | None:
    try:
        from alluvia.distill.scrub import strip_wrappers
        idx = int(note.span_ref.split(":", 1)[1])
        session = repo.get_session(user_id, note.session_id)
        if session and 0 <= idx < len(session.messages):
            return strip_wrappers(session.messages[idx].text)[:EXCERPT_CHAR_CAP]
    except (ValueError, IndexError, AttributeError):
        pass
    return None


def _normalize_cites(cites: list[str], valid_ids: set[str]) -> list[str]:
    """Models cite loosely ('note:x', bare 'x', '[note:x]') — canonicalize to
    known grounding ids; hallucinated ids are dropped (every survivor is real)."""
    by_bare = {v.split(":", 1)[1]: v for v in valid_ids if ":" in v}
    out: list[str] = []
    for c in cites:
        c = str(c).strip().strip("[]")
        if c in valid_ids:
            out.append(c)
        elif c in by_bare:
            out.append(by_bare[c])
    return list(dict.fromkeys(out))          # dedupe, keep order


def _ground(repo: Repo, user_id: str, cand: Candidate,
            notes: dict[str, Note]) -> str:
    lines, total = [], 0
    for nid in cand.note_ids:
        n = notes[nid]
        line = f"[{nid}] ({n.kind}, {n.session_id.split(':', 1)[0]}) {n.text}"
        ex = _excerpt(repo, user_id, n)
        if ex:
            line += f"\n    raw: {ex}"
        if total + len(line) > CONTEXT_CHAR_CAP:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def _prop_id(src_hash: str, title: str) -> str:
    return "prop:" + hashlib.sha256(f"{src_hash}|{title}".encode()).hexdigest()[:8]


def _reject(repo: Repo, user_id: str, cand: Candidate, src_hash: str,
            reason: str, title: str, text: str, model: str) -> None:
    repo.insert_proposal(Proposal(
        id=_prop_id(src_hash, title or reason), user_id=user_id,
        created_at=datetime.now(timezone.utc).isoformat(), kind=cand.kind,
        source_ref=cand.source_ref, source_hash=src_hash, title=title or "(rejected)",
        text=text, next_step="", cites=[], novelty_sim=None, feasibility=None,
        risk=None, model=model, outcome="rejected", reject_reason=reason))


def generate_proposal(repo: Repo, user_id: str, cand: Candidate,
                      gen_llm, critic_llm, embedder,
                      model_name: str = "") -> Proposal | None:
    notes = {n.id: n for n in repo.get_notes(user_id)}
    grounding = [notes[i] for i in cand.note_ids if i in notes]
    if not grounding:
        return None
    src_hash = _source_hash(grounding)

    # GENERATE
    try:
        result = gen_llm.complete_json(_GEN_SYSTEM, _ground(repo, user_id, cand, notes))
    except Exception as e:
        log.warning("propose generation failed for %s (%s)", cand.source_ref, e)
        return None
    if not isinstance(result, dict):
        _reject(repo, user_id, cand, src_hash, "no_cites", "", "", model_name)
        return None
    title = (result.get("title") or "").strip()
    text = (result.get("proposal") or "").strip()
    next_step = (result.get("next_step") or "").strip()
    cites = [c for c in (result.get("cites") or []) if isinstance(c, str)]

    # CITE-CHECK: normalize loose formats, drop hallucinated ids; must have >=1
    # real cite plus substantive text and a next step
    valid_ids = {n.id for n in grounding}
    cites = _normalize_cites(cites, valid_ids)
    if not cites or not text or not next_step:
        _reject(repo, user_id, cand, src_hash, "no_cites", title, text, model_name)
        return None

    # NOVELTY GATE: embed locally, compare to source notes (fail-open on errors)
    novelty_sim = None
    try:
        pvec = np.asarray(embedder.embed([text])[0], dtype="float32")
        pvec = pvec / (np.linalg.norm(pvec) + 1e-9)
        ids, mat = repo.all_embeddings(user_id)
        idx = {nid: i for i, nid in enumerate(ids)}
        sims = []
        for n in grounding:
            if n.id in idx:
                v = np.asarray(mat[idx[n.id]], dtype="float32")
                v = v / (np.linalg.norm(v) + 1e-9)
                sims.append(float(v @ pvec))
        if sims:
            novelty_sim = max(sims)
            if novelty_sim > NOVELTY_CEIL:
                _reject(repo, user_id, cand, src_hash, "paraphrase",
                        title, text, model_name)
                return None
    except Exception as e:
        log.warning("novelty gate skipped for %s (%s)", cand.source_ref, e)

    # FEASIBILITY: labels, never filters
    feasibility, risk = None, None
    try:
        critic = critic_llm.complete_json(
            _CRITIC_SYSTEM, f"{title}\n{text}\nNext step: {next_step}")
        if isinstance(critic, dict):
            f = critic.get("feasibility")
            feasibility = int(f) if isinstance(f, (int, float)) else None
            risk = critic.get("risk")
    except Exception as e:
        log.warning("feasibility critique failed for %s (%s)", cand.source_ref, e)

    proposal = Proposal(
        id=_prop_id(src_hash, title), user_id=user_id,
        created_at=datetime.now(timezone.utc).isoformat(), kind=cand.kind,
        source_ref=cand.source_ref, source_hash=src_hash, title=title, text=text,
        next_step=next_step, cites=cites, novelty_sim=novelty_sim,
        feasibility=feasibility, risk=risk, model=model_name, outcome="pending")
    repo.insert_proposal(proposal)
    return proposal
