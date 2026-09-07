"""Managed distillation is the automatic fallback once signed in (0.9).

One thing to remember: `alluvia cloud login`. After that a refresh never
stalls: the user's own provider chain runs first and Alluvia Cloud's managed
gateway is the last candidate; with no provider key at all it is the only one.
The flag keeps its meanings at the edges: 0 never, 1 managed first."""
from alluvia import config
from alluvia.llm.client import ManagedKeyUnavailable, ManagedLLM, make_llm
from alluvia.llm.governor import CLIENT_ERROR, classify_exception

SESSION = {"url": "https://api.example.com", "token": "tok"}
KEY = {"key": "sk-v", "base_url": "https://gw.example.com/v1", "model": "alluvia-distill"}


def _env(monkeypatch, tmp_path, key=True):
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.setenv("ALLUVIA_LLM_PROVIDER", "groq")
    if key:
        monkeypatch.setenv("GROQ_API_KEY", "g")
    else:
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
    for v in ("ALLUVIA_MANAGED_DISTILL", "ALLUVIA_LLM_MODEL", "ALLUVIA_LLM_CHAIN",
              "ALLUVIA_LLM_MODEL_DISTILL", "ALLUVIA_LLM_CHAIN_DISTILL"):
        monkeypatch.delenv(v, raising=False)


def _models(llm):
    return [m for m, _ in llm.candidates]


def test_not_signed_in_keeps_the_provider_chain(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    llm = make_llm("distill", session_loader=lambda: None)
    assert _models(llm) == config.llm_chain("groq", "distill")


def test_signed_in_with_a_key_adds_managed_last(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    llm = make_llm("distill", session_loader=lambda: SESSION, key_fetcher=lambda u, t: KEY)
    models = _models(llm)
    assert models[:-1] == config.llm_chain("groq", "distill")
    assert models[-1] == "alluvia-cloud"
    assert isinstance(llm.candidates[-1][1], ManagedLLM)


def test_signed_in_without_a_key_is_managed_only(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, key=False)
    llm = make_llm("distill", session_loader=lambda: SESSION, key_fetcher=lambda u, t: KEY)
    assert _models(llm) == ["alluvia-cloud"]


def test_flag_off_never_uses_managed(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, key=False)
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "0")
    llm = make_llm("distill", session_loader=lambda: SESSION)
    assert "alluvia-cloud" not in _models(llm)


def test_flag_on_puts_managed_first(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "1")
    llm = make_llm("distill", session_loader=lambda: SESSION, key_fetcher=lambda u, t: KEY)
    models = _models(llm)
    assert models[0] == "alluvia-cloud"
    assert models[1:] == config.llm_chain("groq", "distill")


def test_other_roles_never_route_to_the_cloud(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    llm = make_llm("label", session_loader=lambda: SESSION)
    assert "alluvia-cloud" not in _models(llm)


def test_managed_llm_fetches_the_key_once_and_delegates(monkeypatch):
    from alluvia.llm import client as clientmod
    fetched, built, calls = [], [], []

    class FakeInner:
        def __init__(self, model, api_key=None, base_url=None, **kw):
            built.append((model, api_key, base_url))

        def complete_json(self, system, user):
            calls.append(user)
            return {"notes": []}

    monkeypatch.setattr(clientmod, "OpenAICompatLLM", FakeInner)
    llm = ManagedLLM(session_loader=lambda: SESSION,
                     key_fetcher=lambda u, t: fetched.append((u, t)) or KEY)
    assert llm.complete_json("s", "u1") == {"notes": []}
    assert llm.complete_json("s", "u2") == {"notes": []}
    assert fetched == [("https://api.example.com", "tok")]          # once per process
    assert built == [("alluvia-distill", "sk-v", "https://gw.example.com/v1")]
    assert calls == ["u1", "u2"]


def test_managed_llm_key_failure_is_terminal_for_this_run():
    llm = ManagedLLM(session_loader=lambda: SESSION, key_fetcher=lambda u, t: None)
    try:
        llm.complete_json("s", "u")
    except ManagedKeyUnavailable as e:
        assert classify_exception(e) == CLIENT_ERROR      # no blind retries; next candidate
    else:
        raise AssertionError("expected ManagedKeyUnavailable")


def test_flag_is_tri_state(monkeypatch, tmp_path):
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "none.toml"))
    monkeypatch.delenv("ALLUVIA_MANAGED_DISTILL", raising=False)
    assert config.managed_distillation() is None
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "false")
    assert config.managed_distillation() is False
    monkeypatch.setenv("ALLUVIA_MANAGED_DISTILL", "true")
    assert config.managed_distillation() is True


def _paused():
    return ({"distill": {"todo": 4, "ok": 1, "cold": True}, "retry_at": "2026-09-07T10:00:00"},
            {"sessions": 4, "distilled": 1, "pending": 3})


def test_pause_text_tells_the_signed_out_user_what_sign_in_changes(capsys):
    import alluvia.cli as cli
    stats, cov = _paused()
    cli._echo_refresh_summary(stats, coverage=cov, signed_in=False)
    out = capsys.readouterr().out
    assert "alluvia cloud login" in out and "$5/month" in out


def test_pause_text_names_pro_when_the_managed_budget_is_spent(capsys):
    import alluvia.cli as cli
    stats, cov = _paused()
    cli._echo_refresh_summary(stats, coverage=cov, signed_in=True, over_budget=True)
    out = capsys.readouterr().out
    assert "Pro" in out and "alluvia cloud status" in out
    cli._echo_refresh_summary(stats, coverage=cov, signed_in=True, over_budget=False)
    assert "cloud login" not in capsys.readouterr().out
