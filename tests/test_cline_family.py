import json

from alluvia.ingest.cline_family import ClineFamilyAdapter


def _task(root, ext, task_id, messages):
    d = root / "User" / "globalStorage" / ext / "tasks" / task_id
    d.mkdir(parents=True)
    (d / "api_conversation_history.json").write_text(json.dumps(messages))
    return d


def test_reads_anthropic_tasks(tmp_path):
    ext = "saoudrizwan.claude-dev"
    _task(tmp_path, ext, "1700000000000", [
        {"role": "user", "content": "why does refresh double-fire?"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "two tabs race the token"},
            {"type": "tool_use", "name": "bash", "input": {"cmd": "grep refresh"}},
            {"type": "tool_result", "content": "auth.ts:42 refresh()"},
        ]},
    ])
    sessions = list(ClineFamilyAdapter("cline", root=str(tmp_path)).read())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "cline" and s.native_id == "1700000000000"
    assert s.messages[0].role == "user"
    asst = s.messages[1].text
    assert "two tabs race" in asst and "auth.ts:42" in asst    # tool_result kept
    assert "bash" not in asst and "grep refresh" not in asst   # tool_use dropped
    assert s.started_at.year == 2023                            # epoch-ms task id parsed


def test_tool_result_capped(tmp_path):
    ext = "saoudrizwan.claude-dev"
    _task(tmp_path, ext, "t2", [{"role": "assistant",
          "content": [{"type": "tool_result", "content": "y" * 5000}]}])
    s = list(ClineFamilyAdapter("cline", root=str(tmp_path)).read())[0]
    assert len(s.messages[0].text) == 2000


def test_malformed_task_skipped(tmp_path):
    ext = "saoudrizwan.claude-dev"
    d = tmp_path / "User" / "globalStorage" / ext / "tasks" / "bad"
    d.mkdir(parents=True)
    (d / "api_conversation_history.json").write_text("{ not json")
    _task(tmp_path, ext, "good", [{"role": "user", "content": "hi"}])
    sessions = list(ClineFamilyAdapter("cline", root=str(tmp_path)).read())
    assert [s.native_id for s in sessions] == ["good"]         # bad skipped, good survives


def test_flavor_ext_mapping():
    assert ClineFamilyAdapter("kilo-code").ext == "kilocode.kilo-code"
    assert ClineFamilyAdapter("roo-code").ext == "rooveterinaryinc.roo-cline"
