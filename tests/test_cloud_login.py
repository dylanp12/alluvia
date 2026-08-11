"""Client loopback login + refresh-on-401 (a fake broker stands in for the
server; no WorkOS, no browser)."""
import http.server
import json
import socketserver
import threading
import urllib.parse
import urllib.request

import pytest

from alluvia.cloudclient import loopback_login, refresh_session, SyncError


class _Broker(http.server.BaseHTTPRequestHandler):
    """Mimics the server: /cli/login immediately loops a token back to the
    CLI's localhost port (skipping the real WorkOS round-trip)."""
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/cli/login":
            port, state = q["port"][0], q["state"][0]
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/callback?token=ACCESS&refresh=REFRESH&state={state}",
                timeout=5).read()
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        else:
            self.send_response(404); self.end_headers()
    def do_POST(self):
        if self.path == "/cli/refresh":
            self.send_response(201)
            self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"token": "NEWACCESS",
                                         "refresh": "NEWREFRESH"}).encode())
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, *a): pass


class _TServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


@pytest.fixture
def broker():
    srv = _TServer(("127.0.0.1", 0), _Broker)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_loopback_login_returns_tokens(broker, monkeypatch):
    # simulate the browser: hitting the printed login URL in a background thread
    def fake_open(u):
        threading.Thread(target=lambda: urllib.request.urlopen(u, timeout=5).read(),
                         daemon=True).start()
    monkeypatch.setattr("webbrowser.open", fake_open)
    access, refresh = loopback_login(broker, open_browser=True, timeout=10)
    assert access == "ACCESS" and refresh == "REFRESH"


def test_refresh_session_exchanges(broker):
    tok, ref = refresh_session(broker, "old-refresh")
    assert tok == "NEWACCESS" and ref == "NEWREFRESH"
