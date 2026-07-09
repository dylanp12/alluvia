"""Role -> model fallthrough chains (issue #3 §4) and governed make_llm."""
from alluvia import config
from alluvia.llm.client import make_llm, OpenAICompatLLM, RoleRouter, FakeLLM
from alluvia.llm.governor import Governor, MemoryHealthStore


def _groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("ALLUVIA_LLM_PROVIDER", "groq")
    for v in ("ALLUVIA_LLM_MODEL", "ALLUVIA_LLM_CHAIN"):
        monkeypatch.delenv(v, raising=False)
    for role in ("DISTILL", "LABEL", "STATUS", "WHY", "PROPOSE"):
        monkeypatch.delenv(f"ALLUVIA_LLM_MODEL_{role}", raising=False)
        monkeypatch.delenv(f"ALLUVIA_LLM_CHAIN_{role}", raising=False)


def test_groq_default_chain_has_fallthrough(monkeypatch):
    _groq(monkeypatch)
    chain = config.llm_chain("groq", "label")
    assert chain[0] == "llama-3.3-70b-versatile"        # head = provider default
    assert len(chain) >= 2                              # real fallbacks behind it


def test_role_model_env_overrides_head_keeps_tail(monkeypatch):
    _groq(monkeypatch)
    monkeypatch.setenv("ALLUVIA_LLM_MODEL_LABEL", "my-model")
    chain = config.llm_chain("groq", "label")
    assert chain[0] == "my-model"
    assert len(chain) >= 2                              # default tail still there
    assert "my-model" not in chain[1:]


def test_chain_env_replaces_whole_chain(monkeypatch):
    _groq(monkeypatch)
    monkeypatch.setenv("ALLUVIA_LLM_CHAIN_LABEL", "a, b ,c")
    assert config.llm_chain("groq", "label") == ["a", "b", "c"]


def test_propose_never_falls_through(monkeypatch):
    _groq(monkeypatch)
    assert config.llm_chain("groq", "propose") == ["llama-3.3-70b-versatile"]
    monkeypatch.setenv("ALLUVIA_LLM_MODEL_PROPOSE", "strong-model")
    assert config.llm_chain("groq", "propose") == ["strong-model"]


def test_single_model_defaults_for_paid_providers(monkeypatch):
    _groq(monkeypatch)
    assert config.llm_chain("openai", "label") == ["gpt-4o-mini"]
    assert config.llm_chain("anthropic", "label") == ["claude-haiku-4-5-20251001"]


def test_make_llm_returns_governed_chain(monkeypatch):
    _groq(monkeypatch)
    llm = make_llm(role="label")
    assert isinstance(llm, Governor)
    assert llm.provider == "groq"
    assert llm.model == "llama-3.3-70b-versatile"
    models = [m for m, _ in llm.candidates]
    assert models == config.llm_chain("groq", "label")
    adapter = llm.candidates[0][1]
    assert isinstance(adapter, OpenAICompatLLM)
    assert adapter.base_url == "https://api.groq.com/openai/v1"


def test_make_llm_shares_injected_health_store(monkeypatch):
    _groq(monkeypatch)
    store = MemoryHealthStore()
    a = make_llm(role="label", health=store)
    b = make_llm(role="status", health=store)
    assert a.store is store and b.store is store        # one breaker table


def test_role_router_builds_lazily_and_caches(monkeypatch):
    _groq(monkeypatch)
    built = []

    def factory(role=None, health=None):
        built.append(role)
        return FakeLLM([{"ok": role}])

    router = RoleRouter(build=factory)
    assert built == []                                  # nothing built up front
    llm = router.for_role("label")
    assert router.for_role("label") is llm              # cached
    assert built == ["label"]
    assert router.complete_json("s", "u") == {"ok": None}   # default role
