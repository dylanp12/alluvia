from __future__ import annotations
import os
import sqlite3


def connect(path: str) -> sqlite3.Connection:
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    # check_same_thread=False: the dashboard serves reads from handler threads.
    # SQLite serializes internally; our writes are short, single-user.
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL: readers never block the writer, so refresh, the dashboard, and MCP
    # servers can run concurrently. Persistent — legacy stores upgrade on
    # first touch. busy_timeout covers the residual writer-writer waits.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_schema(conn: sqlite3.Connection, embed_dim: int) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS raw_sessions (
            id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            source TEXT NOT NULL,
            native_id TEXT NOT NULL,
            title TEXT,
            started_at TEXT,
            ended_at TEXT,
            messages_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            PRIMARY KEY (user_id, id)
        );
        CREATE TABLE IF NOT EXISTS notes (
            id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            span_ref TEXT,
            kind TEXT,
            text TEXT NOT NULL,
            created_at TEXT,
            canonical_id TEXT,
            pipeline_version INTEGER NOT NULL,
            PRIMARY KEY (user_id, id)
        );
        CREATE TABLE IF NOT EXISTS note_embeddings (
            user_id TEXT NOT NULL,
            note_id TEXT NOT NULL,
            dim INTEGER NOT NULL,
            vec BLOB NOT NULL,
            PRIMARY KEY (user_id, note_id)
        );
        CREATE TABLE IF NOT EXISTS themes (
            id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            label TEXT,
            summary TEXT,
            note_ids_json TEXT NOT NULL,
            first_seen TEXT,
            last_seen TEXT,
            session_count INTEGER,
            source_count INTEGER,
            PRIMARY KEY (user_id, id)
        );
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS links (
            id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            from_note_id TEXT NOT NULL,
            to_note_id TEXT NOT NULL,
            from_theme_id TEXT,
            to_theme_id TEXT,
            kind TEXT NOT NULL,
            weight REAL NOT NULL,
            why TEXT,
            PRIMARY KEY (user_id, id)
        );
        CREATE INDEX IF NOT EXISTS idx_links_user_weight ON links(user_id, weight DESC);
        CREATE TABLE IF NOT EXISTS theme_status_cache (
            user_id TEXT NOT NULL,
            status_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (user_id, status_hash)
        );
        CREATE TABLE IF NOT EXISTS theme_label_cache (
            user_id TEXT NOT NULL,
            label_hash TEXT NOT NULL,
            label TEXT NOT NULL,
            summary TEXT NOT NULL,
            PRIMARY KEY (user_id, label_hash)
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            next_step TEXT,
            cites_json TEXT NOT NULL,
            novelty_sim REAL,
            feasibility INTEGER,
            risk TEXT,
            model TEXT,
            outcome TEXT NOT NULL DEFAULT 'pending',
            reject_reason TEXT,
            rated_at TEXT,
            rating_note TEXT,
            PRIMARY KEY (user_id, id)
        );
        CREATE TABLE IF NOT EXISTS digests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            item_count INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS digest_items (
            digest_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            n INTEGER NOT NULL,
            kind TEXT NOT NULL,
            ref TEXT,
            theme_ref TEXT,
            snapshot TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT 'shown',
            acted_at TEXT,
            PRIMARY KEY (digest_id, n)
        );
        CREATE TABLE IF NOT EXISTS muted_themes (
            user_id TEXT NOT NULL,
            label_lc TEXT NOT NULL,
            PRIMARY KEY (user_id, label_lc)
        );
        CREATE TABLE IF NOT EXISTS distilled_sessions (
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            pipeline_version INTEGER NOT NULL,
            PRIMARY KEY (user_id, session_id)
        );
        CREATE TABLE IF NOT EXISTS llm_health (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            cooldown_until REAL NOT NULL DEFAULT 0,
            rung INTEGER NOT NULL DEFAULT 0,
            consecutive INTEGER NOT NULL DEFAULT 0,
            est_rate REAL,
            last_success REAL NOT NULL DEFAULT 0,
            last_call REAL NOT NULL DEFAULT 0,
            calls INTEGER NOT NULL DEFAULT 0,
            sent_bytes INTEGER NOT NULL DEFAULT 0,
            recv_bytes INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (provider, model)
        );
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('embed_dim', ?)",
        (str(embed_dim),),
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(themes)")}
    if "status" not in cols:
        conn.execute("ALTER TABLE themes ADD COLUMN status TEXT")
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(proposals)")}
    if "rated_via" not in pcols:
        conn.execute("ALTER TABLE proposals ADD COLUMN rated_via TEXT")
    hcols = {r[1] for r in conn.execute("PRAGMA table_info(llm_health)")}
    for col in ("calls", "sent_bytes", "recv_bytes"):
        if col not in hcols:
            conn.execute(f"ALTER TABLE llm_health ADD COLUMN {col} "
                         f"INTEGER NOT NULL DEFAULT 0")
    conn.commit()
