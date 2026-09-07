"""Project identity for sessions and hooks.

A session belongs to the git repository it ran in (the directory holding
`.git`), or to its working directory when no repository is visible. The
root is resolved on this machine only; a path recorded on another machine
is kept verbatim so it still groups that machine's sessions together."""
from __future__ import annotations

import hashlib
import os


def project_root(cwd: str | None, isdir=os.path.isdir) -> str | None:
    if not cwd:
        return None
    cur = os.path.normpath(cwd)
    probe = cur
    while True:
        if isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return cur
        probe = parent


def project_key(path: str) -> str:
    return hashlib.sha1(os.path.normpath(path).encode("utf-8")).hexdigest()[:12]


def project_name(path: str) -> str:
    return os.path.basename(os.path.normpath(path)) or path
