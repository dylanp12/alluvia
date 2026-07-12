"""Localhost dashboard: read-only JSON endpoints + a bundled single-file UI.

Endpoint functions are pure (repo, user) -> dict and transport-agnostic — the
P2 hosted era wraps these same functions in an authenticated server. The local
server binds 127.0.0.1 only; nothing leaves the machine."""
from __future__ import annotations
import json
import logging
import os
from collections import Counter, defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from alluvia import config
from alluvia.models import to_utc

log = logging.getLogger(__name__)


def overview(repo, user_id: str) -> dict:
    themes = repo.list_themes(user_id)
    notes = repo.get_notes(user_id)
    sessions = repo.list_sessions(user_id)
    props = repo.list_proposals(user_id, outcomes=("pending", "kept",
                                                   "dismissed", "rejected"))
    kept = sum(1 for p in props if p.outcome == "kept")
    dismissed = sum(1 for p in props if p.outcome == "dismissed")
    rated = kept + dismissed
    per_source = Counter(s.source for s in sessions)
    refresh = None
    raw = repo.get_meta("last_refresh")
    if raw:
        try:
            m = json.loads(raw)
            refresh = {"at": m.get("at"), "degraded": bool(m.get("degraded")),
                       "retry_at": m.get("retry_at")}
        except ValueError:
            pass
    return {
        "sessions": len(sessions), "notes": len(notes), "themes": len(themes),
        "links": len(repo.list_links(user_id)),
        "sources": dict(per_source),
        "status_mix": dict(Counter(t.status for t in themes)),
        "proposals": {"total": len(props), "kept": kept, "dismissed": dismissed,
                      "hit_rate": (kept * 100 // rated) if rated else None},
        "refresh": refresh,
    }


def themes_data(repo, user_id: str) -> dict:
    muted = repo.muted_labels(user_id)
    out = []
    for t in repo.list_themes(user_id):
        span = None
        if t.first_seen and t.last_seen:
            span = [to_utc(t.first_seen).date().isoformat(),
                    to_utc(t.last_seen).date().isoformat()]
        out.append({"id": t.id, "label": t.label, "summary": t.summary,
                    "status": t.status, "sessions": t.session_count,
                    "sources": t.source_count, "notes": len(t.note_ids),
                    "span": span, "muted": t.label.lower() in muted})
    return {"themes": out}


def links_data(repo, user_id: str) -> dict:
    themes = {t.id: t for t in repo.list_themes(user_id)}
    notes = {n.id: n for n in repo.get_notes(user_id)}
    pair_agg: dict[tuple, dict] = {}
    for l in repo.list_links(user_id, limit=200):
        a, b = notes.get(l.from_note_id), notes.get(l.to_note_id)
        if not a or not b:
            continue
        key = tuple(sorted([l.from_theme_id or "?", l.to_theme_id or "?"]))
        agg = pair_agg.setdefault(key, {"count": 0, "max_weight": 0.0,
                                        "sample": None})
        agg["count"] += 1
        if l.weight > agg["max_weight"]:
            agg["max_weight"] = round(l.weight, 3)
            agg["sample"] = {
                "from": {"text": a.text[:200],
                         "source": a.session_id.split(":", 1)[0]},
                "to": {"text": b.text[:200],
                       "source": b.session_id.split(":", 1)[0]},
                "why": l.why,
            }
    nodes = [{"id": tid, "label": t.label, "status": t.status,
              "sessions": t.session_count}
             for tid, t in themes.items()]
    edges = [{"a": k[0], "b": k[1], **v} for k, v in pair_agg.items()]

    # the hero data: individual bridges ranked by weight, with the human story
    # fields (date gap, sources, why, both excerpts) front and center
    bridges = []
    for l in repo.list_links(user_id, limit=20):
        a, b = notes.get(l.from_note_id), notes.get(l.to_note_id)
        if not a or not b:
            continue
        gap_days = None
        if a.created_at and b.created_at:
            gap_days = abs((to_utc(a.created_at) - to_utc(b.created_at)).days)
        ta, tb = themes.get(l.from_theme_id), themes.get(l.to_theme_id)
        bridges.append({
            "id": l.id, "weight": round(l.weight, 3), "why": l.why,
            "gap_days": gap_days,
            "from": {"text": a.text[:220], "source": a.session_id.split(":", 1)[0],
                     "date": (str(to_utc(a.created_at).date())
                              if a.created_at else None),
                     "theme": ta.label if ta else None},
            "to": {"text": b.text[:220], "source": b.session_id.split(":", 1)[0],
                   "date": (str(to_utc(b.created_at).date())
                            if b.created_at else None),
                   "theme": tb.label if tb else None},
        })
    return {"nodes": nodes, "edges": edges, "bridges": bridges}


def timeline_data(repo, user_id: str) -> dict:
    weeks: dict[str, Counter] = defaultdict(Counter)
    for s in repo.list_sessions(user_id):
        if not s.started_at:
            continue
        d = to_utc(s.started_at).date()
        iso = d.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        weeks[week][s.source] += 1
    arcs = []
    for t in repo.list_themes(user_id):
        if t.status in ("open", "dormant") and t.first_seen and t.last_seen:
            arcs.append({"label": t.label, "status": t.status,
                         "start": to_utc(t.first_seen).date().isoformat(),
                         "end": to_utc(t.last_seen).date().isoformat(),
                         "sessions": t.session_count})
    return {"weeks": [{"week": w, "by_source": dict(c)}
                      for w, c in sorted(weeks.items())],
            "arcs": sorted(arcs, key=lambda a: a["start"])}


def proposals_data(repo, user_id: str) -> dict:
    props = repo.list_proposals(user_id, outcomes=("pending", "kept",
                                                   "dismissed", "rejected"))
    return {"proposals": [{
        "id": p.id, "title": p.title, "feasibility": p.feasibility,
        "outcome": p.outcome, "reject_reason": p.reject_reason,
        "rated_via": p.rated_via, "rating_note": p.rating_note,
        "created_at": p.created_at} for p in props]}


def digests_data(repo, user_id: str) -> dict:
    out = []
    last = repo.latest_digest(user_id)
    if last:
        for did in range(1, last[0] + 1):
            items = repo.digest_items(user_id, did)
            if items or did == last[0]:
                out.append({"id": did, "items": items})
    return {"digests": out}


def search_data(repo, user_id: str, q: str, embedder=None) -> dict:
    """Vector search over notes (when an embedder is available) + substring
    match over theme labels. Pure function; embedder injected."""
    q = (q or "").strip()
    if not q:
        return {"notes": [], "themes": []}
    themes = repo.list_themes(user_id)
    note_theme = {}
    for t in themes:
        for nid in t.note_ids:
            note_theme[nid] = t
    toks = [w for w in q.lower().split() if len(w) > 1]
    theme_hits = [{"id": t.id, "label": t.label, "status": t.status,
                   "sessions": t.session_count}
                  for t in themes
                  if any(w in t.label.lower() for w in toks)][:10]
    note_hits = []
    if embedder is not None:
        try:
            notes = {n.id: n for n in repo.get_notes(user_id)}
            for nid, score in repo.search_notes(user_id,
                                                embedder.embed([q])[0], k=12):
                n = notes.get(nid)
                if not n:
                    continue
                t = note_theme.get(nid)
                note_hits.append({
                    "id": nid, "text": n.text[:220], "kind": n.kind,
                    "source": n.session_id.split(":", 1)[0],
                    "date": (str(to_utc(n.created_at).date())
                             if n.created_at else None),
                    "score": round(float(score), 3),
                    "theme": {"id": t.id, "label": t.label} if t else None})
        except Exception as e:
            log.warning("vector search unavailable (%s)", e)
    return {"notes": note_hits, "themes": theme_hits}


ENDPOINTS = {
    "overview": overview,
    "themes": themes_data,
    "links": links_data,
    "timeline": timeline_data,
    "proposals": proposals_data,
    "digests": digests_data,
}


def _index_html() -> bytes:
    path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(path, "rb") as f:
        return f.read()


def make_handler(repo, user_id: str, embedder_factory=None):
    holder = {"emb": None}

    def _embedder():
        if holder["emb"] is None and embedder_factory is not None:
            holder["emb"] = embedder_factory()
        return holder["emb"]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):          # quiet by default
            log.debug(fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                if self.path in ("/", "/index.html"):
                    self._send(200, _index_html(), "text/html; charset=utf-8")
                    return
                if self.path.startswith("/api/"):
                    from urllib.parse import parse_qs, urlparse
                    parsed = urlparse(self.path)
                    name = parsed.path[len("/api/"):]
                    if name == "search":
                        q = parse_qs(parsed.query).get("q", [""])[0]
                        body = json.dumps(search_data(repo, user_id, q,
                                                      _embedder())).encode()
                        self._send(200, body, "application/json")
                        return
                    fn = ENDPOINTS.get(name)
                    if fn is None:
                        self._send(404, json.dumps({"error": "unknown endpoint"})
                                   .encode(), "application/json")
                        return
                    body = json.dumps(fn(repo, user_id)).encode()
                    self._send(200, body, "application/json")
                    return
                self._send(404, json.dumps({"error": "not found"}).encode(),
                           "application/json")
            except Exception as e:                   # never a traceback page
                self._send(500, json.dumps({"error": str(e)}).encode(),
                           "application/json")
    return Handler


def looks_like_alluvia(port: int, timeout: float = 0.5) -> bool:
    """True if something on 127.0.0.1:<port> answers /api/overview like us."""
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/overview", timeout=timeout) as r:
            return "themes" in json.loads(r.read().decode())
    except Exception:
        return False


def pick_port(start: int, tries: int = 10) -> int:
    """First bindable localhost port from `start`."""
    import socket
    for p in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise OSError(f"no free port in {start}-{start + tries - 1}")


def serve(repo, user_id: str = None, port: int = 8177,
          embedder_factory=None) -> ThreadingHTTPServer:
    user_id = user_id or config.DEFAULT_USER
    if embedder_factory is None:
        def embedder_factory():
            from alluvia.engine.embed import FastEmbedEmbedder
            return FastEmbedEmbedder()
    server = ThreadingHTTPServer(
        ("127.0.0.1", port), make_handler(repo, user_id, embedder_factory))
    return server
