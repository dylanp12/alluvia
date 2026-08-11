import json

from alluvia.ingest.codex import CodexAdapter


def _rollout(root, name, records):
    d = root / "sessions" / "2025" / "08" / "09"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("\n".join(json.dumps(r) for r in records))


def test_reads_codex_rollout(tmp_path):
    _rollout(tmp_path, "rollout-2025-08-09T14-30-45-67e5uuid.jsonl", [
        {"timestamp": "2025-08-09T14:30:45.123Z", "type": "session_meta",
         "payload": {"id": "67e5uuid", "timestamp": "2025-08-09T14:30:45.120Z",
                     "cwd": "/p", "cli_version": "0.44.0", "source": "cli", "model_provider": "openai"}},
        # event_msg double-encodes the user's text -> must be skipped (else duplicated)
        {"timestamp": "t", "type": "event_msg",
         "payload": {"type": "user_message", "message": "Refactor auth to async.", "kind": "plain"}},
        {"timestamp": "t", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "Refactor auth to async."}]}},
        {"timestamp": "t", "type": "response_item",
         "payload": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "thinking"}]}},
        {"timestamp": "t", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "Reading the module."}]}},
        {"timestamp": "t", "type": "response_item",
         "payload": {"type": "function_call", "name": "shell", "arguments": "{}", "call_id": "c1"}},
    ])
    sessions = list(CodexAdapter(root=str(tmp_path)).read())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "codex" and s.native_id == "67e5uuid"
    assert [m.role for m in s.messages] == ["user", "assistant"]
    assert s.messages[0].text == "Refactor auth to async."          # once, not duplicated by event_msg
    assert "Reading the module" in s.messages[1].text               # reasoning/function_call skipped
    assert s.started_at.year == 2025                                # ISO timestamp parsed


def test_codex_old_wrapperless_format(tmp_path):
    _rollout(tmp_path, "rollout-2025-08-09T10-00-00-olduuid.jsonl", [
        {"id": "olduuid", "timestamp": "2025-08-09T10:00:00Z", "instructions": "..."},   # root meta
        {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello old"}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]},
    ])
    s = list(CodexAdapter(root=str(tmp_path)).read())[0]
    assert s.native_id == "olduuid" and [m.role for m in s.messages] == ["user", "assistant"]
    assert s.messages[0].text == "hello old"


def test_codex_skips_system_and_empty(tmp_path):
    # a system turn (dropped) + an empty-content turn (dropped) -> only the real user turn survives
    _rollout(tmp_path, "rollout-2025-08-09T09-00-00-s.jsonl", [
        {"type": "session_meta", "payload": {"id": "s", "timestamp": "2025-08-09T09:00:00Z"}},
        {"type": "response_item", "payload": {"type": "message", "role": "system",
                                              "content": [{"type": "input_text", "text": "You are Codex."}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": []}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
                                              "content": [{"type": "input_text", "text": "real question"}]}},
    ])
    s = list(CodexAdapter(root=str(tmp_path)).read())[0]
    assert [m.role for m in s.messages] == ["user"]
    assert s.messages[0].text == "real question"
