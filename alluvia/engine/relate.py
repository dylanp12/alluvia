"""Typed-relation pass over surprise links.

An untyped "these two notes are similar across themes" edge becomes a
directional, evidence-bearing relation candidate: A CONTRADICTS B,
A SUPERSEDES B, A ADDRESSES B, A RECURS_AS B — or nothing. Candidates are
predictions with a confidence and a one-sentence why; they live in the
candidates store and are never promoted to facts here. Errors are counted in
the returned stats, never raised — a failed classification costs one edge,
not the pass."""
from __future__ import annotations
import logging
from datetime import datetime

from alluvia.store.repo import Repo

log = logging.getLogger(__name__)

RELATIONS = ("CONTRADICTS", "SUPERSEDES", "ADDRESSES", "RECURS_AS",
             "TRANSFERS_TO")
POLICY_VERSION = "relate-v1"

_SYSTEM = (
    "Two notes from one developer's history, A and B. Classify their "
    "relationship. Return JSON {\"relation\": one of CONTRADICTS (they cannot "
    "both hold) | SUPERSEDES (A replaces/invalidates B) | ADDRESSES (A is a "
    "decision/fix for problem B) | RECURS_AS (A is an earlier occurrence of "
    "the same underlying issue as B) | TRANSFERS_TO (solution/approach A "
    "applies structurally to problem B in a different area) | NONE, "
    "\"confidence\": 0-1, \"why\": ONE short sentence}. Prefer NONE unless "
    "the relation is clearly supported by the texts."
)


def _span(note) -> str:
    return f"{note.session_id}/{note.span_ref}" if note.span_ref \
        else note.session_id


def judge_candidate(repo: Repo, user_id: str, cid: str, verdict: str,
                    now: datetime) -> dict:
    """Relay the user's verdict on a typed finding. keep → the candidate is
    PROMOTED: a confirmed edge plus a human-confirmed judgment event carrying
    the candidate's evidence. dismiss → verdict recorded, nothing promoted.
    Errors as values."""
    import hashlib
    import json as _json
    if verdict not in ("keep", "dismiss"):
        return {"error": "verdict must be 'keep' or 'dismiss'"}
    cand = next((c for c in repo.list_candidates(user_id) if c["id"] == cid),
                None)
    if cand is None:
        return {"error": f"no finding {cid}"}
    if verdict == "dismiss":
        repo.set_candidate_status(user_id, cid, "dismissed")
        return {"id": cid, "status": "dismissed", "promoted": False}

    participants = [["subject", cand["subject_id"]],
                    ["object", cand["object_id"]]]
    payload = _json.dumps(["judgment", cand["relation"], participants,
                            cand["evidence"]], sort_keys=True)
    ev_id = "ev:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    repo.insert_events(user_id, [{
        "id": ev_id, "event_type": "judgment", "relation": cand["relation"],
        "participants": participants, "event_time_start": None,
        "event_time_end": None, "derived_at": now.isoformat(), "run_id": None,
        "confidence": cand["score"], "human_confirmed": True,
        "evidence": cand["evidence"], "derivation": []}])
    repo.upsert_edges(user_id, [{
        "id": f"edge:{cid}", "subject_id": cand["subject_id"],
        "relation": cand["relation"], "object_id": cand["object_id"],
        "event_id": ev_id, "weight": cand["score"]}])
    repo.set_candidate_status(user_id, cid, "confirmed")
    return {"id": cid, "status": "confirmed", "promoted": True}


def type_links(repo: Repo, user_id: str, llm, now: datetime,
               limit: int = 20) -> dict:
    """Classify the top `limit` links that have no candidate yet. Returns
    {"examined", "typed", "skipped", "errors"}."""
    notes = {n.id: n for n in repo.get_notes(user_id)}
    have = {c["id"] for c in repo.list_candidates(user_id)}
    stats = {"examined": 0, "typed": 0, "skipped": 0, "errors": 0}
    for link in repo.list_links(user_id, limit=limit):
        cid = f"cand:rel:{link.id}"
        if cid in have:
            continue
        a, b = notes.get(link.from_note_id), notes.get(link.to_note_id)
        if not a or not b:
            continue
        stats["examined"] += 1
        try:
            result = llm.complete_json(_SYSTEM, f"A: {a.text}\nB: {b.text}")
        except Exception as e:
            log.warning("relate: classification failed for %s (%s)", link.id, e)
            stats["errors"] += 1
            continue
        if not isinstance(result, dict):
            stats["errors"] += 1
            continue
        rel = str(result.get("relation") or "").strip().upper()
        if rel not in RELATIONS:
            stats["skipped"] += 1
            continue
        try:
            conf = max(0.0, min(1.0, float(result.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            conf = 0.0
        repo.insert_candidates(user_id, [{
            "id": cid, "relation": rel,
            "subject_id": a.id, "object_id": b.id, "score": conf,
            "uncertainty": None, "evidence": [_span(a), _span(b)],
            "status": "pending", "created_at": now.isoformat(),
            "policy_version": POLICY_VERSION,
            "why": (result.get("why") or "").strip() or None}])
        stats["typed"] += 1
    return stats
