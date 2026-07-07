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

_KEY_ENVS = {"groq": "GROQ_API_KEY", "openai": "OPENAI_API_KEY",
             "anthropic": "ANTHROPIC_API_KEY"}

_toml_cache: dict | None = None


def config_path() -> str:
    return os.environ.get("SIFT_CONFIG", os.path.expanduser("~/.alluvia/config.toml"))


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
    return os.environ.get("SIFT_DB",
                          _toml().get("store", {}).get("db")
                          or os.path.expanduser("~/.alluvia/alluvia.db"))


def llm_provider() -> str:
    return (os.environ.get("SIFT_LLM_PROVIDER")
            or _toml().get("llm", {}).get("provider")
            or LLM_PROVIDER)


def llm_model(provider: str, role: str | None = None) -> str:
    llm = _toml().get("llm", {})
    if role:
        role_model = os.environ.get(f"SIFT_LLM_MODEL_{role.upper()}")
        if role_model:
            return role_model
        toml_role = llm.get("roles", {}).get(role)
        if toml_role:
            return toml_role
    return (os.environ.get("SIFT_LLM_MODEL")
            or llm.get("model")
            or _DEFAULT_MODELS[provider])


def provider_key(provider: str) -> str | None:
    env = _KEY_ENVS.get(provider)
    return ((os.environ.get(env) if env else None)
            or _toml().get("keys", {}).get(provider))


def digest_days() -> int:
    return int(os.environ.get("SIFT_DIGEST_DAYS")
               or _toml().get("digest", {}).get("days")
               or 7)


def digest_proposals_enabled() -> bool:
    env = os.environ.get("SIFT_DIGEST_PROPOSALS")
    if env is not None:
        return env != "0"
    return bool(_toml().get("digest", {}).get("proposals", True))


def min_cluster() -> int | None:
    env = os.environ.get("SIFT_MIN_CLUSTER")
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
