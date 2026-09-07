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


import json


def _rec(type_, content, **extra):
    d = {"type": type_, "message": {"role": type_, "content": content}}
    d.update(extra)
    return json.dumps(d)


def test_session_carries_project_and_branch(tmp_path):
    repo = tmp_path / "acme"; (repo / ".git").mkdir(parents=True)
    (tmp_path / "s.jsonl").write_text(
        _rec("user", "hello", cwd=str(repo / "src"), gitBranch="feat/x") + "\n"
        + _rec("assistant", [{"type": "text", "text": "hi"}], cwd=str(repo / "src")) + "\n")
    s = list(ClaudeCodeAdapter(str(tmp_path)).read())[0]
    assert s.project == str(repo)          # git root, not the deeper cwd
    assert s.branch == "feat/x"


def test_tool_actions_are_kept_as_action_lines(tmp_path):
    cwd = "/work/acme"
    (tmp_path / "s.jsonl").write_text(
        _rec("user", "fix the race", cwd=cwd) + "\n"
        + _rec("assistant", [
            {"type": "text", "text": "Pinning clock skew."},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/work/acme/auth/refresh.py", "old_string": "a", "new_string": "b"}},
            {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q tests/test_auth.py\n"}},
            {"type": "tool_use", "name": "Grep", "input": {"pattern": "clock_skew"}},
        ], cwd=cwd) + "\n"
        + _rec("user", [{"type": "tool_result", "tool_use_id": "x", "content": "3 passed"}], cwd=cwd) + "\n")
    s = list(ClaudeCodeAdapter(str(tmp_path)).read())[0]
    assert [m.role for m in s.messages] == ["user", "assistant"]   # tool_result-only turn dropped
    text = s.messages[1].text
    assert text.startswith("Pinning clock skew.")
    assert "[action] Edit auth/refresh.py" in text                  # relative to cwd
    assert "[action] Bash: pytest -q tests/test_auth.py" in text    # newline collapsed
    assert "[action] Grep clock_skew" in text
    assert "old_string" not in text                                  # arguments never dumped


def test_action_only_turn_is_kept_and_capped(tmp_path):
    blocks = [{"type": "tool_use", "name": "Read", "input": {"file_path": f"/w/f{i}.py"}} for i in range(30)]
    (tmp_path / "s.jsonl").write_text(
        _rec("user", "look around", cwd="/w") + "\n" + _rec("assistant", blocks, cwd="/w") + "\n")
    s = list(ClaudeCodeAdapter(str(tmp_path)).read())[0]
    lines = s.messages[1].text.splitlines()
    assert lines[0] == "[action] Read f0.py"
    assert len(lines) == 21 and lines[-1] == "[action] …10 more"


def test_read_file_returns_one_session(tmp_path):
    p = tmp_path / "one.jsonl"
    p.write_text(_rec("user", "hello") + "\n")
    s = ClaudeCodeAdapter(str(tmp_path)).read_file(str(p))
    assert s is not None and s.native_id == "one"


def test_harness_injected_user_slot_records_are_not_the_users_thread(tmp_path):
    """Claude Code marks injected user-slot content (skill bodies, command
    expansions) with isMeta. Measured 2026-09-05: a real session's handoff
    surfaced the TDD skill's rules as the user's 'decisions'. Not the user's
    thinking — never ingested."""
    (tmp_path / "s.jsonl").write_text(
        _rec("user", "make recall honest", cwd="/w") + "\n"
        + _rec("user", "Base directory for this skill: /plugins/tdd\n# TDD\nAlways write the test first.",
               cwd="/w", isMeta=True) + "\n"
        + _rec("assistant", [{"type": "text", "text": "On it."}], cwd="/w") + "\n")
    s = list(ClaudeCodeAdapter(str(tmp_path)).read())[0]
    assert [m.text for m in s.messages] == ["make recall honest", "On it."]
