"""Sync policy: per-source mode from ~/.alluvia/cloud.toml, default derived_only."""
from alluvia.cloudsync.policy import Policy, load_policy


def test_default_is_derived_only(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_CLOUD_CONFIG", str(tmp_path / "none.toml"))
    p = load_policy()
    assert p.mode_for("claude-code") == "derived_only"
    assert p.default == "derived_only"


def test_per_source_overrides(tmp_path, monkeypatch):
    cfg = tmp_path / "cloud.toml"
    cfg.write_text(
        '[cloud]\ndefault_mode = "excerpt"\n'
        '[sources.chatgpt-export]\nsync = "none"\n'
        '[sources.claude-code]\nsync = "derived_only"\n')
    monkeypatch.setenv("ALLUVIA_CLOUD_CONFIG", str(cfg))
    p = load_policy()
    assert p.default == "excerpt"
    assert p.mode_for("chatgpt-export") == "none"
    assert p.mode_for("claude-code") == "derived_only"
    assert p.mode_for("cursor") == "excerpt"        # falls back to default


def test_invalid_mode_rejected(tmp_path, monkeypatch):
    cfg = tmp_path / "cloud.toml"
    cfg.write_text('[cloud]\ndefault_mode = "everything"\n')
    monkeypatch.setenv("ALLUVIA_CLOUD_CONFIG", str(cfg))
    import pytest
    with pytest.raises(ValueError):
        load_policy()
