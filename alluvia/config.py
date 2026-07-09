"""Configuration. Precedence everywhere: env > ~/.alluvia/config.toml > defaults.

Every historical env var keeps working unchanged; the TOML file is the
onboarding-friendly layer underneath (written by `alluvia init`)."""
from __future__ import annotations
import os
import tomllib

DEFAULT_USER = "local"
DISTILL_MODEL = "claude-haiku-4-5-20251001"   # legacy constants (unused by make_llm)
LABEL_MODEL = "claude-haiku-4-5-20251001"
PIPELINE_VERSION = 2      # v2: message-level meta-strip (re-distill required)

LLM_PROVIDER = "groq"
_DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "groq": "llama-3.3-70b-versatile",
}
# Fallthrough chains (head first). On Groq's free tier each model has its own
# daily budget, so falling through to a sibling keeps the map alive when the
# head model hits a wall. Paid providers default to a single model.
_DEFAULT_CHAINS = {
    "groq": ["llama-3.3-70b-versatile", "openai/gpt-oss-120b",
             "llama-3.1-8b-instant"],
    "openai": ["gpt-4o-mini"],
    "anthropic": ["claude-haiku-4-5-20251001"],
}

_KEY_ENVS = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY",
             "anthropic": "ANTHROPIC_API_KEY"}

_toml_cache: dict | None = None


def config_path() -> str:
    return os.environ.get("ALLUVIA_CONFIG", os.path.expanduser("~/.alluvia/config.toml"))


def _toml() -> dict:
    global _toml_cache
    if _toml_cache is None:
        try:
            with open(config_path(), "rb") as f:
                _toml_cache = tomllib.load(f)
        except (FileNotFoundError, tomllib.TOMLDecodeError):
            _toml_cache = {}
    return _toml_cache


def reset_toml_cache() -> None:
    global _toml_cache
    _toml_cache = None


def db_path() -> str:
    return os.environ.get("ALLUVIA_DB",
                          _toml().get("store", {}).get("db")
                          or os.path.expanduser("~/.alluvia/alluvia.db"))


def llm_provider() -> str:
    return (os.environ.get("ALLUVIA_LLM_PROVIDER")
            or _toml().get("llm", {}).get("provider")
            or LLM_PROVIDER)


def llm_model(provider: str, role: str | None = None) -> str:
    llm = _toml().get("llm", {})
    if role:
        role_model = os.environ.get(f"ALLUVIA_LLM_MODEL_{role.upper()}")
        if role_model:
            return role_model
        toml_role = llm.get("roles", {}).get(role)
        if toml_role:
            return toml_role
    return (os.environ.get("ALLUVIA_LLM_MODEL")
            or llm.get("model")
            or _DEFAULT_MODELS[provider])


def _explicit_model(provider: str, role: str | None) -> str | None:
    """The model the user configured, or None if we'd fall back to defaults."""
    llm = _toml().get("llm", {})
    if role:
        found = (os.environ.get(f"ALLUVIA_LLM_MODEL_{role.upper()}")
                 or llm.get("roles", {}).get(role))
        if found:
            return found
    return os.environ.get("ALLUVIA_LLM_MODEL") or llm.get("model")


def llm_chain(provider: str, role: str | None = None) -> list[str]:
    """Ordered model candidates for a role (head first).

    `propose` never falls through — generation quality is user-facing, so it
    fails loud instead of silently downgrading. For other roles an explicit
    model override becomes the head of the default chain; ALLUVIA_LLM_CHAIN_<ROLE>
    (or [llm.chains] in config.toml) replaces the chain outright."""
    head = llm_model(provider, role)
    if role == "propose":
        return [head]
    raw = (os.environ.get(f"ALLUVIA_LLM_CHAIN_{role.upper()}") if role else None) \
        or os.environ.get("ALLUVIA_LLM_CHAIN") \
        or _toml().get("llm", {}).get("chains", {}).get(role or "default")
    if raw:
        parts = raw if isinstance(raw, list) else str(raw).split(",")
        return [p.strip() for p in parts if p.strip()]
    base = _DEFAULT_CHAINS.get(provider, [head])
    if _explicit_model(provider, role):
        return [head] + [m for m in base if m != head]
    return list(base) if base else [head]


def llm_patience() -> float:
    """Max seconds a single LLM call may spend sleeping on rate limits before
    the model's breaker opens and the chain falls through."""
    return float(os.environ.get("ALLUVIA_LLM_PATIENCE")
                 or _toml().get("llm", {}).get("patience")
                 or 90)


def provider_key(provider: str) -> str | None:
    env = _KEY_ENVS.get(provider)
    return ((os.environ.get(env) if env else None)
            or _toml().get("keys", {}).get(provider))


def digest_days() -> int:
    return int(os.environ.get("ALLUVIA_DIGEST_DAYS")
               or _toml().get("digest", {}).get("days")
               or 7)


def digest_proposals_enabled() -> bool:
    env = os.environ.get("ALLUVIA_DIGEST_PROPOSALS")
    if env is not None:
        return env != "0"
    return bool(_toml().get("digest", {}).get("proposals", True))


def min_cluster() -> int | None:
    env = os.environ.get("ALLUVIA_MIN_CLUSTER")
    if env:
        return int(env)
    v = _toml().get("engine", {}).get("min_cluster")
    return int(v) if v else None


def source_root(flavor: str) -> str | None:
    return _toml().get("sources", {}).get(flavor)


def write_config(data: dict) -> str:
    """Write config.toml (simple flat emitter — our schema is 2 levels max).
    chmod 0600 because [keys] may hold API keys."""
    path = config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines: list[str] = []
    for section, values in data.items():
        lines.append(f"[{section}]")
        for k, v in values.items():
            if isinstance(v, dict):
                continue                      # nested tables emitted below
            if isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            elif isinstance(v, (int, float)):
                lines.append(f"{k} = {v}")
            else:
                lines.append(f'{k} = "{v}"')
        for k, v in values.items():
            if isinstance(v, dict):
                lines.append(f"[{section}.{k}]")
                for k2, v2 in v.items():
                    lines.append(f'{k2} = "{v2}"')
        lines.append("")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    os.chmod(path, 0o600)
    reset_toml_cache()
    return path
