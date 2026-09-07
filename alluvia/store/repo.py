from __future__ import annotations
import json
import sqlite3
from datetime import datetime

import numpy as np

from alluvia.config import PIPELINE_VERSION
from alluvia.models import ExtractionRun, Link, Message, Note, Proposal, RawSession, Theme
from alluvia.store.vector import make_index


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


def _dts(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


from alluvia.lexical import lex_query as _lex_query


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
    _SESSION_COLS = ("id,user_id,source,native_id,title,started_at,ended_at,"
                     "messages_json,content_hash,project,branch")

    def upsert_session(self, s: RawSession, imported_from: str | None = None) -> bool:
        """`imported_from`: the session arrived in a memory bundle from another
        machine — metadata only, no messages; its notes are real, its receipts
        live on the origin."""
        row = self.conn.execute(
            "SELECT content_hash, project, branch FROM raw_sessions "
            "WHERE user_id=? AND id=?", (s.user_id, s.id)).fetchone()
        if row and row[0] == s.content_hash and (row[1], row[2]) == (s.project, s.branch):
            return False
        if row and row[0] != s.content_hash:
            # derived is rebuildable from raw: notes distilled from the OLD
            # content are invalid the moment the raw changes — drop them (and
            # their vectors and marker) so the next pass distills fresh and
            # "no record" beats a stale one
            self._drop_session_derived(s.user_id, s.id)
        messages_json = json.dumps(
            [[m.role, m.text, _dts(m.ts)] for m in s.messages], ensure_ascii=False
        )
        self.conn.execute(
            """INSERT INTO raw_sessions
               (id,user_id,source,native_id,title,started_at,ended_at,messages_json,
                content_hash,project,branch,imported_from)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id,id) DO UPDATE SET
                 source=excluded.source, native_id=excluded.native_id, title=excluded.title,
                 started_at=excluded.started_at, ended_at=excluded.ended_at,
                 messages_json=excluded.messages_json, content_hash=excluded.content_hash,
                 project=excluded.project, branch=excluded.branch,
                 imported_from=excluded.imported_from""",
            (s.id, s.user_id, s.source, s.native_id, s.title, _dts(s.started_at),
             _dts(s.ended_at), messages_json, s.content_hash, s.project, s.branch,
             imported_from),
        )
        self.conn.commit()
        return True

    def session_origins(self, user_id: str) -> dict[str, str]:
        """Sessions that arrived by import, with where they came from."""
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT id, imported_from FROM raw_sessions "
            "WHERE user_id=? AND imported_from IS NOT NULL", (user_id,))}

    def session_content_hash(self, user_id: str, sid: str) -> str | None:
        r = self.conn.execute("SELECT content_hash FROM raw_sessions WHERE user_id=? AND id=?",
                              (user_id, sid)).fetchone()
        return r[0] if r else None

    # ---- proof of use (JUDGMENTS: what the memory did, never regenerated) ----
    def record_handoff_event(self, user_id: str, project: str, note_ids: list[str],
                             chars: int, source: str | None) -> str:
        import hashlib
        from datetime import datetime, timezone
        at = datetime.now(timezone.utc).isoformat()
        eid = "hev:" + hashlib.sha1(f"{project}|{at}".encode("utf-8")).hexdigest()[:12]
        self.conn.execute(
            "INSERT INTO handoff_events(id,user_id,project,created_at,note_ids_json,chars,source,"
            "referenced_json) VALUES (?,?,?,?,?,?,?,NULL)",
            (eid, user_id, project, at, json.dumps(note_ids), chars, source))
        self.conn.commit()
        return eid

    def _event_row(self, r) -> dict:
        return {"id": r[0], "project": r[1], "created_at": r[2], "note_ids": json.loads(r[3]),
                "chars": r[4], "source": r[5],
                "referenced_note_ids": json.loads(r[6]) if r[6] else []}

    _EVENT_COLS = "id,project,created_at,note_ids_json,chars,source,referenced_json"

    def latest_handoff_event(self, user_id: str, project: str) -> dict | None:
        r = self.conn.execute(
            f"SELECT {self._EVENT_COLS} FROM handoff_events WHERE user_id=? AND project=? "
            "ORDER BY created_at DESC, id DESC LIMIT 1", (user_id, project)).fetchone()
        return self._event_row(r) if r else None

    def list_handoff_events(self, user_id: str) -> list[dict]:
        return [self._event_row(r) for r in self.conn.execute(
            f"SELECT {self._EVENT_COLS} FROM handoff_events WHERE user_id=? ORDER BY created_at",
            (user_id,))]

    def set_event_references(self, user_id: str, event_id: str, note_ids: list[str]) -> None:
        self.conn.execute("UPDATE handoff_events SET referenced_json=? WHERE user_id=? AND id=?",
                          (json.dumps(note_ids), user_id, event_id))
        self.conn.commit()

    def record_verdict(self, user_id: str, event_id: str, verdict: str,
                       note_id: str | None = None) -> None:
        from datetime import datetime, timezone
        self.conn.execute(
            "INSERT INTO handoff_verdicts(user_id,event_id,verdict,note_id,created_at) "
            "VALUES (?,?,?,?,?)",
            (user_id, event_id, verdict, note_id, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def list_verdicts(self, user_id: str) -> list[dict]:
        return [{"event_id": r[0], "verdict": r[1], "note_id": r[2], "created_at": r[3]}
                for r in self.conn.execute(
                    "SELECT event_id, verdict, note_id, created_at FROM handoff_verdicts "
                    "WHERE user_id=? ORDER BY id", (user_id,))]

    def bump_counter(self, user_id: str, key: str, by: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO usage_counters(user_id,key,count) VALUES (?,?,?) "
            "ON CONFLICT(user_id,key) DO UPDATE SET count=count+excluded.count",
            (user_id, key, by))
        self.conn.commit()

    def counters(self, user_id: str) -> dict[str, int]:
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT key, count FROM usage_counters WHERE user_id=? ORDER BY key", (user_id,))}

    def _drop_session_derived(self, user_id: str, session_id: str) -> None:
        ids = [r[0] for r in self.conn.execute(
            "SELECT id FROM notes WHERE user_id=? AND session_id=?", (user_id, session_id))]
        for nid in ids:
            self.conn.execute("DELETE FROM notes_fts WHERE user_id=? AND note_id=?",
                              (user_id, nid))
            self.conn.execute("DELETE FROM note_embeddings WHERE user_id=? AND note_id=?",
                              (user_id, nid))
            self._index().delete(user_id, nid)
        self.conn.execute("DELETE FROM notes WHERE user_id=? AND session_id=?",
                          (user_id, session_id))
        self.conn.execute("DELETE FROM distilled_sessions WHERE user_id=? AND session_id=?",
                          (user_id, session_id))

    def _row_to_session(self, r) -> RawSession:
        msgs = [Message(role=a, text=b, ts=_dt(c)) for a, b, c in json.loads(r[7])]
        return RawSession(
            id=r[0], user_id=r[1], source=r[2], native_id=r[3], title=r[4],
            started_at=_dt(r[5]), ended_at=_dt(r[6]), messages=msgs, content_hash=r[8],
            project=r[9], branch=r[10],
        )

    def get_session(self, user_id: str, sid: str) -> RawSession | None:
        r = self.conn.execute(
            f"SELECT {self._SESSION_COLS} FROM raw_sessions WHERE user_id=? AND id=?",
            (user_id, sid)).fetchone()
        return self._row_to_session(r) if r else None

    def list_sessions(self, user_id: str) -> list[RawSession]:
        rows = self.conn.execute(
            f"SELECT {self._SESSION_COLS} FROM raw_sessions WHERE user_id=? ORDER BY id",
            (user_id,)).fetchall()
        return [self._row_to_session(r) for r in rows]

    def list_session_meta(self, user_id: str, project: str | None = None) -> list[dict]:
        """Session headers without message bodies — cheap enough to call from a
        hook. Optionally filtered to one project root."""
        sql = ("SELECT id,source,native_id,title,started_at,ended_at,project,branch "
               "FROM raw_sessions WHERE user_id=?")
        params: tuple = (user_id,)
        if project is not None:
            sql += " AND project=?"
            params = (user_id, project)
        rows = self.conn.execute(sql + " ORDER BY started_at, id", params).fetchall()
        return [{"id": r[0], "source": r[1], "native_id": r[2], "title": r[3],
                 "started_at": _dt(r[4]), "ended_at": _dt(r[5]),
                 "project": r[6], "branch": r[7]} for r in rows]

    def session_projects(self, user_id: str) -> dict[str, str | None]:
        return {r[0]: r[1] for r in self.conn.execute(
            "SELECT id, project FROM raw_sessions WHERE user_id=?", (user_id,))}

    # ---- notes ----
    def upsert_notes(self, notes: list[Note]) -> None:
        for n in notes:
            self.conn.execute(
                """INSERT INTO notes
                   (id,user_id,session_id,span_ref,kind,text,created_at,canonical_id,
                    pipeline_version,run_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,id) DO UPDATE SET
                     session_id=excluded.session_id, span_ref=excluded.span_ref,
                     kind=excluded.kind, text=excluded.text, created_at=excluded.created_at,
                     canonical_id=excluded.canonical_id,
                     pipeline_version=excluded.pipeline_version,
                     run_id=excluded.run_id""",
                (n.id, n.user_id, n.session_id, n.span_ref, n.kind, n.text,
                 _dts(n.created_at), n.canonical_id, PIPELINE_VERSION, n.run_id),
            )
            self.conn.execute(
                "DELETE FROM notes_fts WHERE user_id=? AND note_id=?",
                (n.user_id, n.id))
            self.conn.execute(
                "INSERT INTO notes_fts(note_id, user_id, text) VALUES (?,?,?)",
                (n.id, n.user_id, n.text))
        self.conn.commit()

    def replace_session_notes(self, user_id: str, session_id: str,
                              notes: list[Note]) -> int:
        """A FULL distill of a session defines its note set: notes from an
        earlier pass that the new pass did not produce are stale (the raw
        rendering or the pipeline changed) and are removed with their vectors
        and FTS rows. Returns how many were dropped. Partial passes must use
        upsert_notes (union) instead."""
        self.upsert_notes(notes)
        keep = {n.id for n in notes}
        stale = [r[0] for r in self.conn.execute(
            "SELECT id FROM notes WHERE user_id=? AND session_id=?", (user_id, session_id))
            if r[0] not in keep]
        for nid in stale:
            self.conn.execute("DELETE FROM notes WHERE user_id=? AND id=?", (user_id, nid))
            self.conn.execute("DELETE FROM notes_fts WHERE user_id=? AND note_id=?",
                              (user_id, nid))
            self.conn.execute("DELETE FROM note_embeddings WHERE user_id=? AND note_id=?",
                              (user_id, nid))
            self._index().delete(user_id, nid)
        self.conn.commit()
        return len(stale)

    def get_notes(self, user_id: str) -> list[Note]:
        rows = self.conn.execute(
            "SELECT id,user_id,session_id,span_ref,kind,text,created_at,canonical_id,"
            "run_id,pipeline_version FROM notes WHERE user_id=? ORDER BY id",
            (user_id,)
        ).fetchall()
        return [Note(id=r[0], user_id=r[1], session_id=r[2], span_ref=r[3], kind=r[4],
                     text=r[5], created_at=_dt(r[6]), canonical_id=r[7],
                     run_id=r[8], pipeline_version=r[9]) for r in rows]

    def session_ids_with_notes(self, user_id: str,
                               version: int | None = None) -> set[str]:
        if version is None:
            return {r[0] for r in self.conn.execute(
                "SELECT DISTINCT session_id FROM notes WHERE user_id=?", (user_id,))}
        return {r[0] for r in self.conn.execute(
            "SELECT DISTINCT session_id FROM notes "
            "WHERE user_id=? AND pipeline_version >= ?", (user_id, version))}

    # ---- distill checkpoint (covers zero-note sessions, unlike notes-derived) ----
    def mark_distilled(self, user_id: str, session_id: str,
                       partial: bool = False) -> None:
        """`partial`: the provider cut a multi-window distill short — the
        notes written are real but incomplete, so the session is NOT done."""
        self.conn.execute(
            "INSERT INTO distilled_sessions(user_id,session_id,pipeline_version,partial) "
            "VALUES (?,?,?,?) ON CONFLICT(user_id,session_id) DO UPDATE SET "
            "pipeline_version=excluded.pipeline_version, partial=excluded.partial",
            (user_id, session_id, PIPELINE_VERSION, 1 if partial else 0))
        self.conn.commit()

    def distilled_session_ids(self, user_id: str,
                              version: int = PIPELINE_VERSION) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT session_id FROM distilled_sessions "
            "WHERE user_id=? AND pipeline_version >= ? AND partial=0", (user_id, version))}

    def partial_session_ids(self, user_id: str) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT session_id FROM distilled_sessions WHERE user_id=? AND partial=1",
            (user_id,))}

    def done_session_ids(self, user_id: str) -> set[str]:
        """Sessions recall can consider fully distilled at the current pipeline
        version. Union: the marker table is authoritative; the notes-derived
        set backfills sessions distilled before the marker existed — minus
        sessions explicitly known to be partial."""
        return (self.distilled_session_ids(user_id)
                | (self.session_ids_with_notes(user_id, version=PIPELINE_VERSION)
                   - self.partial_session_ids(user_id)))

    def distill_coverage(self, user_id: str) -> dict:
        """How much of the raw history recall can actually see."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM raw_sessions WHERE user_id=?", (user_id,)).fetchone()[0]
        done = len(self.done_session_ids(user_id))
        return {"sessions": total, "distilled": min(done, total),
                "pending": max(total - done, 0)}

    # ---- extraction runs (provenance: which model/prompt produced what) ----
    def record_extraction_run(self, run: ExtractionRun) -> None:
        self.conn.execute(
            """INSERT INTO extraction_runs
               (id,user_id,session_id,stage,model,pipeline_version,prompt_hash,created_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(user_id,id) DO NOTHING""",
            (run.id, run.user_id, run.session_id, run.stage, run.model,
             run.pipeline_version, run.prompt_hash, run.created_at))
        self.conn.commit()

    def list_extraction_runs(self, user_id: str) -> list[ExtractionRun]:
        rows = self.conn.execute(
            "SELECT id,user_id,session_id,stage,model,pipeline_version,prompt_hash,"
            "created_at FROM extraction_runs WHERE user_id=? ORDER BY created_at, id",
            (user_id,)).fetchall()
        return [ExtractionRun(id=r[0], user_id=r[1], session_id=r[2], stage=r[3],
                              model=r[4], pipeline_version=r[5], prompt_hash=r[6],
                              created_at=r[7]) for r in rows]

    # ---- graph rows (events/edges/candidates/slates): dict-shaped, thin.
    # Producers arrive with extraction v2 and the lens/flywheel milestones. ----
    def insert_events(self, user_id: str, rows: list[dict]) -> None:
        for e in rows:
            self.conn.execute(
                """INSERT INTO events
                   (id,user_id,event_type,relation,participants_json,
                    event_time_start,event_time_end,derived_at,run_id,confidence,
                    human_confirmed,evidence_json,derivation_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,id) DO NOTHING""",
                (e["id"], user_id, e["event_type"], e.get("relation"),
                 json.dumps(e.get("participants", [])),
                 e.get("event_time_start"), e.get("event_time_end"),
                 e.get("derived_at"), e.get("run_id"), e.get("confidence"),
                 1 if e.get("human_confirmed") else 0,
                 json.dumps(e.get("evidence", [])),
                 json.dumps(e.get("derivation", []))))
        self.conn.commit()

    def list_events(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id,event_type,relation,participants_json,event_time_start,"
            "event_time_end,derived_at,run_id,confidence,human_confirmed,"
            "evidence_json,derivation_json FROM events WHERE user_id=? ORDER BY id",
            (user_id,)).fetchall()
        return [{"id": r[0], "event_type": r[1], "relation": r[2],
                 "participants": json.loads(r[3]), "event_time_start": r[4],
                 "event_time_end": r[5], "derived_at": r[6], "run_id": r[7],
                 "confidence": r[8], "human_confirmed": bool(r[9]),
                 "evidence": json.loads(r[10]), "derivation": json.loads(r[11])}
                for r in rows]

    def upsert_edges(self, user_id: str, rows: list[dict]) -> None:
        for e in rows:
            self.conn.execute(
                """INSERT INTO edges (id,user_id,subject_id,relation,object_id,
                                       event_id,weight)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,id) DO UPDATE SET
                     subject_id=excluded.subject_id, relation=excluded.relation,
                     object_id=excluded.object_id, event_id=excluded.event_id,
                     weight=excluded.weight""",
                (e["id"], user_id, e["subject_id"], e["relation"], e["object_id"],
                 e.get("event_id"), e.get("weight")))
        self.conn.commit()

    def list_edges(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id,subject_id,relation,object_id,event_id,weight "
            "FROM edges WHERE user_id=? ORDER BY id", (user_id,)).fetchall()
        return [{"id": r[0], "subject_id": r[1], "relation": r[2],
                 "object_id": r[3], "event_id": r[4], "weight": r[5]} for r in rows]

    def insert_candidates(self, user_id: str, rows: list[dict]) -> None:
        for c in rows:
            self.conn.execute(
                """INSERT INTO candidates
                   (id,user_id,relation,subject_id,object_id,score,
                    uncertainty_json,evidence_json,status,created_at,
                    policy_version,why)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(user_id,id) DO NOTHING""",
                (c["id"], user_id, c["relation"], c["subject_id"], c["object_id"],
                 c.get("score"),
                 json.dumps(c["uncertainty"]) if c.get("uncertainty") is not None
                 else None,
                 json.dumps(c.get("evidence", [])),
                 c.get("status", "pending"), c["created_at"],
                 c.get("policy_version"), c.get("why")))
        self.conn.commit()

    def list_candidates(self, user_id: str, status: str | None = None) -> list[dict]:
        sql = ("SELECT id,relation,subject_id,object_id,score,uncertainty_json,"
               "evidence_json,status,created_at,policy_version,why "
               "FROM candidates WHERE user_id=?")
        params: tuple = (user_id,)
        if status is not None:
            sql += " AND status=?"
            params = (user_id, status)
        rows = self.conn.execute(sql + " ORDER BY id", params).fetchall()
        return [{"id": r[0], "relation": r[1], "subject_id": r[2], "object_id": r[3],
                 "score": r[4],
                 "uncertainty": json.loads(r[5]) if r[5] else None,
                 "evidence": json.loads(r[6]), "status": r[7], "created_at": r[8],
                 "policy_version": r[9], "why": r[10]} for r in rows]

    def set_candidate_status(self, user_id: str, cid: str, status: str) -> None:
        self.conn.execute(
            "UPDATE candidates SET status=? WHERE user_id=? AND id=?",
            (status, user_id, cid))
        self.conn.commit()

    def insert_slate(self, user_id: str, surface: str, policy_version: str,
                     created_at: str, items: list[dict]) -> int:
        cur = self.conn.execute(
            "INSERT INTO slates(user_id,surface,policy_version,created_at,items_json)"
            " VALUES (?,?,?,?,?)",
            (user_id, surface, policy_version, created_at, json.dumps(items)))
        self.conn.commit()
        return cur.lastrowid

    def list_slates(self, user_id: str, surface: str | None = None) -> list[dict]:
        sql = ("SELECT id,surface,policy_version,created_at,items_json FROM slates "
               "WHERE user_id=?")
        params: tuple = (user_id,)
        if surface is not None:
            sql += " AND surface=?"
            params = (user_id, surface)
        rows = self.conn.execute(sql + " ORDER BY id", params).fetchall()
        return [{"id": r[0], "surface": r[1], "policy_version": r[2],
                 "created_at": r[3], "items": json.loads(r[4])} for r in rows]

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

    def search_notes_lexical(self, user_id: str, query: str,
                             k: int = 25) -> list[tuple[str, float]]:
        """Exact-match channel of hybrid recall: BM25 over notes_fts.

        Query text is reduced to quoted literal tokens (never parsed as FTS5
        syntax), OR-matched, then thresholded: a note must contain every
        token of a 1–2-token query, or at least half of a longer one —
        one shared word is not an answer."""
        q = _lex_query(query)
        if not q.tokens:
            return []
        self._sync_fts(user_id)
        match = " OR ".join(f'"{t}"' for t in q.tokens)
        rows = self.conn.execute(
            "SELECT note_id, text, bm25(notes_fts) AS r FROM notes_fts "
            "WHERE notes_fts MATCH ? AND user_id=? ORDER BY r LIMIT ?",
            (match, user_id, k * 3)).fetchall()
        # bm25: smaller is better; a path query must name THE file, a plain
        # query must share enough terms — one shared word is not an answer
        out = [(nid, -float(r)) for nid, text, r in rows if q.matches(text)]
        return out[:k]

    def note_excerpt(self, user_id: str, note: Note) -> str | None:
        """The receipt seam: recall reaches verbatim quotes through the
        store, so team stores can answer from synced excerpts instead."""
        from alluvia.excerpts import note_excerpt
        return note_excerpt(self, user_id, note)

    def _sync_fts(self, user_id: str) -> None:
        """Rebuild this user's FTS rows when they disagree with notes —
        covers stores created before notes_fts existed."""
        n = self.conn.execute(
            "SELECT COUNT(*) FROM notes WHERE user_id=?", (user_id,)).fetchone()[0]
        f = self.conn.execute(
            "SELECT COUNT(*) FROM notes_fts WHERE user_id=?", (user_id,)).fetchone()[0]
        if f != n:
            self.conn.execute("DELETE FROM notes_fts WHERE user_id=?", (user_id,))
            self.conn.execute(
                "INSERT INTO notes_fts(note_id, user_id, text) "
                "SELECT id, user_id, text FROM notes WHERE user_id=?", (user_id,))
            self.conn.commit()

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

    # ---- suppression (JUDGMENTS: a note the user says is wrong or stale never
    # surfaces again — in recall, handoffs, or MCP. Raw and derived untouched.) ----
    def suppress_note(self, user_id: str, note_id: str, reason: str | None = None) -> None:
        from datetime import datetime, timezone
        self.conn.execute(
            "INSERT INTO suppressed_notes(user_id,note_id,reason,created_at) VALUES (?,?,?,?) "
            "ON CONFLICT(user_id,note_id) DO UPDATE SET reason=excluded.reason",
            (user_id, note_id, reason, datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def unsuppress_note(self, user_id: str, note_id: str) -> None:
        self.conn.execute("DELETE FROM suppressed_notes WHERE user_id=? AND note_id=?",
                          (user_id, note_id))
        self.conn.commit()

    def suppressed_note_ids(self, user_id: str) -> set[str]:
        return {r[0] for r in self.conn.execute(
            "SELECT note_id FROM suppressed_notes WHERE user_id=?", (user_id,))}

    def list_suppressed(self, user_id: str) -> list[dict]:
        return [{"note_id": r[0], "reason": r[1], "created_at": r[2]} for r in self.conn.execute(
            "SELECT note_id, reason, created_at FROM suppressed_notes WHERE user_id=? "
            "ORDER BY created_at", (user_id,))]

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

    def digest_count(self, user_id: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) FROM digests WHERE user_id=?",
            (user_id,)).fetchone()[0]

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

    # --- meta & llm health -------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    _HEALTH_COLS = ("cooldown_until", "rung", "consecutive", "est_rate",
                    "last_success", "last_call", "calls", "sent_bytes",
                    "recv_bytes")

    def llm_health_load(self, provider: str, model: str) -> dict | None:
        r = self.conn.execute(
            "SELECT cooldown_until, rung, consecutive, est_rate, last_success, "
            "last_call, calls, sent_bytes, recv_bytes "
            "FROM llm_health WHERE provider=? AND model=?",
            (provider, model)).fetchone()
        return dict(zip(self._HEALTH_COLS, r)) if r else None

    def llm_health_save(self, provider: str, model: str, state: dict) -> None:
        vals = [state.get(c) for c in self._HEALTH_COLS]
        self.conn.execute(
            "INSERT INTO llm_health(provider, model, cooldown_until, rung, "
            "consecutive, est_rate, last_success, last_call, calls, "
            "sent_bytes, recv_bytes) "
            "VALUES (?,?,COALESCE(?,0),COALESCE(?,0),COALESCE(?,0),?,"
            "COALESCE(?,0),COALESCE(?,0),COALESCE(?,0),COALESCE(?,0),"
            "COALESCE(?,0)) "
            "ON CONFLICT(provider, model) DO UPDATE SET "
            "cooldown_until=COALESCE(excluded.cooldown_until,0), "
            "rung=COALESCE(excluded.rung,0), "
            "consecutive=COALESCE(excluded.consecutive,0), "
            "est_rate=excluded.est_rate, "
            "last_success=COALESCE(excluded.last_success,0), "
            "last_call=COALESCE(excluded.last_call,0), "
            "calls=COALESCE(excluded.calls,0), "
            "sent_bytes=COALESCE(excluded.sent_bytes,0), "
            "recv_bytes=COALESCE(excluded.recv_bytes,0)",
            (provider, model, *vals))
        self.conn.commit()

    def llm_health_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT provider, model, cooldown_until, rung, consecutive, "
            "est_rate, last_success, last_call, calls, sent_bytes, "
            "recv_bytes FROM llm_health").fetchall()
        return [{"provider": r[0], "model": r[1],
                 **dict(zip(self._HEALTH_COLS, r[2:]))} for r in rows]


class LLMHealthStore:
    """Adapter giving the governor its load/save contract over the repo."""

    def __init__(self, repo: Repo):
        self.repo = repo

    def load(self, provider: str, model: str) -> dict | None:
        return self.repo.llm_health_load(provider, model)

    def save(self, provider: str, model: str, state: dict) -> None:
        self.repo.llm_health_save(provider, model, state)
