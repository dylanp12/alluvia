"""The managed-distillation preference flag. Chain composition lives in
test_llm_managed_fallback.py."""


def test_managed_distillation_flag(monkeypatch, tmp_path):
    from alluvia import config
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "1")
    assert config.managed_distillation() is True
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "off")
    assert config.managed_distillation() is False
    monkeypatch.delenv("ALLUVIA_MANAGED_DISTILL")
    assert config.managed_distillation() is None                 # automatic


def test_toml_preference_is_honoured(monkeypatch, tmp_path):
    from alluvia import config
    monkeypatch.delenv("ALLUVIA_MANAGED_DISTILL", raising=False)
    cfg = tmp_path / "c.toml"
    cfg.write_text("[cloud]\nmanaged_distillation = false\n")
    monkeypatch.setenv("ALLUVIA_CONFIG", str(cfg))
    config.reset_toml_cache()
    assert config.managed_distillation() is False
