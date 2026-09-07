"""One pitch, everywhere it is visible. Four surfaces drift apart the moment
nobody checks; this checks."""
import json
import os
import re
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PITCH = "Your agent remembers this repo, and it will not lie about it."


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_readme_leads_with_the_pitch_and_the_install_path():
    readme = _read("README.md")
    head = readme[:2500]
    assert PITCH in head
    assert "/plugin install alluvia@alluvia" in head
    # the lenses are still documented, below the fold
    assert "alluvia connections" in readme and "alluvia unfinished" in readme
    assert readme.index(PITCH) < readme.index("## The lenses")


def test_pypi_and_plugin_descriptions_say_the_same_thing():
    py = tomllib.loads(_read("pyproject.toml"))
    plugin = json.loads(_read(".claude-plugin/plugin.json"))
    assert py["project"]["description"].startswith(PITCH)
    assert plugin["description"].startswith(PITCH)


def test_readme_shows_a_real_handoff():
    readme = _read("README.md")
    assert "alluvia · prior context for this repo" in readme
    assert re.search(r"\(session [0-9a-f]{8}\)", readme), "example lines carry their receipts"
