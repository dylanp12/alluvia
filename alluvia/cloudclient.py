"""Cloud sync client (ships in the OSS package). Stores a session and pushes a
policy-filtered, scrubbed bundle to the hosted service. Stdlib HTTP only — the
local-first product stays dependency-light."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def session_path() -> str:
    return os.environ.get("ALLUVIA_CLOUD_SESSION",
                          os.path.expanduser("~/.alluvia/cloud-session.json"))


def save_session(url: str, token: str, refresh: str | None = None) -> None:
    p = session_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = {"url": url.rstrip("/"), "token": token}
    if refresh:
        data["refresh"] = refresh
    with open(p, "w") as f:
        json.dump(data, f)
    os.chmod(p, 0o600)


def load_session() -> dict | None:
    try:
        with open(session_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def clear_session() -> None:
    try:
        os.remove(session_path())
    except OSError:
        pass


def fetch_distill_key(url: str, token: str) -> dict | None:
    """GET the org's managed-distillation virtual key ({key, base_url, model}) from the
    cloud. None on any error, so the caller falls back to the local BYOK path."""
    req = urllib.request.Request(
        url.rstrip("/") + "/api/distill/key",
        headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except (OSError, ValueError):
        return None


class SyncError(Exception):
    pass


def push_bundle(url: str, token: str, bundle: dict) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + "/sync",
        data=json.dumps(bundle).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:200]
        raise SyncError(f"server returned {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise SyncError(f"cannot reach {url}: {e.reason}") from e


def loopback_login(server_url: str, open_browser: bool = True,
                   timeout: float = 300.0) -> tuple[str, str | None]:
    """Server-brokered OAuth via a localhost loopback. Opens the browser to the
    hosted login, which (after WorkOS) redirects the token back to a one-shot
    local server. Returns (access_token, refresh_token)."""
    import http.server
    import secrets
    import time
    import urllib.parse
    import webbrowser

    nonce = secrets.token_urlsafe(16)
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "token" in q:
                got.update(token=q.get("token", [None])[0],
                           refresh=q.get("refresh", [None])[0],
                           state=q.get("state", [None])[0])
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>alluvia: signed in.</h2>You can close this tab.")
        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    login_url = f"{server_url.rstrip('/')}/cli/login?port={port}&state={nonce}"
    if open_browser:
        webbrowser.open(login_url)
    else:
        print(f"open this URL to sign in:\n  {login_url}")
    srv.timeout = 1.0
    deadline = time.monotonic() + timeout
    while "token" not in got and time.monotonic() < deadline:
        srv.handle_request()             # one request (favicon, then callback)
    srv.server_close()
    if not got.get("token"):
        raise SyncError("login timed out or was cancelled")
    if got.get("state") != nonce:
        raise SyncError("login state mismatch — aborting")
    return got["token"], got.get("refresh")


def refresh_session(url: str, refresh_token: str) -> tuple[str, str | None]:
    """Exchange a refresh token for a fresh access token via the server broker."""
    req = urllib.request.Request(
        url.rstrip("/") + "/cli/refresh",
        data=json.dumps({"refresh_token": refresh_token}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
            return body["token"], body.get("refresh")
    except urllib.error.HTTPError as e:
        raise SyncError(f"refresh failed ({e.code}) — run `alluvia cloud login`")
