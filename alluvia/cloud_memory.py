"""Memory follows you. After `alluvia cloud login`, the never-raw bundle
(session metadata, notes, suppressions, mutes — see memory_bundle) is pushed
after every refresh and capture and pulled before, so a second machine that
signs in receives everything on its first refresh. No command to remember.

Every function returns a result dict and never raises: a hook or a refresh
must not fail because the network did. Raw messages never leave the machine."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from alluvia import cloudclient
from alluvia.memory_bundle import export_bundle, import_bundle

PUSHED_AT = "cloud_memory:pushed_at"
PULLED_AT = "cloud_memory:pulled_at"
LAST_SYNC = "cloud_memory:last_sync"
MANAGED_DOWN = "cloud:managed_down"     # JSON {reason, at, until}; empty when healthy
NOT_SIGNED_IN = {"ok": False, "skipped": "not signed in"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _authed(session: dict, call):
    """Run `call(token)`; on a 401 with a refresh token, refresh once and retry."""
    try:
        return call(session["token"])
    except cloudclient.SyncError as e:
        if e.code != 401 or not session.get("refresh"):
            raise
        token, refresh = cloudclient.refresh_session(session["url"], session["refresh"])
        cloudclient.save_session(session["url"], token, refresh)
        session.update(token=token, refresh=refresh)
        return call(token)


def _backlog(repo, user_id: str) -> int:
    try:
        from alluvia.engine.engine import pending_distill
        return len(pending_distill(repo, user_id))
    except Exception:                                # noqa: BLE001 — a count, never a failure
        return 0


def push(repo, user_id: str, client=None, session=None, send_derived: bool = True) -> dict:
    """Two payloads: the memory bundle (source of truth for briefings, forget,
    and cross-machine memory) and the derived record (topics, related work,
    suggestions; never raw) so the app fills in by itself."""
    client = client or cloudclient
    session = session if session is not None else cloudclient.load_session()
    if not session or not session.get("token") or not session.get("url"):
        return dict(NOT_SIGNED_IN)
    records = list(export_bundle(repo, user_id, extra={"pending_sessions": _backlog(repo, user_id)}))
    try:
        result = _authed(session, lambda tok: client.post_memory(session["url"], tok, records))
    except cloudclient.SyncError as e:
        return {"ok": False, "error": str(e)}
    repo.set_meta(PUSHED_AT, _now())
    derived = {"ok": False, "skipped": "not requested"}
    if send_derived:
        try:
            from alluvia.cloudsync.bundle import build_bundle
            from alluvia.cloudsync.policy import load_policy
            bundle = build_bundle(repo, user_id, load_policy())
            _authed(session, lambda tok: client.push_bundle(session["url"], tok, bundle))
            derived = {"ok": True, "notes": len(bundle["notes"]), "themes": len(bundle["themes"])}
        except Exception as e:                       # noqa: BLE001 — never fail a push on the second payload
            derived = {"ok": False, "error": str(e)}
    notes = sum(1 for r in records if r.get("kind") == "note")
    return {"ok": True, "pushed": len(records), "notes": notes,
            "upserted": result.get("upserted") if isinstance(result, dict) else None,
            "derived": derived}


def pull(repo, user_id: str, client=None, session=None, embedder=None) -> dict:
    client = client or cloudclient
    session = session if session is not None else cloudclient.load_session()
    if not session or not session.get("token") or not session.get("url"):
        return dict(NOT_SIGNED_IN)
    since = repo.get_meta(PULLED_AT)
    try:
        body = _authed(session, lambda tok: client.get_memory(session["url"], tok, since))
    except cloudclient.SyncError as e:
        return {"ok": False, "error": str(e)}
    records = body.get("records") or [] if isinstance(body, dict) else []
    stats = import_bundle(repo, user_id, records, embedder=embedder)
    if isinstance(body, dict) and body.get("server_time"):
        repo.set_meta(PULLED_AT, str(body["server_time"]))
    return {"ok": True, "received": len(records), **stats}


def sync(repo, user_id: str, client=None, session=None, embedder=None) -> dict:
    """Pull, then push. Records what happened for `alluvia cloud status`."""
    session = session if session is not None else cloudclient.load_session()
    if not session or not session.get("token") or not session.get("url"):
        return dict(NOT_SIGNED_IN)
    pulled = pull(repo, user_id, client=client, session=session, embedder=embedder)
    pushed = push(repo, user_id, client=client, session=session)
    ok = bool(pulled.get("ok") and pushed.get("ok"))
    try:                                             # the plan shapes the LLM chain and the pause text
        b = _authed(session, lambda tok: (client or cloudclient).get_billing(session["url"], tok))
        cloudclient.update_session(plan=str(b.get("plan") or "free"))
    except Exception:                                # noqa: BLE001
        pass
    if ok:
        repo.set_meta(LAST_SYNC, json.dumps({
            "at": _now(), "notes_pushed": pushed.get("notes", 0),
            "notes_pulled": pulled.get("notes_added", 0)}))
    return {"ok": ok, "pull": pulled, "push": pushed}
