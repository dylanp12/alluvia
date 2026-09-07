from __future__ import annotations
import json
import os
import re
from typing import Any, Protocol

from alluvia import config


class LLM(Protocol):
    def complete_json(self, system: str, user: str) -> Any: ...


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text).strip()
    return json.loads(text)


class AnthropicLLM:
    """Anthropic Messages API. Client constructed lazily (no key needed to build)."""
    def __init__(self, model: str, api_key: str | None = None, max_tokens: int = 1024):
        self.model = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._client = None

    def _client_(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete_json(self, system: str, user: str) -> Any:
        resp = self._client_().messages.create(
            model=self.model, max_tokens=self._max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return _extract_json(resp.content[0].text)


class OpenAICompatLLM:
    """OpenAI-compatible chat completions — serves OpenAI and Groq (custom base_url).
    Client constructed lazily so building an engine needs no API key."""
    def __init__(self, model: str, api_key: str | None = None,
                 base_url: str | None = None, max_tokens: int = 1024):
        self.model = model
        self.base_url = base_url
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._client = None

    def _client_(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key, base_url=self.base_url)
        return self._client

    def complete_json(self, system: str, user: str) -> Any:
        resp = self._client_().chat.completions.create(
            model=self.model, max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return _extract_json(resp.choices[0].message.content)


class FakeLLM:
    def __init__(self, responses: list[Any]):
        self._responses = list(responses)
        self._i = 0

    def complete_json(self, system: str, user: str) -> Any:
        r = self._responses[self._i]
        self._i += 1
        return r


def _adapter(provider: str, model: str, key: str | None) -> LLM:
    if provider == "anthropic":
        return AnthropicLLM(model, api_key=key)
    if provider == "openai":
        return OpenAICompatLLM(model, api_key=key)
    return OpenAICompatLLM(model, api_key=key,
                           base_url="https://api.groq.com/openai/v1")


# Shared within one process so every role sees the same breaker state; the
# CLI/MCP entrypoints swap in the SQLite-backed store for cross-run memory.
_process_health = None


def _default_health():
    global _process_health
    if _process_health is None:
        from alluvia.llm.governor import MemoryHealthStore
        _process_health = MemoryHealthStore()
    return _process_health


class ManagedKeyUnavailable(Exception):
    """The account's managed key could not be fetched (signed out, offline, or
    the service refused). Classified like a 401 so the Governor treats it as
    terminal for this run and moves to the next candidate instead of sleeping."""
    status_code = 401


class ManagedLLM:
    """Alluvia Cloud's managed distillation as one candidate in the chain.
    Lazy: the account's virtual key is fetched from the service on first use
    and cached for the process; nothing is fetched when the user's own provider
    answers first. Transcripts are secret+PII scrubbed before any LLM sees them."""
    model = "alluvia-cloud"

    def __init__(self, session_loader=None, key_fetcher=None):
        from alluvia import cloudclient
        self._load = session_loader or cloudclient.load_session
        self._fetch = key_fetcher or cloudclient.fetch_distill_key
        self._inner = None

    def _inner_(self):
        if self._inner is None:
            sess = self._load() or {}
            info = None
            if sess.get("url") and sess.get("token"):
                info = self._fetch(sess["url"], sess["token"])
            if not info or not info.get("key") or not info.get("base_url"):
                raise ManagedKeyUnavailable(
                    "managed distillation unavailable: could not fetch the account key "
                    "(alluvia cloud status)")
            self._inner = OpenAICompatLLM(info.get("model") or "alluvia-distill",
                                          api_key=info["key"], base_url=info["base_url"])
        return self._inner

    def complete_json(self, system: str, user: str) -> Any:
        return self._inner_().complete_json(system, user)


def _signed_in(session_loader) -> bool:
    from alluvia import cloudclient
    sess = (session_loader or cloudclient.load_session)()
    return bool(sess and sess.get("token") and sess.get("url"))


def make_llm(role: str | None = None, health=None, on_wait=None,
             session_loader=None, key_fetcher=None) -> LLM:
    """Role-aware factory: ALLUVIA_LLM_MODEL_<ROLE> -> ALLUVIA_LLM_MODEL -> provider
    default, expanded to the role's fallthrough chain and wrapped in a
    Governor (backoff, per-model breakers, chain fallthrough — see
    llm/governor.py). Roles: distill, label, status, why, propose.

    Distill only, once signed in to Alluvia Cloud: the managed gateway joins the
    chain — last by default, first when ALLUVIA_MANAGED_DISTILL=1, alone when no
    provider key is configured, never when =0. A refresh does not stall on one
    rate-limited provider."""
    from alluvia.llm.governor import Governor
    provider = config.llm_provider()
    if provider not in ("anthropic", "openai", "groq"):
        raise ValueError(f"unknown ALLUVIA_LLM_PROVIDER: {provider}")
    key = config.provider_key(provider)          # env > config.toml [keys]
    candidates = [(m, _adapter(provider, m, key))
                  for m in config.llm_chain(provider, role)]
    pref = config.managed_distillation() if role == "distill" else False
    if pref is not False and _signed_in(session_loader):
        managed = (ManagedLLM.model, ManagedLLM(session_loader, key_fetcher))
        if pref is True:
            candidates = [managed] + candidates
        elif key is None:
            candidates = [managed]
        else:
            candidates = candidates + [managed]
    return Governor(provider, candidates,
                    store=health if health is not None else _default_health(),
                    patience=config.llm_patience(), on_wait=on_wait)


class RoleRouter:
    """Lazy per-role LLMs behind one object. The engine asks `for_role(...)` at
    each call site; plain LLMs (tests, single-model setups) skip the router."""

    def __init__(self, build=make_llm, health=None, on_wait=None):
        self._build = build
        self._health = health
        self._on_wait = on_wait
        self._cache: dict[str | None, LLM] = {}

    def for_role(self, role: str | None) -> LLM:
        if role not in self._cache:
            kwargs = {"role": role, "health": self._health}
            if self._on_wait is not None:
                kwargs["on_wait"] = self._on_wait
            self._cache[role] = self._build(**kwargs)
        return self._cache[role]

    def complete_json(self, system: str, user: str) -> Any:
        return self.for_role(None).complete_json(system, user)
