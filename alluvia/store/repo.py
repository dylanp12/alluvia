from __future__ import annotations
import json
import sqlite3
from datetime import datetime

import numpy as np

from alluvia.config import PIPELINE_VERSION
from alluvia.models import Link, Message, Note, Proposal, RawSession, Theme
from alluvia.store.vector import make_index


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _dts(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


class Repo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._vec_index = None

    def _index(self):
        if self._vec_index is None:
            dim = int(self.conn.execute(
                "SELECT value FROM meta WHERE key='embed_dim'").fetchone()[0])
            self._vec_index = make_index(self.conn, dim=dim)
        return self._vec_index

    # ---- sessions ----
    def upsert_session(self, s: RawSession) -> bool:
        row = self.conn.execute(
            "SELECT content_hash FROM raw_sessions WHERE user_id=? AND id=?",
            (s.user_id, s.id),
        ).fetchone()
        if row and row[0] == s.content_hash:
            return False
        messages_json = json.dumps(
            [[m.role, m.text, _dts(m.ts)] for m in s.messages], ensure_ascii=False
        )
        self.conn.execute(
            """INSERT INTO raw_sessions
               (id,user_id,source,native_id,title,started_at,ended_at,messages_json,content_hash)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id,id) DO UPDATE SET
                 source=excluded.source, native_id=excluded.native_id, title=excluded.title,
                 started_at=excluded.started_at, ended_at=excluded.ended_at,
                 messages_json=excluded.messages_json, content_hash=excluded.content_hash""",
            (s.id, s.user_id, s.source, s.native_id, s.title, _dts(s.started_at),
             _dts(s.ended_at), messages_json, s.content_hash),
        )
        self.conn.commit()
        return True

    def _row_to_session(self, r) -> RawSession:
        msgs = [Message(role=a, text=b, ts=_dt(c)) for a, b, c in json.loads(r[7])]
        return RawSession(
            id=r[0], user_id=r[1], source=r[2], native_id=r[3], title=r[4],
            started_at=_dt(r[5]), ended_at=_dt(r[6]), messages=msgs, content_hash=r[8],
        )

    def get_session(self, user_id: str, sid: str) -> RawSession | None:
        r = self.conn.execute(
            "SELECT * FROM raw_sessions WHERE user_id=? AND id=?", (user_id, sid)
        ).fetchone()
        return self._row_to_session(r) if r else None

    def list_sessions(self, user_id: str) -> list[RawSession]:
        rows = self.conn.execute(
            "SELECT * FROM raw_sessions WHERE user_id=? ORDER BY id", (user_id,)
        ).fetchall()
        return [self._row_to_session(r) for r in rows]

    # ---- notes ----
    def upsert_notes(self, notes: list[Note]) -> None:
        for n in notes:
            self.conn.execute(
                """INSERT INTO notes
                   (id,user_id,session_id,span_ref,kind,text,created_at,canonical_id,pipeline_version)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,id) DO UPDATE SET
                     session_id=excluded.session_id, span_ref=excluded.span_ref,
                     kind=excluded.kind, text=excluded.text, created_at=excluded.created_at,
                     canonical_id=excluded.canonical_id, pipeline_version=excluded.pipeline_version""",
                (n.id, n.user_id, n.session_id, n.span_ref, n.kind, n.text,
                 _dts(n.created_at), n.canonical_id, PIPELINE_VERSION),
            )
        self.conn.commit()

    def get_notes(self, user_id: str) -> list[Note]:
        rows = self.conn.execute(
            "SELECT id,user_id,session_id,span_ref,kind,text,created_at,canonical_id "
            "FROM notes WHERE user_id=? ORDER BY id", (user_id,)
        ).fetchall()
        return [Note(id=r[0], user_id=r[1], session_id=r[2], span_ref=r[3], kind=r[4],
                     text=r[5], created_at=_dt(r[6]), canonical_id=r[7]) for r in rows]

    def session_ids_with_notes(self, user_id: str,
                               version: int | None = None) -> set[str]:
        if version is None:
            return {r[0] for r in self.conn.execute(
                "SELECT DISTINCT session_id FROM notes WHERE user_id=?", (user_id,))}
        return {r[0] for r in self.conn.execute(
            "SELECT DISTINCT session_id FROM notes "
            "WHERE user_id=? AND pipeline_version >= ?", (user_id, version))}

    # ---- distill checkpoint (covers zero-note sessions, unlike notes-derived) ----
    def mark_distilled(self, user_id: str, session_id: str) -> None:
        self.conn.execute(
            "INSERT INTO distilled_sessions(user_id,session_id,pipeline_version) "
            "VALUES (?,?,?) ON CONFLICT(user_id,session_id) DO UPDATE SET "
            "pipeline_version=excluded.pipeline_version",
            (user_id, session_id, PIPELINE_VERSION))
        self.conn.commit()

    def distilled_session_ids(self, user_id: str,
                              version: int = PIPELINE_VERSION) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT session_id FROM distilled_sessions "
            "WHERE user_id=? AND pipeline_version >= ?", (user_id, version))}

    # ---- embeddings (brute-force numpy; sqlite-vec is a later optimization) ----
    def set_embedding(self, user_id: str, note_id: str, vec: list[float]) -> None:
        arr = np.asarray(vec, dtype="float32")
        self.conn.execute(
            "INSERT INTO note_embeddings(user_id,note_id,dim,vec) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id,note_id) DO UPDATE SET dim=excluded.dim, vec=excluded.vec",
            (user_id, note_id, arr.shape[0], arr.tobytes()),
        )
        self.conn.commit()
        self._index().upsert(user_id, note_id, [float(x) for x in arr])

    def note_ids_with_embeddings(self, user_id: str) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT note_id FROM note_embeddings WHERE user_id=?", (user_id,))}

    def all_embeddings(self, user_id: str) -> tuple[list[str], "np.ndarray"]:
        rows = self.conn.execute(
            "SELECT note_id,vec FROM note_embeddings WHERE user_id=? ORDER BY note_id",
            (user_id,)).fetchall()
        ids = [r[0] for r in rows]
        mat = (np.stack([np.frombuffer(r[1], dtype="float32") for r in rows])
               if rows else np.zeros((0, 0), dtype="float32"))
        return ids, mat

    def search_notes(self, user_id: str, vec: list[float], k: int) -> list[tuple[str, float]]:
        return self._index().search(user_id, vec, k)

    # ---- themes (full-rebuild each refresh) ----
    def replace_themes(self, user_id: str, themes: list[Theme]) -> None:
        self.conn.execute("DELETE FROM themes WHERE user_id=?", (user_id,))
        for t in themes:
            self.conn.execute(
                """INSERT INTO themes
                   (id,user_id,label,summary,note_ids_json,first_seen,last_seen,
                    session_count,source_count,status)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (t.id, t.user_id, t.label, t.summary, json.dumps(t.note_ids),
                 _dts(t.first_seen), _dts(t.last_seen), t.session_count, t.source_count, t.status),
            )
        self.conn.commit()

    def list_themes(self, user_id: str) -> list[Theme]:
        rows = self.conn.execute(
            "SELECT id,user_id,label,summary,note_ids_json,first_seen,last_seen,"
            "session_count,source_count,status FROM themes WHERE user_id=? "
            "ORDER BY session_count DESC", (user_id,)).fetchall()
        return [Theme(id=r[0], user_id=r[1], label=r[2], summary=r[3],
                      note_ids=json.loads(r[4]), first_seen=_dt(r[5]), last_seen=_dt(r[6]),
                      session_count=r[7], source_count=r[8],
                      status=(r[9] or "unknown")) for r in rows]

    def get_theme(self, user_id: str, theme_id: str) -> Theme | None:
        for t in self.list_themes(user_id):
            if t.id == theme_id:
                return t
        return None

    # ---- links ----
    def replace_links(self, user_id: str, links: list[Link]) -> None:
        self.conn.execute("DELETE FROM links WHERE user_id=?", (user_id,))
        for l in links:
            self.conn.execute(
                """INSERT INTO links
                   (id,user_id,from_note_id,to_note_id,from_theme_id,to_theme_id,kind,weight,why)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (l.id, l.user_id, l.from_note_id, l.to_note_id, l.from_theme_id,
                 l.to_theme_id, l.kind, l.weight, l.why),
            )
        self.conn.commit()

    def list_links(self, user_id: str, limit: int | None = None) -> list[Link]:
        sql = ("SELECT id,user_id,from_note_id,to_note_id,from_theme_id,to_theme_id,"
               "kind,weight,why FROM links WHERE user_id=? ORDER BY weight DESC")
        params: tuple = (user_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (user_id, limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [Link(id=r[0], user_id=r[1], from_note_id=r[2], to_note_id=r[3],
                     from_theme_id=r[4], to_theme_id=r[5], kind=r[6], weight=r[7], why=r[8])
                for r in rows]

    def set_link_why(self, user_id: str, link_id: str, why: str) -> None:
        self.conn.execute("UPDATE links SET why=? WHERE user_id=? AND id=?",
                          (why, user_id, link_id))
        self.conn.commit()

    # ---- theme label cache (content-hash keyed, like status: labels are LLM
    # calls and must not be re-billed on every refresh) ----
    def get_label_cache(self, user_id: str, label_hash: str) -> tuple[str, str] | None:
        r = self.conn.execute(
            "SELECT label, summary FROM theme_label_cache WHERE user_id=? AND label_hash=?",
            (user_id, label_hash)).fetchone()
        return (r[0], r[1]) if r else None

    def set_label_cache(self, user_id: str, label_hash: str, label: str, summary: str) -> None:
        self.conn.execute(
            "INSERT INTO theme_label_cache(user_id,label_hash,label,summary) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id,label_hash) DO UPDATE SET label=excluded.label, "
            "summary=excluded.summary",
            (user_id, label_hash, label, summary))
        self.conn.commit()

    # ---- theme status cache (keyed by content hash, survives theme-id churn) ----
    def get_status_cache(self, user_id: str, status_hash: str) -> str | None:
        r = self.conn.execute(
            "SELECT status FROM theme_status_cache WHERE user_id=? AND status_hash=?",
            (user_id, status_hash)).fetchone()
        return r[0] if r else None

    def set_status_cache(self, user_id: str, status_hash: str, status: str) -> None:
        self.conn.execute(
            "INSERT INTO theme_status_cache(user_id,status_hash,status) VALUES (?,?,?) "
            "ON CONFLICT(user_id,status_hash) DO UPDATE SET status=excluded.status",
            (user_id, status_hash, status))
        self.conn.commit()

    # ---- proposals (JUDGMENTS: durable; refresh never touches this table) ----
    def insert_proposal(self, p: Proposal) -> None:
        self.conn.execute(
            """INSERT INTO proposals
               (id,user_id,created_at,kind,source_ref,source_hash,title,text,next_step,
                cites_json,novelty_sim,feasibility,risk,model,outcome,reject_reason,
                rated_at,rating_note,rated_via)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id,id) DO NOTHING""",
            (p.id, p.user_id, p.created_at, p.kind, p.source_ref, p.source_hash,
             p.title, p.text, p.next_step, json.dumps(p.cites), p.novelty_sim,
             p.feasibility, p.risk, p.model, p.outcome, p.reject_reason,
             p.rated_at, p.rating_note, p.rated_via))
        self.conn.commit()

    def _row_to_proposal(self, r) -> Proposal:
        return Proposal(id=r[0], user_id=r[1], created_at=r[2], kind=r[3],
                        source_ref=r[4], source_hash=r[5], title=r[6], text=r[7],
                        next_step=r[8], cites=json.loads(r[9]), novelty_sim=r[10],
                        feasibility=r[11], risk=r[12], model=r[13], outcome=r[14],
                        reject_reason=r[15], rated_at=r[16], rating_note=r[17],
                        rated_via=r[18])

    def list_proposals(self, user_id: str,
                       outcomes: tuple[str, ...] = ("pending",)) -> list[Proposal]:
        q = ",".join("?" * len(outcomes))
        rows = self.conn.execute(
            f"SELECT id,user_id,created_at,kind,source_ref,source_hash,title,text,"
            f"next_step,cites_json,novelty_sim,feasibility,risk,model,outcome,"
            f"reject_reason,rated_at,rating_note,rated_via FROM proposals "
            f"WHERE user_id=? AND outcome IN ({q}) ORDER BY created_at",
            (user_id, *outcomes)).fetchall()
        return [self._row_to_proposal(r) for r in rows]

    def get_proposal(self, user_id: str, pid: str) -> Proposal | None:
        for p in self.list_proposals(user_id, outcomes=("pending", "kept",
                                                        "dismissed", "rejected")):
            if p.id == pid:
                return p
        return None

    def rate_proposal(self, user_id: str, pid: str, outcome: str,
                      note: str | None = None, via: str = "cli") -> None:
        from datetime import datetime, timezone
        self.conn.execute(
            "UPDATE proposals SET outcome=?, rating_note=?, rated_at=?, rated_via=? "
            "WHERE user_id=? AND id=?",
            (outcome, note, datetime.now(timezone.utc).isoformat(), via, user_id, pid))
        self.conn.commit()

    def proposal_source_hashes(self, user_id: str) -> set[str]:
        """Material already proposed-from. Auto-rejected attempts do NOT count —
        a transient generator/guardrail failure must not burn material forever."""
        return {r[0] for r in self.conn.execute(
            "SELECT DISTINCT source_hash FROM proposals "
            "WHERE user_id=? AND outcome != 'rejected'", (user_id,))}

    # ---- mute (label-keyed: survives theme-id churn across rebuilds) ----
    def mute_label(self, user_id: str, label: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO muted_themes(user_id,label_lc) VALUES (?,?)",
            (user_id, label.strip().lower()))
        self.conn.commit()

    def unmute_label(self, user_id: str, label: str) -> None:
        self.conn.execute("DELETE FROM muted_themes WHERE user_id=? AND label_lc=?",
                          (user_id, label.strip().lower()))
        self.conn.commit()

    def muted_labels(self, user_id: str) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT label_lc FROM muted_themes WHERE user_id=?", (user_id,))}

    # ---- digests (JUDGMENTS-class: durable, snapshot text) ----
    def insert_digest(self, user_id: str, created_at: str, items: list[dict]) -> int:
        cur = self.conn.execute(
            "INSERT INTO digests(user_id,created_at,item_count) VALUES (?,?,?)",
            (user_id, created_at, len(items)))
        did = cur.lastrowid
        for i, it in enumerate(items, 1):
            self.conn.execute(
                "INSERT INTO digest_items(digest_id,user_id,n,kind,ref,theme_ref,snapshot)"
                " VALUES (?,?,?,?,?,?,?)",
                (did, user_id, i, it["kind"], it.get("ref"), it.get("theme_ref"),
                 it["snapshot"]))
        self.conn.commit()
        return did

    def latest_digest(self, user_id: str):
        return self.conn.execute(
            "SELECT id, created_at, item_count FROM digests WHERE user_id=? "
            "ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()

    def digest_items(self, user_id: str, digest_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT n,kind,ref,theme_ref,snapshot,outcome FROM digest_items "
            "WHERE user_id=? AND digest_id=? ORDER BY n", (user_id, digest_id))
        return [{"n": r[0], "kind": r[1], "ref": r[2], "theme_ref": r[3],
                 "snapshot": r[4], "outcome": r[5]} for r in rows]

    def shown_refs(self, user_id: str, kinds: tuple[str, ...],
                   last_n_digests: int | None = None) -> set[str]:
        sql = ("SELECT di.ref FROM digest_items di WHERE di.user_id=? "
               f"AND di.kind IN ({','.join('?' * len(kinds))}) AND di.ref IS NOT NULL")
        params: list = [user_id, *kinds]
        if last_n_digests is not None:
            sql += (" AND di.digest_id IN (SELECT id FROM digests WHERE user_id=? "
                    "ORDER BY id DESC LIMIT ?)")
            params += [user_id, last_n_digests]
        return {r[0] for r in self.conn.execute(sql, params)}

    def dismissed_theme_counts(self, user_id: str) -> dict[str, int]:
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT theme_ref, COUNT(*) FROM digest_items "
            "WHERE user_id=? AND outcome='dismissed' AND theme_ref IS NOT NULL "
            "GROUP BY theme_ref", (user_id,))}

    def set_digest_item_outcome(self, user_id: str, digest_id: int, n: int,
                                outcome: str) -> dict | None:
        from datetime import datetime, timezone
        item = next((i for i in self.digest_items(user_id, digest_id)
                     if i["n"] == n), None)
        if item is None:
            return None
        self.conn.execute(
            "UPDATE digest_items SET outcome=?, acted_at=? "
            "WHERE user_id=? AND digest_id=? AND n=?",
            (outcome, datetime.now(timezone.utc).isoformat(), user_id, digest_id, n))
        self.conn.commit()
        return item
