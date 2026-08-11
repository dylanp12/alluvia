"""Sync policy: what leaves this machine, per source. Default derived_only —
raw sessions never leave unless a source is explicitly set to raw."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field

MODES = ("none", "derived_only", "excerpt", "raw")


def config_path() -> str:
    return os.environ.get("ALLUVIA_CLOUD_CONFIG",
                          os.path.expanduser("~/.alluvia/cloud.toml"))


@dataclass
class Policy:
    default: str = "derived_only"
    per_source: dict[str, str] = field(default_factory=dict)

    def mode_for(self, source: str) -> str:
        return self.per_source.get(source, self.default)


def load_policy() -> Policy:
    try:
        with open(config_path(), "rb") as f:
            data = tomllib.load(f)
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        data = {}
    default = data.get("cloud", {}).get("default_mode", "derived_only")
    per_source = {s: v.get("sync") for s, v in data.get("sources", {}).items()
                  if v.get("sync")}
    for m in [default, *per_source.values()]:
        if m not in MODES:
            raise ValueError(f"invalid sync mode {m!r}; expected one of {MODES}")
    return Policy(default=default, per_source=per_source)
