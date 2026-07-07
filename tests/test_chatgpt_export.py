import json
import zipfile
from alluvia.ingest.chatgpt_export import ChatGPTExportAdapter


def _conversations():
    # root -> u1 -> a1 -> u2b (canonical), with an abandoned branch u2a off a1
    return [{
        "id": "conv-1",
        "title": "rate limiting ideas",
        "create_time": 1767225600.0,
        "current_node": "u2b",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["u1"]},
            "u1": {"id": "u1", "parent": "root", "children": ["a1"], "message": {
                "author": {"role": "user"}, "create_time": 1767225600.0,
                "content": {"content_type": "text", "parts": ["how should I rate limit"]}}},
            "a1": {"id": "a1", "parent": "u1", "children": ["u2a", "u2b"], "message": {
                "author": {"role": "assistant"}, "create_time": 1767225660.0,
                "content": {"content_type": "text", "parts": ["token bucket per key"]}}},
            "u2a": {"id": "u2a", "parent": "a1", "children": [], "message": {
                "author": {"role": "user"}, "create_time": 1767225700.0,
                "content": {"content_type": "text", "parts": ["ABANDONED BRANCH"]}}},
            "u2b": {"id": "u2b", "parent": "a1", "children": [], "message": {
                "author": {"role": "user"}, "create_time": 1767225720.0,
                "content": {"content_type": "text", "parts": ["what about bursts"]}}},
        },
    }]


def test_zip_parses_canonical_path_only(tmp_path):
    zpath = tmp_path / "export.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("conversations.json", json.dumps(_conversations()))
    sessions = list(ChatGPTExportAdapter(str(zpath)).read())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "chatgpt" and s.native_id == "conv-1"
    texts = [m.text for m in s.messages]
    assert texts == ["how should I rate limit", "token bucket per key", "what about bursts"]
    assert "ABANDONED BRANCH" not in " ".join(texts)      # branch not taken
    assert s.started_at is not None and s.title == "rate limiting ideas"


def test_plain_json_file_and_idempotent_hash(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(_conversations()))
    a = list(ChatGPTExportAdapter(str(p)).read())[0]
    b = list(ChatGPTExportAdapter(str(p)).read())[0]
    assert a.content_hash == b.content_hash               # re-import idempotency basis


def test_non_text_and_system_parts_skipped(tmp_path):
    convs = _conversations()
    convs[0]["mapping"]["u1"]["message"]["content"] = {
        "content_type": "multimodal_text", "parts": [{"image": "..."}]}
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(convs))
    s = list(ChatGPTExportAdapter(str(p)).read())[0]
    assert all(isinstance(m.text, str) and m.text for m in s.messages)
    assert "how should I rate limit" not in [m.text for m in s.messages]
