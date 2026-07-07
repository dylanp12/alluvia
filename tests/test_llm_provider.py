import pytest
from alluvia.llm.client import make_llm, OpenAICompatLLM, AnthropicLLM


def test_make_llm_selects_groq_openai_anthropic(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")

    monkeypatch.setenv("SIFT_LLM_PROVIDER", "groq")
    monkeypatch.setenv("SIFT_LLM_MODEL", "llama-x")
    g = make_llm()
    assert isinstance(g, OpenAICompatLLM)
    assert g.base_url == "https://api.groq.com/openai/v1"
    assert g.model == "llama-x"

    monkeypatch.setenv("SIFT_LLM_PROVIDER", "openai")
    monkeypatch.delenv("SIFT_LLM_MODEL", raising=False)
    o = make_llm()
    assert isinstance(o, OpenAICompatLLM)
    assert o.base_url is None          # openai SDK default endpoint

    monkeypatch.setenv("SIFT_LLM_PROVIDER", "anthropic")
    assert isinstance(make_llm(), AnthropicLLM)


def test_make_llm_unknown_provider_errors(monkeypatch):
    monkeypatch.setenv("SIFT_LLM_PROVIDER", "nope")
    with pytest.raises(ValueError):
        make_llm()
