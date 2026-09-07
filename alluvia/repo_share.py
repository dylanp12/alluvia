"""Opt-in repo-committed memory: .alluvia/memory.jsonl inside the repository.

Distilled, scrubbed notes only — no receipts, no raw, no titles. Written after
each capture and refresh while sharing is on; imported on session start when
its hash changed, so a fresh clone or a second machine starts with the repo's
memory. Committing .alluvia/ is the user's act; alluvia never touches git."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from alluvia.memory_bundle import export_bundle, import_bundle
from alluvia.projects import project_key

DIRNAME = ".alluvia"
FILENAME = "memory.jsonl"
CONFIG = "config.toml"


def share_dir(root: str) -> Path:
    return Path(root) / DIRNAME


def share_file(root: str) -> Path:
    return share_dir(root) / FILENAME


def is_shared(root: str) -> bool:
    cfg = share_dir(root) / CONFIG
    return cfg.exists() and "share = true" in cfg.read_text(encoding="utf-8")


def set_shared(root: str, on: bool) -> None:
    d = share_dir(root)
    if on:
        d.mkdir(parents=True, exist_ok=True)
        (d / CONFIG).write_text(
            "# alluvia: this repository carries its own distilled memory\n"
            "# (notes only — never raw conversations). Commit this directory to share it.\n"
            "share = true\n", encoding="utf-8")
        return
    for f in (d / CONFIG, share_file(root)):
        if f.exists():
            f.unlink()
    if d.exists() and not any(d.iterdir()):
        d.rmdir()


def write_share(repo, user_id: str, root: str) -> int:
    """Write the repository's memory file; returns the note count."""
    recs = list(export_bundle(repo, user_id, project=root, project_relative=True))
    share_dir(root).mkdir(parents=True, exist_ok=True)
    share_file(root).write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in recs) + "\n", encoding="utf-8")
    return sum(1 for r in recs if r["kind"] == "note")


def import_share_if_changed(repo, user_id: str, root: str, embedder=None) -> dict | None:
    """Import the repo's memory file when its content changed since the last
    import. SQLite only unless an embedder is given. None when nothing to do."""
    f = share_file(root)
    if not f.exists():
        return None
    data = f.read_bytes()
    digest = hashlib.sha1(data).hexdigest()
    key = f"repo_memory:{project_key(root)}"
    if repo.get_meta(key) == digest:
        return None
    records = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"kind": "malformed"})
    out = import_bundle(repo, user_id, records, embedder=embedder, bind_project=root)
    repo.set_meta(key, digest)
    return out
