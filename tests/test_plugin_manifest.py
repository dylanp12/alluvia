"""The Claude Code plugin is manifests only: hooks call the installed CLI,
MCP runs `alluvia mcp`. Every referenced command must exist."""
import json
import os
import shutil
import subprocess
import pytest
from typer.main import get_command
import alluvia.cli as cli

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


def test_manifest_and_marketplace_agree():
    plugin = _load(".claude-plugin/plugin.json")
    market = _load(".claude-plugin/marketplace.json")
    assert plugin["name"] == "alluvia"
    assert market["plugins"][0]["name"] == "alluvia" and market["plugins"][0]["source"] == "./"


def test_hooks_reference_real_cli_commands():
    hooks = _load("hooks/hooks.json")["hooks"]
    assert set(hooks) == {"SessionStart", "SessionEnd", "PreCompact"}
    assert "compact" in hooks["SessionStart"][0]["matcher"]
    root = get_command(cli.app)
    hook_group = root.commands["hook"]
    for event, entries in hooks.items():
        for entry in entries:
            for h in entry["hooks"]:
                assert h["type"] == "command" and h["command"].startswith("alluvia hook ")
                sub = h["command"].split()[2]
                assert sub in hook_group.commands, f"{event} → {sub} is not a CLI command"
                assert h["timeout"] <= (10 if event == "SessionStart" else 180)


def test_mcp_manifest_runs_the_cli():
    mcp = _load(".mcp.json")
    assert mcp["alluvia"] == {"command": "alluvia", "args": ["mcp"]}


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI absent")
def test_claude_validates_the_plugin():
    r = subprocess.run(["claude", "plugin", "validate", "."], cwd=ROOT,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
