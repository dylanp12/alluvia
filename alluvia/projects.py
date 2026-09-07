"""Project identity for sessions and hooks.

A session belongs to the git repository it ran in (the directory holding
`.git`), or to its working directory when no repository is visible. The
root is resolved on this machine only; a path recorded on another machine
or OS is an opaque key and is kept verbatim (only a trailing separator is
dropped), so it still groups that machine's sessions together."""
from __future__ import annotations

import hashlib
import os

_SEPS = "/\\"


def _strip(path: str) -> str:
    stripped = path.rstrip(_SEPS)
    return stripped or path


def _canon(path: str) -> str:
    """Separator-normalized form for keys and names: the same repository
    keys identically whether the path was written with / or \\."""
    return _strip(path.replace("\\", "/"))


def project_root(cwd: str | None, isdir=os.path.isdir) -> str | None:
    if not cwd:
        return None
    cur = _strip(cwd)
    probe = cur
    while True:
        if isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if not parent or parent == probe:
            return cur
        probe = parent


def project_key(path: str) -> str:
    return hashlib.sha1(_canon(path).encode("utf-8")).hexdigest()[:12]


def project_name(path: str) -> str:
    return _canon(path).rsplit("/", 1)[-1] or path
