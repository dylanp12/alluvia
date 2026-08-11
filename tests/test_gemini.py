import json

from alluvia.ingest.gemini import GeminiAdapter


def _chats(tmp_path, projhash="ph"):
    d = tmp_path / "tmp" / projhash / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_reads_gemini_jsonl(tmp_path):
    d = _chats(tmp_path)
    lines = [
        {"sessionId": "7f3c", "projectHash": "ph", "startTime": "2026-08-09T15:04:00.000Z",
         "lastUpdated": "2026-08-09T15:04:07.500Z", "kind": "main"},
        {"id": "a1", "timestamp": "2026-08-09T15:04:05.000Z", "type": "user",
         "content": [{"text": "Write a haiku about rivers."}]},
        {"$set": {"lastUpdated": "2026-08-09T15:04:07.500Z"}},                       # control -> skip
        {"id": "b2", "timestamp": "2026-08-09T15:04:07.000Z", "type": "gemini",
         "content": [{"text": "Silver threads descend"}], "model": "gemini-2.5-pro"},
        {"id": "c3", "timestamp": "t", "type": "gemini",                              # tool call -> no text
         "content": [{"functionCall": {"id": "call-1", "name": "read_file", "args": {}}}]},
        {"id": "d4", "timestamp": "t", "type": "user",                               # tool result -> no text
         "content": [{"functionResponse": {"id": "call-1", "name": "read_file", "response": {}}}]},
        {"$rewindTo": "z9"},                                                          # control -> skip
    ]
    (d / "session-2026-08-09T15-04-7f3c.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    sessions = list(GeminiAdapter(root=str(tmp_path)).read())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "gemini" and s.native_id == "7f3c"
    assert [m.role for m in s.messages] == ["user", "assistant"]      # gemini->assistant; tool-only dropped
    assert "haiku about rivers" in s.messages[0].text
    assert "Silver threads" in s.messages[1].text
    assert s.started_at.year == 2026                                  # ISO startTime parsed


def test_reads_gemini_json_and_string_content(tmp_path):
    d = _chats(tmp_path, "ph2")
    obj = {"sessionId": "jj", "startTime": "2026-08-09T15:04:00.000Z", "messages": [
        {"id": "a", "timestamp": "t", "type": "user", "content": [{"text": "hi"}]},
        {"id": "b", "timestamp": "t", "type": "gemini", "content": "plain string reply"},
        {"id": "c", "timestamp": "t", "type": "info", "content": [{"text": "ui noise"}]},   # dropped
    ]}
    (d / "session-x.json").write_text(json.dumps(obj))
    s = list(GeminiAdapter(root=str(tmp_path)).read())[0]
    assert s.native_id == "jj" and [m.role for m in s.messages] == ["user", "assistant"]
    assert s.messages[1].text == "plain string reply"                # bare-string content handled


def test_gemini_malformed_line_skipped(tmp_path):
    d = _chats(tmp_path, "ph3")
    (d / "session-bad.jsonl").write_text(
        '{"sessionId":"ok","startTime":"2026-08-09T15:04:00.000Z"}\n'
        "{ not json\n"
        '{"id":"a","type":"user","content":[{"text":"survived"}]}\n')
    s = list(GeminiAdapter(root=str(tmp_path)).read())[0]
    assert s.native_id == "ok" and s.messages[0].text == "survived"  # bad line skipped, rest intact
