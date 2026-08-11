"""Proactive digest: ≤5 interrupt-worthy items, allowed silence, dismissal
learning, muted-theme exclusion. Pure selection over the map; the one LLM slot
(fresh proposal) degrades to skipped.

Every Nth digest trades one connection slot for an EXPLORE pick from beyond
the normal window — the label support a pure top-K policy can never collect.
Each digest also records its slate (what was shown, with explore flags)."""
from __future__ import annotations
import logging
import os
from datetime import datetime, timedelta

from alluvia.models import to_utc

log = logging.getLogger(__name__)

BUDGET_CONNECTIONS = 2
BUDGET_NUDGES = 2
NUDGE_COOLDOWN_DIGESTS = 2
DISMISSAL_MUTE_THRESHOLD = 2
EXPLORE_EVERY_DEFAULT = 4         # every Nth digest explores; 0 disables
EXPLORE_BEYOND = 100              # normal window ends here; explore picks past it
DIGEST_POLICY_VERSION = "digest-v1"


def _explore_every() -> int:
    raw = os.environ.get("ALLUVIA_DIGEST_EXPLORE_EVERY")
    try:
        return int(raw) if raw is not None else EXPLORE_EVERY_DEFAULT
    except ValueError:
        return EXPLORE_EVERY_DEFAULT


def due(repo, user_id: str, now: datetime, days: int) -> bool:
    last = repo.latest_digest(user_id)
    if last is None:
        return True
    last_at = to_utc(datetime.fromisoformat(last[1]))
    return to_utc(now) - last_at >= timedelta(days=days)


def generate(repo, deps, user_id: str, now: datetime) -> tuple[int, list[dict]]:
    """Build + persist a digest (possibly empty). Returns (digest_id, items)."""
    muted = repo.muted_labels(user_id)
    themes = [t for t in repo.list_themes(user_id)
              if t.label.lower() not in muted]
    noisy = {ref for ref, c in repo.dismissed_theme_counts(user_id).items()
             if c >= DISMISSAL_MUTE_THRESHOLD}
    themes = [t for t in themes if t.id not in noisy]
    theme_ids = {t.id for t in themes}
    notes = {n.id: n for n in repo.get_notes(user_id)}
    items: list[dict] = []

    # exploration cadence: this digest's ordinal decides whether one
    # connection slot is traded for a below-cutoff pick
    every = _explore_every()
    explore_due = bool(every) and (repo.digest_count(user_id) + 1) % every == 0
    explore_ref = None
    budget_a = BUDGET_CONNECTIONS - (1 if explore_due else 0)

    # A: never-shown connections, weight desc, at least one endpoint un-muted
    seen_links = repo.shown_refs(user_id, kinds=("connection",))
    for l in repo.list_links(user_id, limit=100):
        if len([i for i in items if i["kind"] == "connection"]) >= budget_a:
            break
        if l.id in seen_links:
            continue
        if l.from_theme_id not in theme_ids and l.to_theme_id not in theme_ids:
            continue
        a, b = notes.get(l.from_note_id), notes.get(l.to_note_id)
        if not a or not b:
            continue
        snap = (f"CONNECTION: \"{a.text[:120]}\" [{a.session_id.split(':', 1)[0]}] ↔ "
                f"\"{b.text[:120]}\" [{b.session_id.split(':', 1)[0]}]")
        items.append({"kind": "connection", "ref": l.id,
                      "theme_ref": l.from_theme_id, "snapshot": snap})

    # A': the explore pick — beyond the normal window, never shown
    if explore_due:
        shown = {i["ref"] for i in items}
        for l in repo.list_links(user_id, limit=200)[EXPLORE_BEYOND:]:
            if l.id in seen_links or l.id in shown:
                continue
            a, b = notes.get(l.from_note_id), notes.get(l.to_note_id)
            if not a or not b:
                continue
            snap = (f"EXPLORE: \"{a.text[:120]}\" "
                    f"[{a.session_id.split(':', 1)[0]}] ↔ \"{b.text[:120]}\" "
                    f"[{b.session_id.split(':', 1)[0]}]")
            items.append({"kind": "connection", "ref": l.id,
                          "theme_ref": l.from_theme_id, "snapshot": snap})
            explore_ref = l.id
            break

    # B: open themes, cooldown window, session×span desc
    recent_nudges = repo.shown_refs(user_id, kinds=("nudge",),
                                    last_n_digests=NUDGE_COOLDOWN_DIGESTS)

    def span_days(t):
        if t.first_seen and t.last_seen:
            return (to_utc(t.last_seen) - to_utc(t.first_seen)).days
        return 0

    open_themes = sorted((t for t in themes if t.status == "open"),
                         key=lambda t: t.session_count * (span_days(t) + 1),
                         reverse=True)
    for t in open_themes:
        if len([i for i in items if i["kind"] == "nudge"]) >= BUDGET_NUDGES:
            break
        if t.id in recent_nudges:
            continue
        snap = (f"UNFINISHED: {t.label} — {t.session_count} sessions over "
                f"{span_days(t)}d. {(t.summary or '')[:200]}")
        items.append({"kind": "nudge", "ref": t.id, "theme_ref": t.id,
                      "snapshot": snap})

    # C: one fresh proposal (bounded scheduled spend; degrade to skip).
    # Disable (env ALLUVIA_DIGEST_PROPOSALS=0 or [digest].proposals=false) for
    # pure-recall digests with zero scheduled LLM spend.
    from alluvia import config as _config
    if not _config.digest_proposals_enabled():
        return _finish(repo, user_id, now, items, explore_ref)
    try:
        from alluvia.engine.propose import candidates, generate_proposal
        cands = [c for c in candidates(repo, user_id, limit=5,
                                       surface="digest-propose")
                 if c.kind != "theme" or c.source_ref in theme_ids]
        for cand in cands:
            p = generate_proposal(repo, user_id, cand, deps.gen_llm,
                                  deps.critic_llm, deps.embedder,
                                  model_name=getattr(deps.gen_llm, "model", ""))
            if p:
                snap = (f"PROPOSAL [{p.id}] {p.title} (feasibility "
                        f"{p.feasibility or '?'}/5): {p.text[:200]} "
                        f"NEXT: {p.next_step[:120]}")
                items.append({"kind": "proposal", "ref": p.id,
                              "theme_ref": None, "snapshot": snap})
                break
    except Exception as e:
        log.warning("digest proposal slot skipped (%s)", e)

    return _finish(repo, user_id, now, items, explore_ref)


def _finish(repo, user_id: str, now: datetime, items: list[dict],
            explore_ref: str | None) -> tuple[int, list[dict]]:
    """Persist the digest AND its slate — the durable record of what was
    surfaced, at which rank, and which pick was exploration."""
    at = to_utc(now).isoformat()
    did = repo.insert_digest(user_id, at, items)
    repo.insert_slate(
        user_id, surface="digest", policy_version=DIGEST_POLICY_VERSION,
        created_at=at,
        items=[{"kind": it["kind"], "ref": it["ref"], "rank": n,
                "selected": True, "explore": it["ref"] == explore_ref}
               for n, it in enumerate(items, 1)])
    return did, items
