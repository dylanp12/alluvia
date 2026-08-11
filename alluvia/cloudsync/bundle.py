"""Bundle builder: turn the local derived memory into an upload payload,
filtered by policy and secret-scrubbed. Pure over a Repo — the CLI shows the
preview before anything leaves the machine.

Data classes honored: derived_only ships notes/themes/links/judgments +
session METADATA (never raw messages). excerpt adds a scrubbed excerpt per
note. raw (transcript storage) is the next slice."""
from __future__ import annotations

from alluvia.distill.scrub import redact
from alluvia.models import to_utc

BUNDLE_SCHEMA = 1


def _iso(dt):
    return to_utc(dt).isoformat() if dt else None


def build_bundle(repo, user_id: str, policy) -> dict:
    sessions = repo.list_sessions(user_id)
    mode = {s.id: policy.mode_for(s.source) for s in sessions}
    keep_session = {sid for sid, m in mode.items() if m != "none"}

    notes = [n for n in repo.get_notes(user_id) if n.session_id in keep_session]
    ids, mat = repo.all_embeddings(user_id)
    emb = {nid: [round(float(x), 6) for x in mat[i]]
           for i, nid in enumerate(ids) if nid in {n.id for n in notes}}

    excerpts = {}
    want_excerpt = {n.id for n in notes
                    if mode.get(n.session_id) in ("excerpt", "raw")}
    if want_excerpt:
        by_session = {s.id: s for s in sessions}
        for n in notes:
            if n.id in want_excerpt:
                s = by_session.get(n.session_id)
                raw = " ".join(m.text for m in s.messages) if s else n.text
                excerpts[n.id] = redact(raw[:500])

    kept_note_ids = {n.id for n in notes}
    themes = [t for t in repo.list_themes(user_id)
              if any(nid in kept_note_ids for nid in t.note_ids)]
    links = [l for l in repo.list_links(user_id)
             if l.from_note_id in kept_note_ids and l.to_note_id in kept_note_ids]
    judgments = repo.list_proposals(user_id,
                                    outcomes=("pending", "kept", "dismissed"))

    return {
        "schema": BUNDLE_SCHEMA,
        "modes": {s.source: policy.mode_for(s.source) for s in sessions},
        "sessions": [{"id": s.id, "source": s.source, "native_id": s.native_id,
                      "title": s.title, "started_at": _iso(s.started_at),
                      "ended_at": _iso(s.ended_at),
                      "content_hash": s.content_hash,
                      "sync_mode": mode[s.id]}
                     for s in sessions if s.id in keep_session],
        "notes": [{"id": n.id, "session_id": n.session_id, "span_ref": n.span_ref,
                   "kind": n.kind, "text": redact(n.text),
                   "created_at": _iso(n.created_at)} for n in notes],
        "embeddings": emb,
        "themes": [{"id": t.id, "label": t.label, "summary": t.summary,
                    "note_ids": t.note_ids, "first_seen": _iso(t.first_seen),
                    "last_seen": _iso(t.last_seen), "session_count": t.session_count,
                    "source_count": t.source_count, "status": t.status}
                   for t in themes],
        "links": [{"id": l.id, "from_note_id": l.from_note_id,
                   "to_note_id": l.to_note_id, "from_theme_id": l.from_theme_id,
                   "to_theme_id": l.to_theme_id, "kind": l.kind,
                   "weight": l.weight, "why": l.why} for l in links],
        "judgments": [{"id": p.id, "kind": p.kind, "ref": p.source_ref,
                       "verdict": p.outcome, "title": p.title, "text": p.text,
                       "next_step": p.next_step, "cites": p.cites,
                       "created_at": p.created_at} for p in judgments],
        "excerpts": excerpts,
    }


def preview(bundle: dict) -> str:
    raw_count = sum(1 for s in bundle["sessions"] if s["sync_mode"] == "raw")
    return (
        f"will upload:\n"
        f"  notes:      {len(bundle['notes'])}\n"
        f"  themes:     {len(bundle['themes'])}\n"
        f"  links:      {len(bundle['links'])}\n"
        f"  judgments:  {len(bundle['judgments'])}\n"
        f"  excerpts:   {len(bundle['excerpts'])}\n"
        f"  sessions:   {len(bundle['sessions'])} (metadata)\n"
        f"  raw sessions: {raw_count}\n"
        f"note texts are secret-scrubbed before upload; raw transcripts stay "
        f"local unless a source is set to 'raw'.")
