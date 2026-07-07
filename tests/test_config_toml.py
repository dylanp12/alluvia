import os
import stat
from alluvia import config


CFG = """
[llm]
provider = "openai"
model = "toml-global"

[llm.roles]
propose = "toml-propose"

[digest]
days = 3
proposals = false

[engine]
min_cluster = 5

[sources]
cursor = "/custom/cursor"

[keys]
groq = "toml-key"
"""


def _use(tmp_path, monkeypatch, text=CFG):
    p = tmp_path / "config.toml"
    p.write_text(text)
    monkeypatch.setenv("SIFT_CONFIG", str(p))
    for var in ("SIFT_LLM_PROVIDER", "SIFT_LLM_MODEL", "SIFT_LLM_MODEL_PROPOSE",
                "SIFT_DIGEST_DAYS", "SIFT_DIGEST_PROPOSALS", "SIFT_MIN_CLUSTER",
                "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    config.reset_toml_cache()
    return p


def test_toml_values_used_when_env_absent(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    assert config.llm_provider() == "openai"
    assert config.llm_model("openai") == "toml-global"
    assert config.llm_model("openai", role="propose") == "toml-propose"
    assert config.digest_days() == 3
    assert config.digest_proposals_enabled() is False
    assert config.min_cluster() == 5
    assert config.source_root("cursor") == "/custom/cursor"
    assert config.provider_key("groq") == "toml-key"


def test_env_beats_toml(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    monkeypatch.setenv("SIFT_LLM_PROVIDER", "groq")
    monkeypatch.setenv("SIFT_LLM_MODEL_PROPOSE", "env-propose")
    monkeypatch.setenv("SIFT_DIGEST_DAYS", "11")
    monkeypatch.setenv("GROQ_API_KEY", "env-key")
    assert config.llm_provider() == "groq"
    assert config.llm_model("groq", role="propose") == "env-propose"
    assert config.digest_days() == 11
    assert config.provider_key("groq") == "env-key"


def test_missing_file_means_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_CONFIG", str(tmp_path / "absent.toml"))
    for var in ("SIFT_LLM_PROVIDER", "SIFT_DIGEST_DAYS"):
        monkeypatch.delenv(var, raising=False)
    config.reset_toml_cache()
    assert config.llm_provider() == "groq"
    assert config.digest_days() == 7


def test_write_config_0600_and_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SIFT_CONFIG", str(tmp_path / "c.toml"))
    config.reset_toml_cache()
    path = config.write_config({"llm": {"provider": "groq",
                                        "roles": {"propose": "big-model"}},
                                "keys": {"groq": "gsk-x"}})
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600
    assert config.llm_provider() == "groq"
    assert config.llm_model("groq", role="propose") == "big-model"
    assert config.provider_key("groq") == "gsk-x"
