from pathlib import Path
from alluvia.ingest.claude_code import ClaudeCodeAdapter


def test_reads_one_session_per_file():
    fixtures = Path(__file__).parent / "fixtures"
    sessions = list(ClaudeCodeAdapter(str(fixtures), user_id="local").read())
    assert len(sessions) == 1
    s = sessions[0]
    assert s.source == "claude-code"
    assert s.native_id == "sess-1"          # identity = filename stem
    assert s.id == "claude-code:sess-1"
    assert [m.role for m in s.messages] == ["user", "assistant"]
    assert "token service" in s.messages[1].text
    assert s.content_hash


def test_identity_is_the_file_not_internal_sessionid(tmp_path):
    # internal sessionId differs from filename -> identity must follow the FILE
    (tmp_path / "file-uuid.jsonl").write_text(
        '{"type":"user","sessionId":"OTHER","isSidechain":false,'
        '"message":{"role":"user","content":"hello"}}\n'
    )
    s = list(ClaudeCodeAdapter(str(tmp_path)).read())[0]
    assert s.native_id == "file-uuid"
    assert s.id == "claude-code:file-uuid"


def test_excludes_sidechain_files(tmp_path):
    (tmp_path / "main.jsonl").write_text(
        '{"type":"user","isSidechain":false,"message":{"role":"user","content":"real thought"}}\n'
    )
    (tmp_path / "subagent.jsonl").write_text(
        '{"type":"user","isSidechain":true,"message":{"role":"user","content":"agent scratch"}}\n'
        '{"type":"assistant","isSidechain":true,"message":{"role":"assistant","content":"agent reply"}}\n'
    )
    sessions = list(ClaudeCodeAdapter(str(tmp_path)).read())
    assert [s.native_id for s in sessions] == ["main"]
    assert "real thought" in sessions[0].messages[0].text


def test_excludes_harness_judge_meta_sessions(tmp_path):
    (tmp_path / "judge.jsonl").write_text(
        '{"type":"user","message":{"role":"user","content":'
        '"Analyze this conversation and determine: Does the assistant have more '
        'autonomous work to do RIGHT NOW?"}}\n'
        '{"type":"assistant","message":{"role":"assistant","content":"No."}}\n')
    (tmp_path / "critic.jsonl").write_text(
        '{"type":"user","message":{"role":"user","content":'
        '"You are a completeness critic for a viability study."}}\n')
    (tmp_path / "real.jsonl").write_text(
        '{"type":"user","message":{"role":"user","content":"design the cache layer"}}\n')
    sessions = list(ClaudeCodeAdapter(str(tmp_path)).read())
    assert [s.native_id for s in sessions] == ["real"]


def test_skips_non_message_events_and_malformed(tmp_path):
    (tmp_path / "z.jsonl").write_text(
        "not json\n"
        '{"type":"file-history-snapshot","messageId":"x"}\n'
        '{"type":"user","message":{"role":"user","content":"hello world"}}\n'
        "{bad\n"
    )
    sessions = list(ClaudeCodeAdapter(str(tmp_path)).read())
    assert len(sessions) == 1
    assert sessions[0].native_id == "z"
    assert [m.text for m in sessions[0].messages] == ["hello world"]
