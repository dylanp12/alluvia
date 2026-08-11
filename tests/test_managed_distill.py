def test_managed_distillation_flag(monkeypatch):
    from alluvia import config
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "1")
    assert config.managed_distillation() is True
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "off")
    assert config.managed_distillation() is False


def test_managed_distill_llm_none_when_not_logged_in(monkeypatch):
    import alluvia.cloudclient as cc
    from alluvia.llm import client as clientmod
    monkeypatch.setattr(cc, "load_session", lambda: None)
    assert clientmod._managed_distill_llm() is None


def test_managed_distill_llm_builds_from_cloud(monkeypatch):
    import alluvia.cloudclient as cc
    from alluvia.llm import client as clientmod
    monkeypatch.setattr(cc, "load_session", lambda: {"url": "https://app", "token": "t"})
    monkeypatch.setattr(cc, "fetch_distill_key",
                        lambda url, tok: {"key": "sk-v", "base_url": "https://gw", "model": "alluvia-distill"})
    llm = clientmod._managed_distill_llm()
    assert llm is not None                          # a Governor over the gateway adapter


def test_make_llm_distill_uses_managed_when_enabled(monkeypatch):
    from alluvia.llm import client as clientmod
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "1")
    sentinel = object()
    monkeypatch.setattr(clientmod, "_managed_distill_llm", lambda health=None, on_wait=None: sentinel)
    assert clientmod.make_llm(role="distill") is sentinel   # opt-in routes distill -> managed
