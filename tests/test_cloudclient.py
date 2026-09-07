"""Client: session storage + request shape (HTTP mocked)."""
import json
import os
import sys


def test_session_roundtrip_is_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_CLOUD_SESSION", str(tmp_path / "s.json"))
    from alluvia.cloudclient import save_session, load_session, clear_session
    save_session("https://api.example.com/", "tok123")
    s = load_session()
    assert s == {"url": "https://api.example.com", "token": "tok123"}
    if sys.platform != "win32":       # POSIX mode; Windows uses ACLs, chmod is a no-op
        assert oct(os.stat(tmp_path / "s.json").st_mode & 0o777) == "0o600"
    clear_session()
    assert load_session() is None


def test_push_bundle_sends_bearer_and_json(monkeypatch):
    from alluvia import cloudclient
    captured = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"notes": 3}).encode()

    def fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = json.loads(req.data.decode())
        return FakeResp()

    monkeypatch.setattr(cloudclient.urllib.request, "urlopen", fake_urlopen)
    out = cloudclient.push_bundle("https://api.example.com", "tok",
                                  {"notes": [{"id": "n1"}]})
    assert out == {"notes": 3}
    assert captured["url"] == "https://api.example.com/sync"
    assert captured["auth"] == "Bearer tok"
    assert captured["body"]["notes"] == [{"id": "n1"}]


def test_memory_helpers_use_api_memory_with_a_short_timeout(monkeypatch):
    from alluvia import cloudclient
    seen = []

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps({"records": [], "server_time": "t"}).encode()

    def fake_urlopen(req, timeout=0):
        seen.append((req.get_method(), req.full_url, timeout, req.data))
        return FakeResp()

    monkeypatch.setattr(cloudclient.urllib.request, "urlopen", fake_urlopen)
    cloudclient.post_memory("https://api.example.com/", "tok", [{"kind": "muted", "label": "x"}])
    cloudclient.get_memory("https://api.example.com", "tok", since="2026-09-07T09:05:00+00:00")
    assert seen[0][:3] == ("POST", "https://api.example.com/api/memory", 15)
    assert json.loads(seen[0][3]) == {"records": [{"kind": "muted", "label": "x"}]}
    assert seen[1][:3] == ("GET", "https://api.example.com/api/memory"
                           "?since=2026-09-07T09%3A05%3A00%2B00%3A00", 15)


def test_http_error_carries_its_status(monkeypatch):
    import io
    import urllib.error
    from alluvia import cloudclient

    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "expired", {}, io.BytesIO(b"expired"))

    monkeypatch.setattr(cloudclient.urllib.request, "urlopen", fake_urlopen)
    try:
        cloudclient.get_memory("https://api.example.com", "tok")
    except cloudclient.SyncError as e:
        assert e.code == 401
    else:
        raise AssertionError("expected SyncError")


def test_login_always_prints_a_link_to_paste(monkeypatch, capsys):
    """The browser may not open (SSH, a locked-down desktop); the link is
    always printed so the user can paste it."""
    from alluvia import cloudclient
    monkeypatch.setattr(cloudclient, "webbrowser", type("W", (), {"open": staticmethod(lambda u: True)})(),
                        raising=False)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda u: True)
    try:
        cloudclient.loopback_login("https://app.example.com", open_browser=True, timeout=0.05)
    except cloudclient.SyncError:
        pass
    out = capsys.readouterr().out
    assert "https://app.example.com/cli/login?port=" in out
    assert "paste" in out.lower()
