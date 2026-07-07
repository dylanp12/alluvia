"""MCP server: alluvia's idea-map as tools for any MCP client (Claude Code, Cursor).

Design (spec 2026-07-03): pure *_impl functions (bounded JSON out, errors as
values — a tool must never raise into the host session); FastMCP wiring closes
over lazily-built deps so read-only sessions construct no LLM clients.
Guardrail policy lives in the TOOL CONTRACTS (docstrings) + the rated_via audit
trail; propose_next visibly spends the user's LLM budget."""
from __future__ import annotations

from alluvia import config
from alluvia.models import to_utc
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo

MAX_LIMIT = 25
TEXT_CAP = 400


def _t(s, cap: int = TEXT_CAP):
    if not s:
        return s
    s = str(s)
    return s if len(s) <= cap else s[:cap] + "…"


def _cap(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


class SiftDeps:
    """Lazy deps: repo now; embedder/LLMs only on first use."""

    def __init__(self):
        conn = connect(config.db_path())
        init_schema(conn, embed_dim=384)
        self.repo = Repo(conn)
        self._emb = None
        self._gen = None
        self._critic = None

    @property
    def embedder(self):
        if self._emb is None:
            from alluvia.engine.embed import FastEmbedEmbedder
            self._emb = FastEmbedEmbedder()
        return self._emb

    @property
    def gen_llm(self):
        if self._gen is None:
            from alluvia.llm.client import make_llm
            self._gen = make_llm(role="propose")
        return self._gen

    @property
    def critic_llm(self):
        if self._critic is None:
            from alluvia.llm.client import make_llm
            self._critic = make_llm(role="status")
        return self._critic


def _theme_json(t):
    span = None
    if t.first_seen and t.last_seen:
        span = f"{to_utc(t.first_seen).date()}→{to_utc(t.last_seen).date()}"
    return {"id": t.id, "label": _t(t.label, 120), "summary": _t(t.summary),
            "status": t.status, "sessions": t.session_count,
            "sources": t.source_count, "span": span}


def recall_themes_impl(deps, query: str | None = None, limit: int = 10) -> dict:
    try:
        limit = _cap(limit)
        user = config.DEFAULT_USER
        muted = deps.repo.muted_labels(user)
        themes = [t for t in deps.repo.list_themes(user)
                  if t.label.lower() not in muted]
        if query:
            hits = deps.repo.search_notes(user, deps.embedder.embed([query])[0], k=50)
            hit_ids = {h[0] for h in hits}
            scored = [(sum(1 for n in t.note_ids if n in hit_ids), t) for t in themes]
            themes = [t for score, t in sorted(scored, key=lambda x: -x[0]) if score > 0]
        return {"themes": [_theme_json(t) for t in themes[:limit]], "limit": limit}
    except Exception as e:
        return {"error": str(e)}


def _note_json(n):
    return {"id": n.id, "text": _t(n.text), "kind": n.kind,
            "source": n.session_id.split(":", 1)[0],
            "date": str(to_utc(n.created_at).date()) if n.created_at else None}


def find_connections_impl(deps, topic: str | None = None, limit: int = 10) -> dict:
    try:
        limit = _cap(limit)
        user = config.DEFAULT_USER
        notes = {n.id: n for n in deps.repo.get_notes(user)}
        links = deps.repo.list_links(user, limit=200)
        if topic:
            hits = deps.repo.search_notes(user, deps.embedder.embed([topic])[0], k=50)
            hit_ids = {h[0] for h in hits}
            links = [l for l in links
                     if l.from_note_id in hit_ids or l.to_note_id in hit_ids]
        out = []
        for l in links[:limit]:
            a, b = notes.get(l.from_note_id), notes.get(l.to_note_id)
            if not a or not b:
                continue
            out.append({"from": _note_json(a), "to": _note_json(b),
                        "weight": round(l.weight, 3), "why": _t(l.why, 200)})
        return {"connections": out, "limit": limit}
    except Exception as e:
        return {"error": str(e)}


def unfinished_threads_impl(deps, include_dormant: bool = False) -> dict:
    try:
        user = config.DEFAULT_USER
        wanted = {"open", "dormant"} if include_dormant else {"open"}
        muted = deps.repo.muted_labels(user)
        themes = [t for t in deps.repo.list_themes(user)
                  if t.status in wanted and t.label.lower() not in muted]

        def span_days(t):
            if t.first_seen and t.last_seen:
                return (to_utc(t.last_seen) - to_utc(t.first_seen)).days
            return 0

        themes.sort(key=lambda t: t.session_count * (span_days(t) + 1), reverse=True)
        return {"threads": [_theme_json(t) for t in themes[:MAX_LIMIT]]}
    except Exception as e:
        return {"error": str(e)}


def show_source_impl(deps, note_id: str) -> dict:
    try:
        user = config.DEFAULT_USER
        note = next((n for n in deps.repo.get_notes(user) if n.id == note_id), None)
        if note is None:
            return {"error": f"no note {note_id}"}
        from alluvia.engine.propose import _excerpt
        session = deps.repo.get_session(user, note.session_id)
        return {"note": _note_json(note),
                "raw_excerpt": _t(_excerpt(deps.repo, user, note), TEXT_CAP),
                "session": {"id": note.session_id,
                            "title": _t(session.title, 120) if session else None,
                            "source": note.session_id.split(":", 1)[0]}}
    except Exception as e:
        return {"error": str(e)}


def _prop_json(p):
    return {"id": p.id, "title": _t(p.title, 120), "text": _t(p.text),
            "next_step": _t(p.next_step, 200), "feasibility": p.feasibility,
            "risk": _t(p.risk, 200), "cites": p.cites, "outcome": p.outcome}


def list_proposals_impl(deps, all: bool = False) -> dict:
    try:
        user = config.DEFAULT_USER
        outcomes = ("pending", "kept", "dismissed", "rejected") if all else ("pending",)
        props = sorted(deps.repo.list_proposals(user, outcomes=outcomes),
                       key=lambda p: -(p.feasibility if p.feasibility is not None else 2.5))
        return {"proposals": [_prop_json(p) for p in props[:MAX_LIMIT]]}
    except Exception as e:
        return {"error": str(e)}


def propose_next_impl(deps, theme_id: str | None = None, limit: int = 3) -> dict:
    try:
        limit = _cap(limit)
        user = config.DEFAULT_USER
        from alluvia.engine.propose import Candidate, candidates, generate_proposal
        if theme_id:
            t = deps.repo.get_theme(user, theme_id)
            if not t:
                return {"error": f"no theme {theme_id}"}
            cands = [Candidate(kind="theme", source_ref=t.id,
                               note_ids=tuple(t.note_ids))]
        else:
            cands = candidates(deps.repo, user, limit=limit)
        made = []
        model = getattr(deps.gen_llm, "model", "unknown")
        for cand in cands[:limit]:
            p = generate_proposal(deps.repo, user, cand, deps.gen_llm,
                                  deps.critic_llm, deps.embedder, model_name=model)
            if p:
                made.append(_prop_json(p))
        return {"proposals": made, "model": model,
                "note": "generation spends the user's LLM budget"}
    except Exception as e:
        return {"error": str(e)}


def get_digest_impl(deps) -> dict:
    try:
        import os
        user = config.DEFAULT_USER
        last = deps.repo.latest_digest(user)
        if not last:
            return {"digest": None, "pending": False}
        flag = os.environ.get("SIFT_PENDING_FLAG",
                              os.path.expanduser("~/.alluvia/digest-pending"))
        items = deps.repo.digest_items(user, last[0])
        return {"digest": {"id": last[0], "created_at": last[1],
                           "items": [{"n": i["n"], "kind": i["kind"],
                                      "snapshot": _t(i["snapshot"]),
                                      "outcome": i["outcome"]} for i in items]},
                "pending": os.path.exists(flag)}
    except Exception as e:
        return {"error": str(e)}


def rate_proposal_impl(deps, proposal_id: str, verdict: str,
                       note: str | None = None) -> dict:
    try:
        if verdict not in ("keep", "dismiss"):
            return {"error": "verdict must be 'keep' or 'dismiss'"}
        user = config.DEFAULT_USER
        if not deps.repo.get_proposal(user, proposal_id):
            return {"error": f"no proposal {proposal_id}"}
        outcome = "kept" if verdict == "keep" else "dismissed"
        deps.repo.rate_proposal(user, proposal_id, outcome, note=note, via="mcp")
        return {"id": proposal_id, "outcome": outcome, "rated_via": "mcp"}
    except Exception as e:
        return {"error": str(e)}


def build_server(deps: SiftDeps | None = None):
    """Register alluvia's tools on a FastMCP server. Tool docstrings ARE the
    contracts (enforcement is contractual + audited via rated_via, not
    technical — a confirm-before-write/spend mode is product-era debt)."""
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("alluvia")
    d = deps or SiftDeps()

    @mcp.tool()
    def recall_themes(query: str | None = None, limit: int = 10) -> dict:
        """Search the user's cross-tool idea-map for themes (clusters of their past
        thinking). Use `query` for semantic search; omit for the top themes."""
        return recall_themes_impl(d, query=query, limit=limit)

    @mcp.tool()
    def find_connections(topic: str | None = None, limit: int = 10) -> dict:
        """Surprising bridges between the user's ideas across different tools and
        months. Use `topic` to filter semantically."""
        return find_connections_impl(d, topic=topic, limit=limit)

    @mcp.tool()
    def unfinished_threads(include_dormant: bool = False) -> dict:
        """Themes the user keeps returning to without ever resolving — ranked by
        how much they've circled them."""
        return unfinished_threads_impl(d, include_dormant=include_dormant)

    @mcp.tool()
    def show_source(note_id: str) -> dict:
        """Trace any note back to its raw session excerpt (grounding/provenance)."""
        return show_source_impl(d, note_id=note_id)

    @mcp.tool()
    def list_proposals(all: bool = False) -> dict:
        """The user's pending alluvia proposals (generated next-steps awaiting THEIR
        judgment). all=true includes rated and rejected ones."""
        return list_proposals_impl(d, all=all)

    @mcp.tool()
    def propose_next(theme_id: str | None = None, limit: int = 3) -> dict:
        """Generate NEW grounded proposals from the user's idea-map. This SPENDS
        THE USER'S LLM BUDGET — call only when the user explicitly asks for
        proposals."""
        return propose_next_impl(d, theme_id=theme_id, limit=limit)

    @mcp.tool()
    def get_digest() -> dict:
        """The user's latest alluvia digest (proactive summary of connections,
        unfinished threads, and a proposal). If `pending` is true, surface it to
        the user at a natural moment. Relay only — never dismiss/keep on your own."""
        return get_digest_impl(d)

    @mcp.tool()
    def rate_proposal(proposal_id: str, verdict: str, note: str | None = None) -> dict:
        """Record the USER'S judgment on a proposal. Call ONLY to relay their
        explicit verbal verdict ('keep it' / 'dismiss that') — NEVER rate on your
        own initiative. verdict: keep | dismiss."""
        return rate_proposal_impl(d, proposal_id=proposal_id, verdict=verdict,
                                  note=note)

    return mcp


def serve() -> None:
    build_server().run()
