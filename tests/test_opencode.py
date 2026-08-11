import json

from alluvia.ingest.opencode import OpenCodeAdapter


def _w(root, rel, obj):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj))


def test_reads_opencode_session(tmp_path):
    st = tmp_path  # the storage/ dir
    _w(st, "session/deadbeef/ses_1.json",
       {"id": "ses_1", "projectID": "deadbeef", "title": "Auth race",
        "version": "1.18.15", "time": {"created": 1754781000000, "updated": 1754781543210}})
    _w(st, "message/ses_1/msg_a.json",
       {"id": "msg_a", "sessionID": "ses_1", "role": "user", "time": {"created": 1754781000000}})
    _w(st, "part/msg_a/prt_1.json",
       {"id": "prt_1", "messageID": "msg_a", "type": "text", "text": "why does refresh double-fire?"})
    _w(st, "message/ses_1/msg_b.json",
       {"id": "msg_b", "sessionID": "ses_1", "role": "assistant", "time": {"created": 1754781010000}})
    _w(st, "part/msg_b/prt_1.json",
       {"id": "prt_1", "messageID": "msg_b", "type": "text", "text": "two tabs race the token"})
    _w(st, "part/msg_b/prt_2.json",
       {"id": "prt_2", "messageID": "msg_b", "type": "tool", "tool": "bash",
        "state": {"status": "completed", "input": {"cmd": "grep refresh"}, "output": "auth.ts:42"}})
    sessions = list(OpenCodeAdapter(root=str(st)).read())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "opencode" and s.native_id == "ses_1" and s.title == "Auth race"
    assert s.messages[0].role == "user" and "double-fire" in s.messages[0].text
    assert s.messages[1].role == "assistant" and "two tabs race" in s.messages[1].text
    assert "bash" not in s.messages[1].text and "grep refresh" not in s.messages[1].text  # tool part dropped
    assert s.started_at.year == 2025                                     # epoch-ms time.created parsed


def test_opencode_skips_sessions_with_no_text(tmp_path):
    st = tmp_path
    # ses_2: a message but no text parts -> no messages -> session skipped
    _w(st, "session/p/ses_2.json", {"id": "ses_2", "title": "empty", "time": {"created": 1754781000000}})
    _w(st, "message/ses_2/msg_x.json", {"id": "msg_x", "sessionID": "ses_2", "role": "user", "time": {}})
    # ses_3: has a text part -> survives
    _w(st, "session/p/ses_3.json", {"id": "ses_3", "title": "ok", "time": {"created": 1754781000000}})
    _w(st, "message/ses_3/msg_y.json", {"id": "msg_y", "sessionID": "ses_3", "role": "user", "time": {}})
    _w(st, "part/msg_y/prt_1.json", {"id": "prt_1", "messageID": "msg_y", "type": "text", "text": "hello"})
    ids = sorted(s.native_id for s in OpenCodeAdapter(root=str(st)).read())
    assert ids == ["ses_3"]


def test_opencode_malformed_session_skipped(tmp_path):
    st = tmp_path
    (st / "session" / "p").mkdir(parents=True)
    (st / "session" / "p" / "ses_bad.json").write_text("{ not json")
    _w(st, "session/p/ses_ok.json", {"id": "ses_ok", "title": "ok", "time": {"created": 1754781000000}})
    _w(st, "message/ses_ok/msg_z.json", {"id": "msg_z", "sessionID": "ses_ok", "role": "user", "time": {}})
    _w(st, "part/msg_z/prt_1.json", {"id": "prt_1", "messageID": "msg_z", "type": "text", "text": "hi"})
    ids = [s.native_id for s in OpenCodeAdapter(root=str(st)).read()]
    assert ids == ["ses_ok"]                                             # bad skipped, good survives
