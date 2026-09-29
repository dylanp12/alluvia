"""The documented handoff includes inspectable source references."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_readme_shows_a_real_handoff():
    readme = _read("README.md")
    assert "alluvia · prior context for this repo" in readme
    assert re.search(r"\(session [0-9a-f]{8}\)", readme), "example lines carry their receipts"
