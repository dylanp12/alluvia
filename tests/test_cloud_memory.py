"""Memory follows you: after sign-in the never-raw bundle syncs up and down
with no command to remember. Nothing here raises; a hook or a refresh must
never fail because the network did."""
from datetime import datetime, timezone

from alluvia.cloud_memory import PULLED_AT, PUSHED_AT, pull, push, sync
from alluvia.cloudclient import SyncError
from alluvia.models import Note, RawSession

USER = "local"
NOW = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)
SESSION = {"url": "https://api.example.com", "token": "tok"}


class FakeCloud:
    def __init__(self, records=None, fail=None):
        self.calls, self.records, self.fail = [], records or [], fail
        self.server_time = "2026-09-07T09:05:00+00:00"

    def post_memory(self, url, token, records):
        self.calls.append(("post", url, token, list(records)))
        if self.fail:
            raise self.fail
        return {"upserted": len(records), "skipped": 0}

    def get_memory(self, url, token, since=None):
        self.calls.append(("get", url, token, since))
        if self.fail:
            raise self.fail
        return {"records": self.records, "server_time": self.server_time}


def _seed(repo, sid="s1", nid="n1", project="/w/acme"):
    repo.upsert_session(RawSession(
        id=sid, user_id=USER, source="claude-code", native_id=sid * 4, title="",
        started_at=NOW, ended_at=NOW, messages=[], content_hash="h", project=project,
        branch="main"))
    repo.mark_distilled(USER, sid)
    repo.upsert_notes([Note(id=nid, user_id=USER, session_id=sid, span_ref="msg:1",
                            kind="decision", text="pin clock skew in auth/refresh.py",
                            created_at=NOW)])


def test_push_sends_the_full_bundle_and_stamps(repo):
    _seed(repo)
    cloud = FakeCloud()
    out = push(repo, USER, client=cloud, session=SESSION)
    assert out["ok"] and out["notes"] == 1
    kinds = [r["kind"] for r in cloud.calls[0][3]]
    assert "session" in kinds and "note" in kinds
    assert repo.get_meta(PUSHED_AT)


def test_pull_imports_and_advances_the_watermark(repo):
    remote = [{"kind": "session", "id": "s9", "source": "claude-code", "native_id": "s9s9s9s9",
               "started_at": NOW.isoformat(), "ended_at": NOW.isoformat(),
               "project": "/w/acme", "branch": "main", "content_hash": "h9"},
              {"kind": "note", "id": "n9", "session_id": "s9", "span_ref": "msg:1",
               "note_kind": "decision", "text": "retry uploads with jitter",
               "created_at": NOW.isoformat()}]
    cloud = FakeCloud(records=remote)
    out = pull(repo, USER, client=cloud, session=SESSION)
    assert out["ok"] and out["notes_added"] == 1 and out["sessions_added"] == 1
    assert cloud.calls[0][3] is None                         # first pull: everything
    assert repo.get_meta(PULLED_AT) == cloud.server_time
    assert "s9" in repo.done_session_ids(USER)               # never re-distilled here
    pull(repo, USER, client=cloud, session=SESSION)
    assert cloud.calls[1][3] == cloud.server_time            # then only what is newer


def test_network_failure_is_a_result_not_an_exception(repo):
    _seed(repo)
    cloud = FakeCloud(fail=SyncError("cannot reach https://api.example.com: timed out"))
    out = push(repo, USER, client=cloud, session=SESSION)
    assert out["ok"] is False and "timed out" in out["error"]
    assert repo.get_meta(PUSHED_AT) is None
    out = pull(repo, USER, client=cloud, session=SESSION)
    assert out["ok"] is False and repo.get_meta(PULLED_AT) is None


def test_not_signed_in_is_skipped_without_a_call(repo):
    cloud = FakeCloud()
    assert push(repo, USER, client=cloud, session=None) == {"ok": False, "skipped": "not signed in"}
    assert pull(repo, USER, client=cloud, session=None) == {"ok": False, "skipped": "not signed in"}
    assert cloud.calls == []


def test_sync_pulls_then_pushes(repo):
    _seed(repo)
    cloud = FakeCloud()
    out = sync(repo, USER, client=cloud, session=SESSION)
    assert out["ok"] and [c[0] for c in cloud.calls] == ["get", "post"]


def test_expired_token_is_refreshed_once(repo, monkeypatch, tmp_path):
    monkeypatch.setenv("ALLUVIA_CLOUD_SESSION", str(tmp_path / "sess.json"))
    from alluvia import cloudclient
    cloudclient.save_session("https://api.example.com", "old", "refresh-1")
    monkeypatch.setattr(cloudclient, "refresh_session", lambda url, ref: ("new", "refresh-2"))
    _seed(repo)

    class Expiring(FakeCloud):
        def post_memory(self, url, token, records):
            self.calls.append(("post", url, token, list(records)))
            if token == "old":
                raise SyncError("server returned 401: expired", code=401)
            return {"upserted": len(records), "skipped": 0}

    cloud = Expiring()
    out = push(repo, USER, client=cloud)                     # session read from disk
    assert out["ok"] and [c[2] for c in cloud.calls] == ["old", "new"]
    assert cloudclient.load_session()["token"] == "new"
