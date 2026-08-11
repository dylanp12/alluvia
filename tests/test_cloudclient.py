"""Client: session storage + request shape (HTTP mocked)."""
import json
import os


def test_session_roundtrip_is_0600(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_CLOUD_SESSION", str(tmp_path / "s.json"))
    from alluvia.cloudclient import save_session, load_session, clear_session
    save_session("https://api.example.com/", "tok123")
    s = load_session()
    assert s == {"url": "https://api.example.com", "token": "tok123"}
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
