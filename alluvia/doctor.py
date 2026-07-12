"""Doctor: diagnose the whole installation and repair what is safe to repair.

Safe repairs are zero-data-loss and idempotent — they touch only DERIVED
state (rebuildable from raw) or file metadata. Raw sessions and judgments
(proposals, digests, mutes) are never modified by auto-repair; the one lever
that discards derived data wholesale (`rebuild_derived`) is a separate,
explicitly-confirmed call.

In check-only mode repairable problems are reported (status "warn",
repairable=True) and left untouched.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from alluvia import config

STALE_REFRESH_DAYS = 14
COOLDOWN_SANITY_S = 25 * 3600      # governor pins at 24h; beyond that is bogus


@dataclass
class Finding:
    name: str
    status: str                    # ok | repaired | warn | fail
    detail: str = ""
    remedy: str | None = None
    repairable: bool = field(default=False)


def _fixable(name: str, detail: str, fixed: bool, fix_msg: str) -> Finding:
    if fixed:
        return Finding(name, "repaired", detail)
    return Finding(name, "warn", detail, remedy=fix_msg, repairable=True)


def _wal(repo, fix: bool) -> Finding:
    mode = repo.conn.execute("PRAGMA journal_mode").fetchone()[0]
    if mode == "wal":
        return Finding("wal journal", "ok", "concurrent readers/writer enabled")
    if fix:
        repo.conn.execute("PRAGMA journal_mode = WAL")
        repo.conn.execute("PRAGMA busy_timeout = 10000")
    return _fixable("wal journal", f"journal mode was {mode}", fix,
                    "doctor enables WAL so concurrent sessions don't block")


def _schema(repo, fix: bool) -> Finding:
    from alluvia.store.db import init_schema
    before = {r[0] for r in repo.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not fix:
        return Finding("schema", "ok", f"{len(before)} tables present")
    dim = repo.conn.execute(
        "SELECT value FROM meta WHERE key='embed_dim'").fetchone()
    init_schema(repo.conn, embed_dim=int(dim[0]) if dim else 384)
    after = {r[0] for r in repo.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if after - before:
        return Finding("schema", "repaired",
                       f"created missing tables: {', '.join(sorted(after - before))}")
    return Finding("schema", "ok", f"{len(after)} tables, migrations current")


def _orphan_embeddings(repo, fix: bool) -> Finding:
    n = repo.conn.execute(
        "SELECT COUNT(*) FROM note_embeddings e WHERE NOT EXISTS "
        "(SELECT 1 FROM notes n WHERE n.user_id=e.user_id AND n.id=e.note_id)"
    ).fetchone()[0]
    if not n:
        return Finding("orphaned embeddings", "ok", "none")
    if fix:
        repo.conn.execute(
            "DELETE FROM note_embeddings WHERE NOT EXISTS "
            "(SELECT 1 FROM notes n WHERE n.user_id=note_embeddings.user_id "
            "AND n.id=note_embeddings.note_id)")
        repo.conn.commit()
    return _fixable("orphaned embeddings", f"{n} row(s) without a note", fix,
                    "doctor prunes them (derived data; the vector index self-heals)")


def _dangling_links(repo, fix: bool) -> Finding:
    cond = ("NOT EXISTS (SELECT 1 FROM notes n WHERE n.user_id=links.user_id "
            "AND n.id=links.from_note_id) OR NOT EXISTS "
            "(SELECT 1 FROM notes n WHERE n.user_id=links.user_id "
            "AND n.id=links.to_note_id)")
    n = repo.conn.execute(f"SELECT COUNT(*) FROM links WHERE {cond}").fetchone()[0]
    if not n:
        return Finding("dangling links", "ok", "none")
    if fix:
        repo.conn.execute(f"DELETE FROM links WHERE {cond}")
        repo.conn.commit()
    return _fixable("dangling links", f"{n} link(s) to missing notes", fix,
                    "doctor prunes them (recomputed on every refresh)")


def _config_perms(repo, fix: bool) -> Finding:
    path = config.config_path()
    if os.name == "nt" or not os.path.exists(path):
        return Finding("config permissions", "ok",
                       "no config file" if not os.path.exists(path) else "n/a")
    mode = os.stat(path).st_mode & 0o777
    if mode == 0o600:
        return Finding("config permissions", "ok", "0600")
    if fix:
        os.chmod(path, 0o600)
    return _fixable("config permissions", f"was {oct(mode)[2:]} (may hold API keys)",
                    fix, "doctor chmods it to 0600")


def _pending_flag(repo, fix: bool) -> Finding:
    flag = os.environ.get("ALLUVIA_PENDING_FLAG",
                          os.path.expanduser("~/.alluvia/digest-pending"))
    if not os.path.exists(flag):
        return Finding("digest flag", "ok", "no pending flag")
    if repo.latest_digest(config.DEFAULT_USER) is not None:
        return Finding("digest flag", "ok", "flag matches an existing digest")
    if fix:
        os.remove(flag)
    return _fixable("digest flag", "flag set but no digest exists", fix,
                    "doctor removes the stale flag")


def _cooldowns(repo, fix: bool) -> Finding:
    horizon = time.time() + COOLDOWN_SANITY_S
    bogus = [r for r in repo.llm_health_all() if r["cooldown_until"] > horizon]
    if not bogus:
        return Finding("llm cooldowns", "ok",
                       f"{len(repo.llm_health_all())} model record(s), all sane")
    if fix:
        for r in bogus:
            r.update(cooldown_until=0.0, rung=0, consecutive=0)
            repo.llm_health_save(r["provider"], r["model"], r)
    names = ", ".join(f"{r['provider']}/{r['model']}" for r in bogus)
    return _fixable("llm cooldowns", f"impossible cooldown on {names}", fix,
                    "doctor resets those governor records")


def _provider_key(repo) -> Finding:
    provider = config.llm_provider()
    if config.provider_key(provider):
        return Finding("provider key", "ok", f"{provider} key configured")
    return Finding("provider key", "fail", f"no key for provider '{provider}'",
                   remedy="run `alluvia init` or set the provider's API key env var")


def _sources(repo) -> Finding:
    import glob
    from alluvia.platform import claude_code_root
    found = []
    cc = config.source_root("claude-code") or claude_code_root()
    if os.path.isdir(cc):
        n = len(glob.glob(os.path.join(cc, "**", "*.jsonl"), recursive=True))
        found.append(f"claude-code ({n} files)")
    if not found:
        return Finding("sources", "warn", "no sources auto-detected",
                       remedy="ingest with --source/--path, or check `alluvia init`")
    return Finding("sources", "ok", ", ".join(found))


def _model_cache(repo) -> Finding:
    from alluvia.inspect import model_cache_dir
    d = model_cache_dir()
    if os.path.isdir(d) and any(os.scandir(d)):
        return Finding("embedding model", "ok", f"cached at {d}")
    return Finding("embedding model", "warn", "not downloaded yet",
                   remedy="first `alluvia refresh` downloads it (~100 MB, one time)")


def _last_refresh(repo) -> Finding:
    import json
    from datetime import datetime, timezone
    raw = repo.get_meta("last_refresh")
    if not raw:
        return Finding("last refresh", "warn", "never ran",
                       remedy="run `alluvia refresh`")
    try:
        meta = json.loads(raw)
    except ValueError:
        return Finding("last refresh", "warn", "unreadable record",
                       remedy="run `alluvia refresh`")
    if meta.get("degraded"):
        return Finding("last refresh", "warn",
                       "degraded by provider rate limits",
                       remedy="re-run `alluvia refresh` when the provider has headroom")
    try:
        at = datetime.fromisoformat(meta["at"])
        age = (datetime.now(timezone.utc) - at).days
        if age > STALE_REFRESH_DAYS:
            return Finding("last refresh", "warn", f"{age} days ago",
                           remedy="run `alluvia refresh` to fold in new sessions")
        return Finding("last refresh", "ok", f"{age} day(s) ago, healthy")
    except (KeyError, ValueError):
        return Finding("last refresh", "ok", "recorded")


def _pipeline_drift(repo) -> Finding:
    n = repo.conn.execute(
        "SELECT COUNT(DISTINCT session_id) FROM notes WHERE pipeline_version < ?",
        (config.PIPELINE_VERSION,)).fetchone()[0]
    if n:
        return Finding("pipeline version", "warn",
                       f"{n} session(s) distilled by an older pipeline",
                       remedy="next `alluvia refresh` re-distills them automatically")
    return Finding("pipeline version", "ok", f"v{config.PIPELINE_VERSION} everywhere")


def _integrity(repo) -> Finding:
    row = repo.conn.execute("PRAGMA quick_check").fetchone()[0]
    if row == "ok":
        return Finding("store integrity", "ok", "quick_check passed")
    return Finding("store integrity", "fail", str(row)[:120],
                   remedy="back up the store file, then `alluvia doctor "
                          "--rebuild-derived` (raw + judgments survive)")


def _live(llm) -> Finding:
    try:
        llm.complete_json('Return exactly {"ok": true}.', "ping")
        return Finding("provider round-trip", "ok",
                       f"model {getattr(llm, 'model', '?')} answered")
    except Exception as e:
        return Finding("provider round-trip", "fail", str(e)[:120],
                       remedy="check the key, provider status, and rate limits")


def run_doctor(repo, *, check_only: bool = False, live: bool = False,
               llm=None) -> list[Finding]:
    fix = not check_only
    findings = [
        _wal(repo, fix),
        _schema(repo, fix),
        _integrity(repo),
        _orphan_embeddings(repo, fix),
        _dangling_links(repo, fix),
        _config_perms(repo, fix),
        _pending_flag(repo, fix),
        _cooldowns(repo, fix),
        _provider_key(repo),
        _sources(repo),
        _model_cache(repo),
        _last_refresh(repo),
        _pipeline_drift(repo),
    ]
    if live and llm is not None:
        findings.append(_live(llm))
    return findings


# Derived tables wiped by rebuild; meta keeps embed_dim (the store must stay
# usable) and llm_health keeps its cooldowns (still true after a rebuild).
_DERIVED_TABLES = ("notes", "note_embeddings", "themes", "links",
                   "theme_label_cache", "theme_status_cache",
                   "distilled_sessions")


def rebuild_derived(repo) -> dict:
    """Discard ALL derived data; raw + judgments + config survive. The next
    refresh rebuilds the map from raw (and re-spends LLM budget doing it)."""
    counts = {}
    for t in _DERIVED_TABLES:
        counts[t] = repo.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        repo.conn.execute(f"DELETE FROM {t}")
    repo.conn.execute("DELETE FROM meta WHERE key='last_refresh'")
    for r in repo.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'note_vec%'").fetchall():
        repo.conn.execute(f"DROP TABLE IF EXISTS [{r[0]}]")
    repo.conn.commit()
    return counts
