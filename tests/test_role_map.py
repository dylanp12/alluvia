from alluvia.llm.client import make_llm, OpenAICompatLLM


def test_role_env_beats_global_beats_default(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("SIFT_LLM_PROVIDER", "groq")
    monkeypatch.delenv("SIFT_LLM_MODEL", raising=False)
    monkeypatch.delenv("SIFT_LLM_MODEL_PROPOSE", raising=False)
    assert make_llm(role="propose").model == "llama-3.3-70b-versatile"  # provider default
    monkeypatch.setenv("SIFT_LLM_MODEL", "global-model")
    assert make_llm(role="propose").model == "global-model"             # global
    monkeypatch.setenv("SIFT_LLM_MODEL_PROPOSE", "propose-model")
    assert make_llm(role="propose").model == "propose-model"            # role wins
    assert make_llm(role="label").model == "global-model"               # other roles: global
    assert make_llm().model == "global-model"                           # no role: global


def test_all_five_roles_resolve(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("SIFT_LLM_PROVIDER", "groq")
    for role in ("distill", "label", "status", "why", "propose"):
        monkeypatch.setenv(f"SIFT_LLM_MODEL_{role.upper()}", f"{role}-model")
        llm = make_llm(role=role)
        assert isinstance(llm, OpenAICompatLLM) and llm.model == f"{role}-model"
