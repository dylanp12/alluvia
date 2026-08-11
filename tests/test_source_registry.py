import pytest

from alluvia.ingest import SOURCES


def test_registry_has_all_slugs():
    for slug in ["claude-code", "cursor", "windsurf", "antigravity", "jsonl",
                 "chatgpt-export", "cline", "kilo-code", "roo-code"]:
        assert slug in SOURCES


def test_existing_sources_build_without_path():
    for slug in ["cursor", "windsurf", "antigravity"]:
        assert SOURCES[slug](None) is not None          # fork root optional


def test_path_required_sources_raise():
    for slug in ["jsonl", "chatgpt-export"]:
        with pytest.raises(ValueError):
            SOURCES[slug](None)
