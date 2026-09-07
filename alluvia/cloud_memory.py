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


def push(repo, user_id: str, client=None, session=None) -> dict:
    client = client or cloudclient
    session = session if session is not None else cloudclient.load_session()
    if not session or not session.get("token") or not session.get("url"):
        return dict(NOT_SIGNED_IN)
    records = list(export_bundle(repo, user_id))
    try:
        result = _authed(session, lambda tok: client.post_memory(session["url"], tok, records))
    except cloudclient.SyncError as e:
        return {"ok": False, "error": str(e)}
    repo.set_meta(PUSHED_AT, _now())
    notes = sum(1 for r in records if r.get("kind") == "note")
    return {"ok": True, "pushed": len(records), "notes": notes,
            "upserted": result.get("upserted") if isinstance(result, dict) else None}


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
    if ok:
        repo.set_meta(LAST_SYNC, json.dumps({
            "at": _now(), "notes_pushed": pushed.get("notes", 0),
            "notes_pulled": pulled.get("notes_added", 0)}))
    return {"ok": ok, "pull": pulled, "push": pushed}
