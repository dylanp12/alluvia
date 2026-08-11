from datetime import datetime, timezone

from alluvia.ingest.common import anthropic_text, build_session, normalize_role, parse_ts
from alluvia.models import Message


def test_parse_ts_variants():
    assert parse_ts(1_700_000_000_000).year == 2023          # epoch ms
    assert parse_ts(1_700_000_000).year == 2023              # epoch s
    assert parse_ts("2026-06-01T10:00:00+00:00").year == 2026
    assert parse_ts("2026-06-01T10:00:00Z").year == 2026
    assert parse_ts("nonsense") is None and parse_ts(None) is None


def test_normalize_role():
    assert normalize_role("user") == "user" and normalize_role("human") == "user"
    assert normalize_role("assistant") == "assistant" and normalize_role(2) == "assistant"
    assert normalize_role("system") is None


def test_anthropic_text_shapes():
    assert anthropic_text("hello") == "hello"
    blocks = [{"type": "text", "text": "hi"},
              {"type": "tool_use", "name": "bash", "input": {"cmd": "ls"}},
              {"type": "tool_result", "content": "file1\nfile2"}]
    out = anthropic_text(blocks)
    assert "hi" in out and "file1" in out and "bash" not in out and "ls" not in out  # tool_use dropped


def test_anthropic_text_tool_result_capped_and_nested():
    big = "x" * 5000
    nested = [{"type": "tool_result", "content": [{"type": "text", "text": big}]}]
    assert len(anthropic_text(nested)) == 2000                # cap applied to nested content


def test_build_session():
    msgs = [Message(role="user", text="why refresh double-fires"),
            Message(role="assistant", text="two tabs race", ts=datetime(2026, 6, 1, tzinfo=timezone.utc))]
    s = build_session("cline", "task42", None, msgs, "local")
    assert s.id == "cline:task42" and s.source == "cline" and s.native_id == "task42"
    assert s.title == "why refresh double-fires" and s.user_id == "local"
    assert s.ended_at.year == 2026 and s.content_hash
