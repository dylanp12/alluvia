"""Portable memory: what you have learned, never what you said.

A bundle is JSON Lines: header, sessions (metadata only), notes, suppressions,
mutes. No raw messages, no embeddings, no themes or links (rebuilt locally).
Import is an idempotent merge: content-addressed note ids, sessions marked
distilled on arrival so they never reach the LLM, this machine's raw always
preferred over an import."""
from __future__ import annotations

import socket
from datetime import datetime, timezone

from alluvia.config import PIPELINE_VERSION
from alluvia.distill.scrub import redact
from alluvia.models import Note, RawSession, to_utc

FORMAT = "alluvia-memory"
VERSION = 1


def _iso(dt):
    return to_utc(dt).isoformat() if dt else None


def _dt(s):
    return datetime.fromisoformat(s) if s else None


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("alluvia")
    except PackageNotFoundError:
        return "dev"


def export_bundle(repo, user_id: str, project: str | None = None,
                  project_relative: bool = False, extra: dict | None = None):
    """Yield bundle records. `project` limits to one repository's sessions;
    `project_relative` writes them as belonging to "this checkout" so the
    importer binds them to its own root; `extra` adds header fields (the cloud
    reads the backlog from them)."""
    yield {"kind": "header", "format": FORMAT, "version": VERSION,
           "exported_at": datetime.now(timezone.utc).isoformat(),
           "origin": socket.gethostname(), "pipeline_version": PIPELINE_VERSION,
           "cli_version": _version(), **(extra or {})}
    sessions = repo.list_session_meta(user_id, project=project)
    sids = {s["id"] for s in sessions}
    for s in sessions:
        rec = {"kind": "session", "id": s["id"], "source": s["source"], "native_id": s["native_id"],
               "started_at": _iso(s["started_at"]), "ended_at": _iso(s["ended_at"]),
               "project": s["project"], "branch": s["branch"],
               "content_hash": repo.session_content_hash(user_id, s["id"])}
        if project_relative:
            rec["project"], rec["project_rel"] = None, "."
        yield rec
    hidden = repo.suppressed_note_ids(user_id)
    for n in repo.get_notes(user_id):
        if n.session_id in sids and n.id not in hidden:
            yield {"kind": "note", "id": n.id, "session_id": n.session_id, "span_ref": n.span_ref,
                   "note_kind": n.kind, "text": redact(n.text), "created_at": _iso(n.created_at)}
    for row in repo.list_suppressed(user_id):
        yield {"kind": "suppressed", **row}
    for label in sorted(repo.muted_labels(user_id)):
        yield {"kind": "muted", "label": label}


class _NoLLM:
    def complete_json(self, *a, **k):
        raise RuntimeError("import never calls a model")


def import_bundle(repo, user_id: str, records, embedder=None,
                  bind_project: str | None = None) -> dict:
    """Merge bundle records into the store. `embedder=None` keeps the import
    SQLite-only (hooks); otherwise new notes are embedded at the end."""
    out = {"sessions_added": 0, "notes_added": 0, "notes_present": 0,
           "judgments_added": 0, "skipped": 0}
    origin = "import"
    known_sessions = repo.session_projects(user_id)
    known_notes = {n.id for n in repo.get_notes(user_id)}
    suppressed = repo.suppressed_note_ids(user_id)
    muted = repo.muted_labels(user_id)
    for r in records:
        kind = r.get("kind") if isinstance(r, dict) else None
        try:
            if kind == "header":
                origin = str(r.get("origin") or origin)
            elif kind == "session":
                sid = r["id"]
                if sid in known_sessions:
                    continue                                    # this machine's raw wins
                project = bind_project if r.get("project_rel") == "." else r.get("project")
                repo.upsert_session(RawSession(
                    id=sid, user_id=user_id, source=r["source"], native_id=r["native_id"],
                    title="", started_at=_dt(r.get("started_at")), ended_at=_dt(r.get("ended_at")),
                    messages=[], content_hash=r.get("content_hash") or "", project=project,
                    branch=r.get("branch")), imported_from=origin)
                repo.mark_distilled(user_id, sid)               # nothing to distill here
                known_sessions[sid] = project
                out["sessions_added"] += 1
            elif kind == "note":
                nid = r["id"]
                if nid in known_notes:
                    out["notes_present"] += 1
                    continue
                repo.upsert_notes([Note(id=nid, user_id=user_id, session_id=r["session_id"],
                                        span_ref=r.get("span_ref", ""),
                                        kind=r.get("note_kind", "insight"), text=r["text"],
                                        created_at=_dt(r.get("created_at")))])
                known_notes.add(nid)
                out["notes_added"] += 1
            elif kind == "suppressed":
                if r.get("retracted"):
                    # a forget undone elsewhere (the app, another machine)
                    if r["note_id"] in suppressed:
                        repo.unsuppress_note(user_id, r["note_id"])
                        suppressed.discard(r["note_id"])
                        out["judgments_added"] += 1
                elif r["note_id"] not in suppressed:
                    repo.suppress_note(user_id, r["note_id"], reason=r.get("reason"))
                    suppressed.add(r["note_id"])
                    out["judgments_added"] += 1
            elif kind == "muted":
                if r["label"].lower() not in muted:
                    repo.mute_label(user_id, r["label"])
                    muted.add(r["label"].lower())
                    out["judgments_added"] += 1
            else:
                out["skipped"] += 1
        except (KeyError, TypeError, ValueError):
            out["skipped"] += 1
    if embedder is not None and out["notes_added"]:
        from alluvia.engine.engine import Engine
        Engine(repo, embedder, _NoLLM(), min_cluster_size=2).embed_new(user_id)
    return out
