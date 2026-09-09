from __future__ import annotations
import os
import typer
from alluvia import config
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo
from alluvia.ingest.claude_code import ClaudeCodeAdapter

app = typer.Typer(help="alluvia — resurface ideas from across your AI history")

# embeddings dim is fixed once the engine phase lands; 384 = bge-small default.
EMBED_DIM = 384


def _fmt_bytes(n) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def _version_callback(value: bool):
    if value:
        from importlib.metadata import PackageNotFoundError, version
        try:
            v = version("alluvia")
        except PackageNotFoundError:
            v = "dev"
        typer.echo(f"alluvia {v}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", callback=_version_callback,
                                 is_eager=True, help="Show version and exit."),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                 help="Show pipeline/governor activity on stderr."),
):
    if verbose:
        import logging
        import sys
        logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                            format="%(name)s \u00b7 %(message)s", force=True)
    if ctx.invoked_subcommand is None:
        _now_view()


def _now_view():
    """Bare `alluvia`: the now-view — what's open, what bridged, what's next."""
    import json as _json
    repo = _repo()
    themes = repo.list_themes(config.DEFAULT_USER)
    if not themes and not repo.list_sessions(config.DEFAULT_USER):
        typer.echo("alluvia — nothing here yet. start with: alluvia init")
        return
    open_loops = [t for t in themes if t.status in ("open", "dormant")][:3]
    typer.echo(f"themes: {len(themes)}")
    if open_loops:
        typer.echo("open loops (unfinished):")
        for t in open_loops:
            typer.echo(f"  \U0001f9f5 {t.label}  [{t.status}] \u00b7 {t.session_count} sessions")
    links = repo.list_links(config.DEFAULT_USER, limit=3)
    if links:
        notes = {n.id: n for n in repo.get_notes(config.DEFAULT_USER)}
        typer.echo("freshest bridges:")
        for l in links:
            a, b = notes.get(l.from_note_id), notes.get(l.to_note_id)
            if a and b:
                typer.echo(f"  \U0001f517 {a.text[:52]} \u2194 {b.text[:52]}")
    raw = repo.get_meta("last_refresh")
    if raw:
        try:
            meta = _json.loads(raw)
            state = "degraded \u2014 re-run refresh" if meta.get("degraded") else "healthy"
            typer.echo(f"last refresh: {meta.get('at', '?')[:10]} \u00b7 {state}")
        except ValueError:
            pass
    else:
        typer.echo("no refresh yet \u2014 run `alluvia refresh`")
    typer.echo("ask it something: alluvia recall \"<what you're working on>\" --handoff")


def _repo() -> Repo:
    conn = connect(config.db_path())
    init_schema(conn, embed_dim=EMBED_DIM)
    return Repo(conn)


def build_engine(repo: Repo, reporter=None):
    from alluvia.engine.engine import Engine
    from alluvia.engine.embed import FastEmbedEmbedder
    from alluvia.llm.client import RoleRouter
    from alluvia.store.repo import LLMHealthStore
    # role-routed models, governed with SQLite-persisted breaker state: a
    # short-lived CLI run respects cooldowns learned by previous runs
    on_wait = None
    if reporter is not None:
        def on_wait(model, seconds):
            reporter.note(f"rate-limited: waiting {int(seconds)}s ({model})")
    return Engine(repo, FastEmbedEmbedder(),
                  RoleRouter(health=LLMHealthStore(repo), on_wait=on_wait),
                  min_cluster_size=config.min_cluster())


@app.command()
def ingest(
    source: str = typer.Option("claude-code", "--source",
                               help="claude-code | cursor | codex | gemini | opencode | cline | kilo-code | roo-code | windsurf | antigravity | chatgpt-export | jsonl (docs/SOURCES.md)"),
    path: str = typer.Option(None, "--path",
                             help="Root/logs dir (claude-code), fork root override, "
                                  "or export ZIP/dir (chatgpt-export)"),
):
    from alluvia.ingest import SOURCES
    repo = _repo()
    if source not in SOURCES:
        raise typer.BadParameter(f"unknown source: {source}. known: {', '.join(SOURCES)}")
    try:
        adapter = SOURCES[source](path)
    except ValueError as e:
        raise typer.BadParameter(str(e))
    from alluvia.progress import make_reporter
    rep = make_reporter()
    n_new = 0
    total = 0
    try:
        rep.start(f"ingesting {source}")
        for s in adapter.read():
            total += 1
            rep.advance()
            if repo.upsert_session(s):
                n_new += 1
    finally:
        rep.close()
    typer.echo(f"ingested {total} session(s), {n_new} new/changed")


@app.command()
def show(session_id: str):
    s = _repo().get_session(config.DEFAULT_USER, session_id)
    if not s:
        typer.echo(f"no session {session_id}")
        raise typer.Exit(1)
    typer.echo(f"# {s.title}  [{s.source}:{s.native_id}]")
    for m in s.messages:
        typer.echo(f"\n[{m.role}] {m.text}")


@app.command()
def tensions(
    scan: int = typer.Option(0, "--scan",
                              help="First classify the top N connections into "
                                   "typed relations (uses your LLM)"),
    keep: str = typer.Option(None, "--keep",
                              help="Confirm a finding by id — promotes it to "
                                   "a confirmed relation in your map"),
    dismiss: str = typer.Option(None, "--dismiss",
                                 help="Dismiss a finding by id"),
):
    """Contradictions, superseded decisions, and recurring problems — typed
    findings with confidence, rationale, and source evidence. Predictions,
    not facts: confirm with --keep to promote one into your map."""
    from datetime import datetime, timezone
    repo = _repo()
    if keep or dismiss:
        from alluvia.engine.relate import judge_candidate
        out = judge_candidate(repo, config.DEFAULT_USER, keep or dismiss,
                              "keep" if keep else "dismiss",
                              now=datetime.now(timezone.utc))
        if "error" in out:
            typer.echo(out["error"])
            raise typer.Exit(1)
        verb = "confirmed → added to your map" if out["promoted"] \
            else "dismissed"
        typer.echo(f"{out['id']}: {verb}")
        return
    if scan:
        from alluvia.progress import make_reporter
        rep = make_reporter()
        try:
            rep.start("classifying connections")
            stats = build_engine(repo, reporter=rep).type_top_links(
                config.DEFAULT_USER, limit=scan)
        finally:
            rep.close()
        typer.echo(f"scanned {stats['examined']} connection(s): "
                   f"{stats['typed']} typed, {stats['skipped']} unrelated, "
                   f"{stats['errors']} errors")
    cands = [c for c in repo.list_candidates(config.DEFAULT_USER)
             if c["status"] in ("pending", "confirmed")]
    if not cands:
        typer.echo("no typed findings yet — run `alluvia tensions --scan 20` "
                   "to classify your top connections")
        return
    notes = {n.id: n for n in repo.get_notes(config.DEFAULT_USER)}
    order = {"CONTRADICTS": 0, "SUPERSEDES": 1, "RECURS_AS": 2,
             "ADDRESSES": 3, "TRANSFERS_TO": 4}
    cands.sort(key=lambda c: (order.get(c["relation"], 9), -(c["score"] or 0)))
    current = None
    for c in cands:
        if c["relation"] != current:
            current = c["relation"]
            typer.echo(f"\n== {current} ==")
        a, b = notes.get(c["subject_id"]), notes.get(c["object_id"])
        if not a or not b:
            continue
        mark = "✓ " if c["status"] == "confirmed" else ""
        typer.echo(f"{mark}[{c['score']:.2g}] \"{a.text[:100]}\"  ({c['id']})")
        typer.echo(f"      → \"{b.text[:100]}\"")
        if c["why"]:
            typer.echo(f"      why: {c['why']}")
        for ev in c["evidence"]:
            typer.echo(f"      evidence: {ev}")


@app.command()
def loops(limit: int = typer.Option(15, "--limit")):
    """Problems you recorded and never resolved: no fix decision points at
    them — not in your notes, not in your confirmed findings. Pure lookup;
    spends nothing."""
    from alluvia.models import to_utc
    from datetime import datetime, timezone
    repo = _repo()
    user = config.DEFAULT_USER
    notes = {n.id: n for n in repo.get_notes(user)}
    addressed = {e["object_id"] for e in repo.list_edges(user)
                 if e["relation"] in ("ADDRESSES", "RESOLVED_BY")}
    addressed |= {c["object_id"] for c in repo.list_candidates(user)
                  if c["relation"] in ("ADDRESSES", "RESOLVED_BY")
                  and c["status"] != "dismissed"}
    muted = repo.muted_labels(user)

    def span_days(t):
        if t.first_seen and t.last_seen:
            return (to_utc(t.last_seen) - to_utc(t.first_seen)).days
        return 0

    now = datetime.now(timezone.utc)
    rows = []
    for t in repo.list_themes(user):
        if t.status != "open" or t.label.lower() in muted:
            continue
        for nid in t.note_ids:
            n = notes.get(nid)
            if not n or n.kind != "problem" or n.id in addressed:
                continue
            age = (now - to_utc(n.created_at)).days if n.created_at else 0
            rows.append((t.session_count * (span_days(t) + 1), age, n, t))
    if not rows:
        typer.echo("no open loops — every recorded problem has an "
                   "addressing signal")
        return
    rows.sort(key=lambda r: (-r[0], -r[1]))
    for _, age, n, t in rows[:limit]:
        typer.echo(f"[{age}d] \"{n.text[:110]}\"")
        typer.echo(f"      theme: {t.label} · source: "
                   f"{n.session_id.split(':', 1)[0]} · {n.id}")


@app.command("export-graph")
def export_graph(
    out: str = typer.Option("alluvia-graph", "--out",
                             help="Destination directory for the bundle"),
    no_judgments: bool = typer.Option(False, "--no-judgments",
                                       help="Leave proposals/ratings out of "
                                            "the export"),
):
    """Export your knowledge map as a portable graph bundle (open format:
    contract.json + gzipped JSONL of nodes and events, with provenance)."""
    from datetime import datetime, timezone
    from alluvia import graph_export
    repo = _repo()
    manifest, nodes, events, judgments = graph_export.build_bundle(
        repo, config.DEFAULT_USER,
        now_iso=datetime.now(timezone.utc).isoformat(),
        include_judgments=not no_judgments)
    graph_export.write_bundle(out, manifest, nodes, events, judgments)
    typer.echo(f"wrote graph bundle: {out} "
               f"({len(nodes)} nodes, {len(events)} events)")


def _refresh_plan(repo) -> None:
    """No-spend preview of the next refresh."""
    import time as _time
    from datetime import datetime, timezone
    from alluvia.engine.engine import pending_distill
    todo = pending_distill(repo, config.DEFAULT_USER)
    themes = repo.list_themes(config.DEFAULT_USER)
    typer.echo(f"distill: {len(todo)} session(s) to distill")
    typer.echo(f"themes:  {len(themes)} current \u00b7 re-labeled/re-classified "
               f"only where content changed (caches skip the rest)")
    from alluvia.inspect import model_cache_dir
    import os as _os
    if not (_os.path.isdir(model_cache_dir()) and any(_os.scandir(model_cache_dir()))):
        typer.echo("note: first refresh downloads the local embedding model (~100 MB)")
    cooling = [r for r in repo.llm_health_all()
               if r["cooldown_until"] > _time.time()]
    for r in cooling:
        until = datetime.fromtimestamp(r["cooldown_until"], tz=timezone.utc)
        typer.echo(f"\u23f3 {r['provider']}/{r['model']} cooling until {until:%H:%M} UTC "
                   f"\u2014 refresh will use fallbacks or pause resumably")
    typer.echo("(plan only \u2014 no LLM calls were made, nothing was written)")


def _echo_refresh_summary(stats: dict, coverage: dict | None = None,
                          signed_in: bool | None = None, over_budget: bool = False,
                          managed_down: str | None = None, plan: str | None = None) -> None:
    """Per-stage outcome of a refresh — a degraded map must never be
    indistinguishable from a healthy one. A pause also says what would end it:
    sign in once, or raise the managed budget."""
    d, t = stats.get("distill", {}), stats.get("themes", {})
    if d.get("todo"):
        line = f"distilled: {d.get('ok', 0)}/{d['todo']} sessions"
        extras = [f"{d[k]} {w}" for k, w in
                  (("zero_note", "empty"), ("failed", "failed")) if d.get(k)]
        typer.echo(line + (f" ({', '.join(extras)})" if extras else ""))
        if d.get("deferred"):
            typer.echo(f"first run: newest sessions first — {d['deferred']} "
                       f"more backfill on the next refresh")
    if coverage and coverage.get("sessions"):
        pct = 100 * coverage["distilled"] // coverage["sessions"]
        typer.echo(f"coverage: {coverage['distilled']}/{coverage['sessions']} sessions "
                   f"distilled ({pct}%)")
        if d.get("cold") and coverage.get("pending"):
            retry = (f" — retry after {stats['retry_at'][:16]} UTC"
                     if stats.get("retry_at") else "")
            typer.echo(f"⏸ paused: provider rate-limited, {coverage['pending']} pending"
                       f"{retry}; `alluvia refresh` resumes where it stopped")
            if managed_down:
                typer.echo(f"  Alluvia Cloud's managed distillation is unavailable right now "
                           f"({managed_down}). This is on our side, not yours; your own provider "
                           f"is still tried first and the managed path retries after its cooldown")
            elif signed_in and plan == "free":
                typer.echo(f"  {coverage['pending']} sessions are waiting to be processed. Pro processes "
                           f"them now, no API key needed: upgrade in Account at the app "
                           f"(alluvia cloud status)")
            elif signed_in and over_budget:
                typer.echo("  your 1,000 sessions this month are used up: more next month, or raise "
                           "it in Account at the app")
            elif signed_in is False:
                typer.echo("  Pro processes these for you, no API key needed: sign in once "
                           "(`alluvia cloud login`), then upgrade in Account")
    if t.get("built"):
        typer.echo(f"labels: {t.get('label_cached', 0)} cached · "
                   f"{t.get('label_llm', 0)} fresh · "
                   f"{t.get('label_fallback', 0)} pending")
        typer.echo(f"status: {t.get('status_ok', 0)} classified · "
                   f"{t.get('status_heuristic', 0)} heuristic · "
                   f"{t.get('status_error', 0)} failed · "
                   f"{t.get('status_na', 0)} n/a")
    if stats.get("degraded"):
        retry = (f" — provider retry after {stats['retry_at'][:16]} UTC"
                 if stats.get("retry_at") else "")
        typer.echo(f"⚠ the LLM provider was rate-limited during this run{retry}")
        typer.echo("  the map degraded gracefully; re-run `alluvia refresh` to "
                   "complete it (pending labels/statuses retry automatically)")


def _maybe_degraded_hint(repo) -> None:
    import json as _json
    raw = repo.get_meta("last_refresh")
    if not raw:
        return
    try:
        meta = _json.loads(raw)
    except ValueError:
        return
    if meta.get("degraded"):
        retry = (f" (provider retry after {meta['retry_at'][:16]} UTC)"
                 if meta.get("retry_at") else "")
        typer.echo(f"⚠ last refresh was degraded by provider rate limits{retry} "
                   f"— re-run `alluvia refresh` to complete the map")


@app.command()
def refresh(
    plan: bool = typer.Option(False, "--plan",
                              help="Preview what a refresh would do — no LLM calls, no writes."),
):
    from alluvia.lockfile import acquire, holder_pid
    from alluvia.progress import make_reporter
    if plan:
        _refresh_plan(_repo())
        return
    lock_path = config.db_path() + ".refresh.lock"
    lock = acquire(lock_path)
    if lock is None:
        # single-writer by design: a second refresh would only double-spend
        # the LLM budget doing identical, idempotent work
        typer.echo(f"another refresh is already running (pid {holder_pid(lock_path)}) "
                   f"— exiting; the store stays consistent")
        return
    repo = _repo()
    rep = make_reporter()
    from alluvia import cloud_memory
    # signed in: what other machines learned counts as done before we distill
    pulled = cloud_memory.pull(repo, config.DEFAULT_USER)
    try:
        stats = build_engine(repo, reporter=rep).refresh(config.DEFAULT_USER,
                                                         reporter=rep)
    except KeyboardInterrupt:
        # kill-anytime contract: everything committed so far is durable and
        # every stage resumes from markers/caches on the next run
        typer.echo("\npaused — everything done so far is saved; "
                   "run `alluvia refresh` to resume")
        raise typer.Exit(130)
    finally:
        rep.close()
        lock.release()
    typer.echo(f"themes: {len(repo.list_themes(config.DEFAULT_USER))}")
    pushed = cloud_memory.push(repo, config.DEFAULT_USER)
    managed_down = _record_managed_state(repo)
    if isinstance(stats, dict):
        _echo_refresh_summary(stats,
                              coverage=repo.distill_coverage(config.DEFAULT_USER),
                              signed_in=_cloud_signed_in(),
                              over_budget=_managed_cooling(repo),
                              managed_down=managed_down,
                              plan=(_cloud_session() or {}).get("plan"))
    _echo_memory_sync(pulled, pushed)
    from alluvia.hooks import refresh_handoffs
    n_handoffs = refresh_handoffs(repo, config.DEFAULT_USER)
    if n_handoffs:
        typer.echo(f"handoffs: {n_handoffs} repo(s) ready for the next Claude Code session")


def _record_managed_state(repo) -> str | None:
    """Persist what the managed candidate reported this run so `cloud status`
    can show it later; returns the outage reason when it is down."""
    import json as _json
    from datetime import datetime, timedelta, timezone
    from alluvia.cloud_memory import MANAGED_DOWN
    from alluvia.llm.client import MANAGED_COOLDOWN, managed_status
    ms = managed_status()
    if ms["state"] == "down":
        now = datetime.now(timezone.utc)
        repo.set_meta(MANAGED_DOWN, _json.dumps({
            "reason": ms["reason"], "at": now.isoformat(),
            "until": (now + timedelta(seconds=MANAGED_COOLDOWN)).isoformat()}))
        return ms["reason"]
    if ms["state"] == "ok":
        repo.set_meta(MANAGED_DOWN, "")
    return None


def _cloud_session() -> dict | None:
    from alluvia.cloudclient import load_session
    return load_session()


def _cloud_signed_in() -> bool:
    from alluvia.cloudclient import load_session
    sess = load_session()
    return bool(sess and sess.get("token") and sess.get("url"))


def _managed_cooling(repo) -> bool:
    """The managed gateway answered 429 (budget spent) and is cooling down."""
    import time as _time
    from alluvia.llm.client import ManagedLLM
    return any(r["model"] == ManagedLLM.model and r["cooldown_until"] > _time.time()
               for r in repo.llm_health_all())


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _echo_memory_sync(pulled: dict, pushed: dict) -> None:
    """One line about the cloud, only when signed in; silence otherwise."""
    if pulled.get("skipped") and pushed.get("skipped"):
        return
    if pulled.get("ok") and pushed.get("ok"):
        typer.echo(f"memory: {_plural(pulled.get('notes_added', 0), 'note')} received · "
                   f"{_plural(pushed.get('notes', 0), 'note')} sent (Alluvia Cloud)")
        return
    if pushed.get("limit") == "machines":
        typer.echo("memory: Free syncs one machine. Pro syncs all of them: upgrade in Account at the app")
        return
    err = pulled.get("error") or pushed.get("error") or "unknown error"
    if "timed out" in err:
        typer.echo("memory sync: the server is still working through a large sync; "
                   "check `alluvia cloud status` in a minute")
        return
    typer.echo(f"memory sync: {err} (retries on the next refresh)")


@app.command()
def themes():
    repo = _repo()
    ts = repo.list_themes(config.DEFAULT_USER)
    muted = repo.muted_labels(config.DEFAULT_USER)
    if not ts:
        typer.echo("no themes yet — run `alluvia refresh`")
        return
    for t in ts:
        span = ""
        if t.first_seen and t.last_seen:
            span = f"  ({t.first_seen.date()}→{t.last_seen.date()})"
        tag = " [muted]" if t.label.lower() in muted else ""
        typer.echo(f"• {t.label}{tag}  [{t.session_count} sessions/{t.source_count} sources]{span}")
        typer.echo(f"    {t.summary}")
    _maybe_degraded_hint(repo)


@app.command()
def mute(label: str):
    """Exclude a theme (by exact label, case-insensitive) from digests,
    unfinished, recall, and proposals."""
    repo = _repo()
    matches = [t for t in repo.list_themes(config.DEFAULT_USER)
               if t.label.lower() == label.strip().lower()]
    if len(matches) > 1:
        typer.echo(f"warning: {len(matches)} themes share this exact label — "
                   f"all will be muted")
    elif not matches:
        typer.echo("warning: no current theme has this exact label "
                   "(mute recorded; applies if one appears)")
    repo.mute_label(config.DEFAULT_USER, label)
    typer.echo(f"muted: {label}")


@app.command()
def unmute(label: str):
    _repo().unmute_label(config.DEFAULT_USER, label)
    typer.echo(f"unmuted: {label}")


@app.command()
def forget(
    note_id: str = typer.Argument(None),
    reason: str = typer.Option(None, "--reason",
                               help="Why it is wrong or stale (kept with the record)."),
    list_: bool = typer.Option(False, "--list", help="Show suppressed notes."),
):
    """Suppress a note that is wrong or stale: it never surfaces again in
    recall, handoffs, or MCP. Raw sessions are untouched; `unforget` reverses."""
    repo = _repo()
    if list_:
        rows = repo.list_suppressed(config.DEFAULT_USER)
        if not rows:
            typer.echo("nothing suppressed")
        for r in rows:
            typer.echo(f"{r['note_id']}  {r['created_at'][:10]}  {r['reason'] or ''}")
        return
    if not note_id:
        raise typer.BadParameter("give a note id (see `cites:` under a recall hit) or --list")
    known = {n.id for n in repo.get_notes(config.DEFAULT_USER)}
    if note_id not in known:
        typer.echo(f"no note {note_id}")
        raise typer.Exit(1)
    repo.suppress_note(config.DEFAULT_USER, note_id, reason=reason)
    typer.echo(f"forgotten: {note_id} — it will not surface again "
               f"(alluvia unforget to reverse)")


@app.command()
def unforget(note_id: str):
    _repo().unsuppress_note(config.DEFAULT_USER, note_id)
    typer.echo(f"restored: {note_id}")


@app.command()
def muted():
    labels = sorted(_repo().muted_labels(config.DEFAULT_USER))
    typer.echo("\n".join(labels) if labels else "(nothing muted)")


@app.command()
def ask(query: str):
    repo = _repo()
    t = build_engine(repo).ask(config.DEFAULT_USER, query)
    if not t:
        typer.echo("nothing found — have you run `alluvia refresh`?")
        raise typer.Exit(1)
    typer.echo(f"# {t.label}\n{t.summary}")


def build_propose_deps(repo: Repo):
    """(gen_llm, critic_llm, embedder) for the propose pipeline — separate seam
    so tests inject fakes and the propose role map applies."""
    from alluvia.engine.embed import FastEmbedEmbedder
    from alluvia.llm.client import make_llm
    from alluvia.store.repo import LLMHealthStore
    health = LLMHealthStore(repo)
    return (make_llm(role="propose", health=health),
            make_llm(role="status", health=health), FastEmbedEmbedder())


def _feas_sort_key(p):
    return -(p.feasibility if p.feasibility is not None else 2.5)


def _show_proposal(p):
    flag = "  ⚠ novel-but-shaky" if (p.feasibility or 5) <= 2 else ""
    feas = f"feasibility {p.feasibility}/5" if p.feasibility else "feasibility ?"
    typer.echo(f"[{p.id}] {p.title}   ({feas}){flag}")
    typer.echo(f"    {p.text}")
    typer.echo(f"    next step: {p.next_step}")
    if p.risk:
        typer.echo(f"    risk: {p.risk}")
    typer.echo(f"    cites: {', '.join(p.cites)}")


@app.command()
def propose(
    theme: str = typer.Option(None, "--theme", help="target one theme id"),
    limit: int = typer.Option(5, "--limit"),
):
    from alluvia.engine.propose import Candidate, candidates, generate_proposal
    repo = _repo()
    gen, critic, embedder = build_propose_deps(repo)
    if theme:
        t = repo.get_theme(config.DEFAULT_USER, theme)
        if not t:
            typer.echo(f"no theme {theme}")
            raise typer.Exit(1)
        cands = [Candidate(kind="theme", source_ref=t.id, note_ids=tuple(t.note_ids))]
    else:
        cands = candidates(repo, config.DEFAULT_USER, limit=limit,
                           surface="propose")
    if not cands:
        typer.echo("no fresh material to propose from — run `alluvia refresh`?")
        return
    made = 0
    for cand in cands[:limit]:
        p = generate_proposal(repo, config.DEFAULT_USER, cand, gen, critic, embedder)
        if p:
            _show_proposal(p)
            made += 1
    typer.echo(f"\n{made} proposal(s) pending — rate with `alluvia rate <id> --keep|--dismiss`")


@app.command()
def proposals(all: bool = typer.Option(False, "--all")):
    repo = _repo()
    outcomes = ("pending", "kept", "dismissed", "rejected") if all else ("pending",)
    props = sorted(repo.list_proposals(config.DEFAULT_USER, outcomes=outcomes),
                   key=_feas_sort_key)
    if not props:
        typer.echo("no proposals — run `alluvia propose`")
        return
    for p in props:
        _show_proposal(p)
        if all:
            typer.echo(f"    outcome: {p.outcome}"
                       + (f" ({p.reject_reason})" if p.reject_reason else ""))


@app.command()
def rate(
    proposal_id: str,
    keep: bool = typer.Option(False, "--keep"),
    dismiss: bool = typer.Option(False, "--dismiss"),
    note: str = typer.Option(None, "--note"),
):
    if keep == dismiss:
        raise typer.BadParameter("exactly one of --keep / --dismiss")
    repo = _repo()
    if not repo.get_proposal(config.DEFAULT_USER, proposal_id):
        typer.echo(f"no proposal {proposal_id}")
        raise typer.Exit(1)
    repo.rate_proposal(config.DEFAULT_USER, proposal_id,
                       "kept" if keep else "dismissed", note=note)
    typer.echo(f"{proposal_id} -> {'kept' if keep else 'dismissed'}")


@app.command()
def stats():
    repo = _repo()
    allp = repo.list_proposals(config.DEFAULT_USER,
                               outcomes=("pending", "kept", "dismissed", "rejected"))
    kept = sum(1 for p in allp if p.outcome == "kept")
    dismissed = sum(1 for p in allp if p.outcome == "dismissed")
    rejected = [p for p in allp if p.outcome == "rejected"]
    rated = kept + dismissed
    rate_pct = f"{100 * kept // rated}%" if rated else "n/a"
    typer.echo(f"proposals: {len(allp)} total · {kept} kept · {dismissed} dismissed · "
               f"{len(rejected)} auto-rejected")
    typer.echo(f"hit-rate: {rate_pct} (kept / rated)")
    if rejected:
        from collections import Counter
        mix = Counter(p.reject_reason for p in rejected)
        typer.echo("rejections: " + ", ".join(f"{k}={v}" for k, v in mix.items()))
    themes = repo.list_themes(config.DEFAULT_USER)
    typer.echo(f"corpus: {len(repo.get_notes(config.DEFAULT_USER))} notes · "
               f"{len(themes)} themes · {len(repo.list_links(config.DEFAULT_USER))} links")
    from alluvia.proof import stats_block
    for line in stats_block(repo, config.DEFAULT_USER):
        typer.echo(line)


@app.command()
def connections(
    limit: int = typer.Option(20, "--limit"),
    themes: bool = typer.Option(False, "--themes", help="roll up by theme pair"),
):
    repo = _repo()
    links = repo.list_links(config.DEFAULT_USER, limit=limit)
    if not links:
        typer.echo("no connections yet — run `alluvia refresh`")
        return
    if themes:
        from collections import Counter
        pairs: Counter = Counter()
        for l in links:
            pairs[tuple(sorted([l.from_theme_id or "?", l.to_theme_id or "?"]))] += 1
        for (a, b), n in pairs.most_common():
            typer.echo(f"{a} ↔ {b}   ({n} bridge{'s' if n != 1 else ''})")
        return
    notes = {n.id: n for n in repo.get_notes(config.DEFAULT_USER)}
    engine = build_engine(repo)

    def _tag(n):
        if n is None:
            return ""
        src = n.session_id.split(":", 1)[0]
        date = f" · {n.created_at.date()}" if n.created_at else ""
        return f"  [{src}{date}]"

    for l in links:
        a = notes.get(l.from_note_id)
        b = notes.get(l.to_note_id)
        why = engine.explain(config.DEFAULT_USER, l)
        typer.echo(f"🔗 {a.text if a else l.from_note_id}{_tag(a)}")
        typer.echo(f"   ↔ {b.text if b else l.to_note_id}{_tag(b)}")
        if why:
            typer.echo(f"   why: {why}")


@app.command()
def unfinished(include_dormant: bool = typer.Option(False, "--include-dormant")):
    repo = _repo()
    themes = build_engine(repo).unfinished(config.DEFAULT_USER, include_dormant=include_dormant)
    if not themes:
        all_themes = repo.list_themes(config.DEFAULT_USER)
        if all_themes and all(t.status == "unknown" for t in all_themes):
            # the truthful message: the classifier never ran, not "all done"
            typer.echo("every theme's status is still 'unknown' — the status "
                       "classifier hasn't completed. re-run `alluvia refresh` "
                       "when your provider has headroom")
        else:
            typer.echo("no unfinished threads — run `alluvia refresh`")
        _maybe_degraded_hint(repo)
        return
    for t in themes:
        span = ""
        if t.first_seen and t.last_seen:
            span = f"{(t.last_seen - t.first_seen).days}d"
        last = t.last_seen.date() if t.last_seen else "?"
        typer.echo(f"🧵 {t.label}   {t.status} · {t.session_count} sessions/{span} · last {last}")
        typer.echo(f"   {t.summary}")
    _maybe_degraded_hint(repo)


@app.command()
def init():
    """First-run onboarding: detect sources, configure provider, first ingest."""
    import glob as _glob
    from alluvia.platform import claude_code_root, fork_roots

    typer.echo("alluvia init — local-first setup\n")
    typer.echo("Detected sources:")
    detections: list[tuple[str, str]] = []
    cc = config.source_root("claude-code") or claude_code_root()
    if os.path.isdir(cc):
        n = len(_glob.glob(os.path.join(cc, "**", "*.jsonl"), recursive=True))
        typer.echo(f"  claude-code: {n} session file(s) at {cc}")
        detections.append(("claude-code", cc))
    for flavor, app_name in (("cursor", "Cursor"), ("windsurf", "Windsurf"),
                             ("antigravity", "Antigravity")):
        roots = ((config.source_root(flavor),) if config.source_root(flavor)
                 else fork_roots(app_name))
        roots = tuple(r for r in roots if r and os.path.isdir(r))
        if roots:
            typer.echo(f"  {flavor}: {roots[0]}")
            detections.append((flavor, roots[0]))
    if not detections:
        typer.echo("  (none found — you can still ingest with --source/--path)")

    typer.echo("\nLLM provider (distill/label/propose calls only; embeddings stay local):")
    provider = typer.prompt("  provider [groq/openai/anthropic]", default="groq")
    key = typer.prompt(f"  {provider} API key", hide_input=True, default="")
    cfg: dict = {"llm": {"provider": provider}}
    if key:
        cfg["keys"] = {provider: key}
    path = config.write_config(cfg)
    typer.echo(f"config written: {path} (0600)")

    if detections and typer.confirm("\nIngest detected sources now?", default=False):
        for source, root in detections:
            typer.echo(f"— ingesting {source}…")
            _do_ingest(source, root)
        if typer.confirm("Run first refresh now? (LLM calls — free tiers pace slowly)",
                         default=False):
            from alluvia.progress import make_reporter
            repo = _repo()
            rep = make_reporter()
            try:
                build_engine(repo, reporter=rep).refresh(config.DEFAULT_USER,
                                                         reporter=rep)
            finally:
                rep.close()
            typer.echo(f"themes: {len(repo.list_themes(config.DEFAULT_USER))}")

    typer.echo("\nNext steps:")
    typer.echo("  alluvia refresh && alluvia themes")
    typer.echo("  Claude Code (hooks + MCP in one install), inside a session:")
    typer.echo("    /plugin marketplace add dylanp12/alluvia")
    typer.echo("    /plugin install alluvia@alluvia")
    typer.echo("  other MCP clients: alluvia mcp   (stdio server)")
    typer.echo("  shell: [ -f ~/.alluvia/digest-pending ] && echo 'alluvia: digest waiting'")
    typer.echo("  cron:  0 9 * * MON alluvia digest run --if-due")


def _do_ingest(source: str, path: str) -> None:
    repo = _repo()
    if source == "claude-code":
        adapter = ClaudeCodeAdapter(path, user_id=config.DEFAULT_USER)
    else:
        from alluvia.ingest.vscode_fork import VSCodeForkAdapter
        adapter = VSCodeForkAdapter(source, root=path, user_id=config.DEFAULT_USER)
    total = new = 0
    for s in adapter.read():
        total += 1
        if repo.upsert_session(s):
            new += 1
    typer.echo(f"  {source}: {total} session(s), {new} new/changed")


@app.command()
def handoff(
    kept: bool = typer.Option(False, "--kept", help="The context shown at session start was useful."),
    noise: bool = typer.Option(False, "--noise", help="It was noise."),
    note: str = typer.Option(None, "--note", help="Apply the verdict to one shown note id."),
    event: str = typer.Option(None, "--event", help="A specific handoff event id (default: latest for this repo)."),
):
    """Tell alluvia whether the block it injected at session start earned its
    place. Verdicts are yours, kept for good, and shown in `alluvia stats`."""
    from alluvia.proof import record_verdict_for
    from alluvia.projects import project_root
    if kept == noise:
        raise typer.BadParameter("say --kept or --noise")
    verdict = "kept" if kept else "noise"
    root = project_root(os.getcwd())
    eid = record_verdict_for(_repo(), config.DEFAULT_USER, root, verdict, note_id=note, event_id=event)
    if eid is None:
        typer.echo("no handoff has been delivered for this repo yet — nothing to rate")
        raise typer.Exit(1)
    typer.echo(f"{verdict}: recorded against {eid}" + (f" for {note}" if note else ""))


memory_app = typer.Typer(help="Portable memory: export/import your distilled notes and "
                              "judgments as one file. Never raw sessions.")
app.add_typer(memory_app, name="memory")


@memory_app.command("export")
def memory_export(
    path: str = typer.Argument(..., help="Destination .jsonl file."),
    project: str = typer.Option(None, "--project",
                                help="Only this repository ('.' = the git root of the cwd)."),
    project_relative: bool = typer.Option(False, "--project-relative",
                                          help="Write the repository as 'this checkout' so an "
                                               "importer binds it to its own root."),
):
    """Write your distilled notes, session metadata, suppressions, and mutes to
    one file you can move with anything you own. No raw messages, ever."""
    import json as _json
    from alluvia.memory_bundle import export_bundle
    from alluvia.projects import project_root
    repo = _repo()
    scope = project_root(os.getcwd()) if project == "." else project
    recs = list(export_bundle(repo, config.DEFAULT_USER, project=scope,
                              project_relative=project_relative))
    with open(path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(_json.dumps(r, ensure_ascii=False) + "\n")
    n_s = sum(1 for r in recs if r["kind"] == "session")
    n_n = sum(1 for r in recs if r["kind"] == "note")
    n_j = sum(1 for r in recs if r["kind"] in ("suppressed", "muted"))
    if not n_s:
        typer.echo(f"nothing known for that repo — header only → {path}")
        return
    typer.echo(f"exported {n_s} session{'s' if n_s != 1 else ''} · {n_n} note{'s' if n_n != 1 else ''}"
               f" · {n_j} judgments → {path}")
    typer.echo("  (distilled notes only; raw conversations never leave this machine)")


@memory_app.command("import")
def memory_import(path: str = typer.Argument(..., help="A file written by `alluvia memory export`.")):
    """Merge a memory file into this machine's store. Idempotent: notes already
    here are skipped, this machine's own sessions are never overwritten."""
    import json as _json
    from alluvia.memory_bundle import import_bundle
    if not os.path.isfile(path):
        typer.echo(f"no such file: {path}")
        raise typer.Exit(1)
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(_json.loads(line))
                except ValueError:
                    records.append({"kind": "malformed"})
    out = import_bundle(_repo(), config.DEFAULT_USER, records, embedder=_recall_embedder())
    typer.echo(f"imported: sessions +{out['sessions_added']} · notes +{out['notes_added']} "
               f"(already present: {out['notes_present']}) · judgments +{out['judgments_added']}"
               + (f" · skipped {out['skipped']} malformed" if out["skipped"] else ""))
    if out["notes_added"]:
        typer.echo("  recall sees them now; `alluvia refresh` folds them into themes")


repo_app = typer.Typer(help="Let a repository carry its own distilled memory (.alluvia/memory.jsonl).")
app.add_typer(repo_app, name="repo")


def _cwd_root() -> str:
    from alluvia.projects import project_root
    return project_root(os.getcwd())


@repo_app.command("share")
def repo_share(state: str = typer.Argument(..., help="on | off")):
    """on: write this repository's distilled notes to .alluvia/memory.jsonl and keep
    it current after every session (commit the directory to share it — with your
    other machines, or with teammates). off: remove the file and the flag.
    Notes only; raw conversations never enter the repository."""
    from alluvia.repo_share import set_shared, share_file, write_share
    root = _cwd_root()
    if state == "on":
        set_shared(root, True)
        n = write_share(_repo(), config.DEFAULT_USER, root)
        typer.echo(f"sharing on: {share_file(root)} ({n} note{'s' if n != 1 else ''})")
        typer.echo("  commit .alluvia/ to carry this repo's memory with the checkout; "
                   "it is rewritten after every session and refresh")
    elif state == "off":
        set_shared(root, False)
        typer.echo("sharing off: .alluvia/memory.jsonl removed")
    else:
        raise typer.BadParameter("expected 'on' or 'off'")


@repo_app.command("status")
def repo_status():
    """Is this repository sharing its memory, and how much is in the file?"""
    import datetime as _dt
    from alluvia.repo_share import is_shared, share_file
    root = _cwd_root()
    f = share_file(root)
    if not is_shared(root):
        typer.echo(f"sharing off for {root}  (alluvia repo share on)")
        return
    notes = sum(1 for l in f.read_text(encoding="utf-8").splitlines()
                if l.strip().startswith('{"kind": "note"')) if f.exists() else 0
    when = (_dt.datetime.fromtimestamp(f.stat().st_mtime, _dt.timezone.utc).isoformat(timespec="minutes")
            if f.exists() else "never")
    typer.echo(f"sharing on for {root}: {notes} note{'s' if notes != 1 else ''} in {f} · written {when}")


@repo_app.command("export")
def repo_export():
    """Rewrite .alluvia/memory.jsonl now (normally automatic)."""
    from alluvia.repo_share import is_shared, write_share
    root = _cwd_root()
    if not is_shared(root):
        typer.echo("sharing is off for this repository — `alluvia repo share on` first")
        raise typer.Exit(1)
    n = write_share(_repo(), config.DEFAULT_USER, root)
    typer.echo(f"written: {n} note{'s' if n != 1 else ''}")


hook_app = typer.Typer(help="Claude Code hook handlers (wired by the alluvia plugin).")
app.add_typer(hook_app, name="hook")


def _hook_log(msg: str) -> None:
    import datetime as _dt
    try:
        d = config.handoff_dir()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "hooks.log"), "a", encoding="utf-8") as f:
            f.write(f"{_dt.datetime.now(_dt.timezone.utc).isoformat()} {msg}\n")
    except Exception:
        pass


def _run_hook(event: str) -> None:
    """Never fail the user's session: any error goes to hooks.log, exit 0."""
    import json as _json
    import sys as _sys
    from alluvia.hooks import parse_payload, run_capture, run_session_start
    payload = parse_payload(_sys.stdin.read())
    try:
        repo = _repo()
        if event == "session-start":
            out = run_session_start(payload, repo)
            if out:
                typer.echo(_json.dumps(out))
            return
        stats = run_capture(payload, repo, build_engine(repo))
        _hook_log(f"{event}: {stats}")
    except Exception as e:                      # noqa: BLE001 — by contract
        _hook_log(f"{event}: error: {e!r} payload_keys={sorted(payload)} "
                  f"transcript={payload.get('transcript_path')}")


@hook_app.command("session-start")
def hook_session_start():
    """Inject what alluvia knows about this repo (reads the cached handoff)."""
    _run_hook("session-start")


@hook_app.command("session-end")
def hook_session_end():
    """Ingest and distill the finished session; rebuild this repo's handoff."""
    _run_hook("session-end")


@hook_app.command("pre-compact")
def hook_pre_compact():
    """Capture the live session before compaction so nothing is lost."""
    _run_hook("pre-compact")


digest_app = typer.Typer(help="Proactive digest: run/show/dismiss/keep")
app.add_typer(digest_app, name="digest")

cloud_app = typer.Typer(help="Sync your derived memory to Alluvia Cloud (opt-in).")
app.add_typer(cloud_app, name="cloud")


@cloud_app.command("sync")
def cloud_sync(yes: bool = typer.Option(False, "--yes", "-y",
                                        help="Skip the confirm prompt.")):
    """Upload your derived memory to your Alluvia Cloud org. Shows exactly what
    will leave the machine first; texts are secret-scrubbed, raw transcripts
    stay local unless a source is set to 'raw'."""
    from alluvia.cloudclient import load_session, push_bundle, SyncError
    from alluvia.cloudsync.bundle import build_bundle, preview
    from alluvia.cloudsync.policy import load_policy
    sess = load_session()
    if not sess:
        typer.echo("not signed in — run `alluvia cloud login` first")
        raise typer.Exit(1)
    bundle = build_bundle(_repo(), config.DEFAULT_USER, load_policy())
    typer.echo(preview(bundle))
    typer.echo(f"\ndestination: {sess['url']}")
    if not yes and not typer.confirm("upload this?", default=False):
        typer.echo("cancelled — nothing left the machine")
        raise typer.Exit(0)
    from alluvia.cloudclient import refresh_session, save_session
    try:
        result = push_bundle(sess["url"], sess["token"], bundle)
    except SyncError as e:
        if sess.get("refresh"):                 # token likely expired — refresh once
            try:
                tok, ref = refresh_session(sess["url"], sess["refresh"])
                save_session(sess["url"], tok, ref)
                result = push_bundle(sess["url"], tok, bundle)
            except SyncError as e2:
                typer.echo(f"sync failed: {e2}")
                raise typer.Exit(1)
        else:
            typer.echo(f"sync failed: {e}")
            raise typer.Exit(1)
    typer.echo(f"synced: {result}")
    from alluvia import cloud_memory
    mem = cloud_memory.push(_repo(), config.DEFAULT_USER)
    if mem.get("ok"):
        typer.echo(f"memory: {_plural(mem.get('notes', 0), 'note')} synced")
    elif mem.get("error"):
        typer.echo(f"memory sync: {mem['error']} (retries on the next refresh)")


@cloud_app.command("login")
def cloud_login(
    url: str = typer.Option(None, "--url", help="Alluvia Cloud API URL."),
    token: str = typer.Option(None, "--token",
                              help="Set a token directly (CI/self-hosted); skips the browser."),
    no_browser: bool = typer.Option(False, "--no-browser",
                                    help="Print the sign-in URL instead of opening a browser."),
):
    """Sign in to Alluvia Cloud. Opens your browser to authenticate; the token
    is returned to a one-shot local listener. --token sets one directly."""
    from alluvia.cloudclient import DEFAULT_CLOUD_URL, loopback_login, save_session, SyncError
    url = url or os.environ.get("ALLUVIA_CLOUD_URL") or DEFAULT_CLOUD_URL
    if token:
        save_session(url, token)
    else:
        typer.echo("opening your browser to sign in…")
        try:
            access, refresh = loopback_login(url, open_browser=not no_browser)
        except SyncError as e:
            typer.echo(f"login failed: {e}")
            raise typer.Exit(1)
        save_session(url, access, refresh)
    typer.echo(f"signed in · {url.rstrip('/')}")
    # the one command to remember has been run; from here memory follows you
    from alluvia import cloud_memory
    res = cloud_memory.sync(_repo(), config.DEFAULT_USER)
    if res.get("ok"):
        pulled, pushed = res.get("pull") or {}, res.get("push") or {}
        typer.echo(f"memory: {_plural(pulled.get('notes_added', 0), 'note')} received · "
                   f"{_plural(pushed.get('notes', 0), 'note')} sent")
        typer.echo("refresh falls through to managed distillation when your provider "
                   "is limited; memory syncs after every session (alluvia cloud status)")
    else:
        err = (res.get("pull") or {}).get("error") or (res.get("push") or {}).get("error") or "skipped"
        if "timed out" in err:
            typer.echo("memory sync: the server is still working through your first sync; "
                       "check `alluvia cloud status` in a minute")
        else:
            typer.echo(f"memory sync: {err} (retries on the next refresh)")


def _ago(iso: str) -> str:
    from datetime import datetime, timezone
    try:
        secs = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return "at an unknown time"
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{int(secs // 60)} min ago"
    if secs < 172800:
        return f"{int(secs // 3600)} h ago"
    return f"{int(secs // 86400)} d ago"


@cloud_app.command("status")
def cloud_status():
    """Signed in as what, on which plan, how much managed distillation is left
    this month, and when memory last synced."""
    import json as _json
    from alluvia import cloudclient
    from alluvia.cloud_memory import LAST_SYNC, MANAGED_DOWN
    sess = cloudclient.load_session()
    if not sess:
        typer.echo("not signed in to Alluvia Cloud")
        return
    typer.echo(f"signed in · {sess['url']}")
    try:
        b = cloudclient.with_refresh(sess, lambda tok: cloudclient.get_billing(sess["url"], tok))
    except cloudclient.SyncError as e:
        if e.code == 401:
            typer.echo("your sign-in expired: run `alluvia cloud login`")
        else:
            typer.echo(f"plan and usage: unavailable right now ({e})")
    else:
        cloudclient.update_session(plan=str(b.get("plan") or "free"))
        plan = str(b.get("plan") or "free").capitalize()
        usage = b.get("usage") or {}
        if usage.get("budget") is not None:
            typer.echo(f"{plan} · managed distillation ${float(usage.get('spend') or 0):.2f} "
                       f"of ${float(usage['budget']):.2f} this month")
        else:
            typer.echo(f"{plan} · managed distillation not used yet")
    repo = _repo()
    down = repo.get_meta(MANAGED_DOWN)
    if down:
        try:
            d = _json.loads(down)
            typer.echo(f"managed distillation: unavailable ({d.get('reason')}) since "
                       f"{str(d.get('at', ''))[11:16]} UTC; retries after "
                       f"{str(d.get('until', ''))[11:16]} UTC. This is on our side, not yours")
        except (ValueError, TypeError):
            pass
    raw = repo.get_meta(LAST_SYNC)
    if raw:
        try:
            last = _json.loads(raw)
            typer.echo(f"memory synced {_plural(int(last.get('notes_pushed', 0)), 'note')} · "
                       f"{_ago(last.get('at', ''))}")
            return
        except (ValueError, TypeError):
            pass
    typer.echo("memory: not synced yet (alluvia refresh)")


@cloud_app.command("logout")
def cloud_logout():
    from alluvia.cloudclient import clear_session
    clear_session()
    typer.echo("signed out")


def _pending_flag() -> str:
    return os.environ.get("ALLUVIA_PENDING_FLAG",
                          os.path.expanduser("~/.alluvia/digest-pending"))


@digest_app.command("run")
def digest_run(
    if_due: bool = typer.Option(False, "--if-due"),
    force: bool = typer.Option(False, "--force"),
):
    from datetime import datetime, timezone
    from alluvia.engine.digest import due, generate
    repo = _repo()
    now = datetime.now(timezone.utc)
    days = config.digest_days()
    if if_due and not force and not due(repo, config.DEFAULT_USER, now, days):
        return                                              # silent: not due
    class _Deps:                                            # lazy, like MCP's SiftDeps
        repo_ = repo
        @property
        def embedder(self):
            from alluvia.engine.embed import FastEmbedEmbedder
            return FastEmbedEmbedder()
        @property
        def gen_llm(self):
            from alluvia.llm.client import make_llm
            from alluvia.store.repo import LLMHealthStore
            return make_llm(role="propose", health=LLMHealthStore(repo))
        @property
        def critic_llm(self):
            from alluvia.llm.client import make_llm
            from alluvia.store.repo import LLMHealthStore
            return make_llm(role="status", health=LLMHealthStore(repo))
    did, items = generate(repo, _Deps(), config.DEFAULT_USER, now)
    if not items:
        typer.echo("(silence — nothing cleared the bar)")
        return
    flag = _pending_flag()
    os.makedirs(os.path.dirname(flag), exist_ok=True)
    with open(flag, "w") as f:
        f.write(str(len(items)))
    _print_digest(repo, did)


def _print_digest(repo, digest_id):
    for it in repo.digest_items(config.DEFAULT_USER, digest_id):
        mark = "" if it["outcome"] == "shown" else f"  [{it['outcome']}]"
        typer.echo(f"{it['n']}. {it['snapshot']}{mark}")
    typer.echo("\nact: alluvia digest dismiss <n> | alluvia digest keep <n>")


@digest_app.command("show")
def digest_show():
    repo = _repo()
    last = repo.latest_digest(config.DEFAULT_USER)
    if not last:
        typer.echo("no digest yet — run `alluvia digest run --force`")
        return
    typer.echo(f"digest #{last[0]} · {last[1][:10]} · {last[2]} item(s)")
    _print_digest(repo, last[0])
    flag = _pending_flag()
    if os.path.exists(flag):
        os.remove(flag)


def _act_on_item(n: int, outcome: str):
    repo = _repo()
    last = repo.latest_digest(config.DEFAULT_USER)
    if not last:
        typer.echo("no digest yet")
        raise typer.Exit(1)
    item = repo.set_digest_item_outcome(config.DEFAULT_USER, last[0], n, outcome)
    if item is None:
        typer.echo(f"no item {n}")
        raise typer.Exit(1)
    if item["kind"] == "proposal" and item["ref"]:
        repo.rate_proposal(config.DEFAULT_USER, item["ref"],
                           "kept" if outcome == "kept" else "dismissed", via="digest")
    typer.echo(f"item {n} -> {outcome}")


@digest_app.command("dismiss")
def digest_dismiss(n: int):
    _act_on_item(n, "dismissed")


@digest_app.command("keep")
def digest_keep(n: int):
    _act_on_item(n, "kept")


def _sigterm(signum, frame):
    raise KeyboardInterrupt               # reuse the clean Ctrl-C shutdown path


@app.command()
def serve(
    port: int = typer.Option(None, "--port",
                             help="Exact port (default: 8177, walking upward if busy)"),
    open_browser: bool = typer.Option(False, "--open"),
):
    """Local dashboard: visualizations of your idea-map at http://localhost:<port>."""
    import signal
    from alluvia.web import looks_like_alluvia, pick_port, serve as make_server
    explicit = port is not None
    want = port if explicit else 8177
    if looks_like_alluvia(want):
        url = f"http://127.0.0.1:{want}"
        typer.echo(f"dashboard already running at {url}")
        if open_browser:
            import webbrowser
            webbrowser.open(url)
        return
    if not explicit:
        want = pick_port(want)
    try:
        server = make_server(_repo(), config.DEFAULT_USER, port=want)
    except OSError as e:
        typer.echo(f"cannot bind port {want}: {e}")
        raise typer.Exit(1)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    typer.echo(f"alluvia dashboard: {url}  (Ctrl-C to stop)")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    signal.signal(signal.SIGTERM, _sigterm)   # docker/systemd stop == Ctrl-C
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


def _recall_embedder():
    from alluvia.engine.embed import FastEmbedEmbedder
    return FastEmbedEmbedder()


@app.command()
def demo(clean: bool = typer.Option(False, "--clean",
                                    help="Remove the demo store.")):
    """See every lens in seconds on a tiny synthetic corpus — no API key,
    no LLM calls, and never anywhere near your real store."""
    import os as _os
    from alluvia.demo_corpus import seed
    from alluvia.store.db import connect, init_schema
    demo_db = _os.path.expanduser("~/.alluvia/demo.db")
    if clean:
        for suffix in ("", "-wal", "-shm"):
            try:
                _os.remove(demo_db + suffix)
            except OSError:
                pass
        typer.echo("demo store removed")
        return
    conn = connect(demo_db)
    init_schema(conn, embed_dim=384)
    repo = Repo(conn)
    seed(repo)
    notes = {n.id: n for n in repo.get_notes(config.DEFAULT_USER)}
    typer.echo("— themes (your thinking, clustered) —")
    for t in repo.list_themes(config.DEFAULT_USER):
        typer.echo(f"\u2022 {t.label}  [{t.status}] \u00b7 {t.session_count} sessions/"
                   f"{t.source_count} sources")
    typer.echo("\n— connections (bridges across tools and months) —")
    for l in repo.list_links(config.DEFAULT_USER, limit=2):
        a, b = notes[l.from_note_id], notes[l.to_note_id]
        typer.echo(f"\U0001f517 {a.text}")
        typer.echo(f"   \u2194 {b.text}")
        typer.echo(f"   why: {l.why}")
    typer.echo("\n— unfinished (threads you keep circling) —")
    for t in repo.list_themes(config.DEFAULT_USER):
        if t.status == "open":
            typer.echo(f"\U0001f9f5 {t.label} \u00b7 open across "
                       f"{t.session_count} sessions")
    typer.echo("\n— proposal (grounded next step, awaiting YOUR judgment) —")
    for p in repo.list_proposals(config.DEFAULT_USER, outcomes=("pending",)):
        typer.echo(f"[{p.id}] {p.title}  (feasibility {p.feasibility}/5)")
        typer.echo(f"    {p.text}")
        typer.echo(f"    cites: {', '.join(p.cites)}")
    typer.echo("\nthis is synthetic data in its own store (~/.alluvia/demo.db).")
    typer.echo(f"dashboard:  ALLUVIA_DB={demo_db} alluvia serve --open")
    typer.echo("your turn:  alluvia init   (your real history, on your machine)")
    typer.echo("remove:     alluvia demo --clean")
    conn.close()   # Windows won't let `demo --clean` delete an open file


@app.command()
def recall(
    query: str,
    handoff: bool = typer.Option(False, "--handoff",
                                 help="Emit a paste-ready context block for your current assistant."),
    json_out: bool = typer.Option(False, "--json"),
    limit: int = typer.Option(5, "--limit"),
    here: bool = typer.Option(False, "--here",
                              help="Only this repository's sessions (the git root of the cwd)."),
    include_weak: bool = typer.Option(False, "--include-weak",
                                      help="Also show matches that have neither a strong "
                                           "semantic score nor an exact-term hit."),
):
    """The front door: what did I already figure out about this?
    Cited, ranked, retrieval-only — zero LLM spend. Says "no record" when
    nothing in your history clears the bar."""
    import json as _json
    import os as _os
    from dataclasses import asdict
    from alluvia.projects import project_root
    from alluvia.recall import build_handoff, recall as _recall, recall_warnings
    repo = _repo()
    git_root = "." if _os.path.isdir(".git") else None
    scope = project_root(_os.getcwd()) if here else None
    hits = _recall(repo, _recall_embedder(), config.DEFAULT_USER, query,
                   limit=limit, git_root=git_root, project=scope,
                   include_weak=include_weak)
    repo.bump_counter(config.DEFAULT_USER, "recall_answered" if hits else "recall_refused")
    warnings = recall_warnings(repo)
    if json_out:
        typer.echo(_json.dumps({"query": query, "scope": scope,
                                "hits": [asdict(h) for h in hits],
                                "warnings": warnings}, indent=2))
        return
    if handoff:
        typer.echo(build_handoff(query, hits))
        for w in warnings:
            typer.echo(f"\u26a0 {w}")
        return
    if not hits:
        n = len(repo.get_notes(config.DEFAULT_USER))
        where = " in this repo" if scope else ""
        typer.echo(f"no record of that{where} \u2014 {n} notes searched, none clear the bar")
        typer.echo("  (add --include-weak to see near misses; `alluvia refresh` if "
                   "sessions are still pending)")
        for w in warnings:
            typer.echo(f"\u26a0 {w}")
        return
    for i, h in enumerate(hits, 1):
        status = f"  [{h.status}]" if h.status else ""
        span = f"  ({h.date_range})" if h.date_range else ""
        conf = "" if h.confidence == "strong" else f"  ({h.confidence})"
        typer.echo(f"{i}. {h.title}{status}{span}{conf}")
        typer.echo(f"   {h.summary}")
        typer.echo(f"   why: {h.why}")
        if h.receipts:
            typer.echo(f'   receipt: "{h.receipts[0]["quote"][:200]}"')
        if h.git_ref:
            typer.echo(f"   {h.git_ref}")
        typer.echo(f"   sources: {'; '.join(h.sources)}")
        typer.echo(f"   cites: {', '.join(h.cites[:4])}  \u00b7  wrong? alluvia forget <note-id>")
    for w in warnings:
        typer.echo(f"\u26a0 {w}")
    typer.echo("\ntip: --handoff emits a block to paste into your assistant")


@app.command()
def status(json_out: bool = typer.Option(False, "--json")):
    """What alluvia keeps on this machine: paths, sizes, data classes,
    and which processes are live right now."""
    import json as _json
    from alluvia.inspect import storage_report
    rep = storage_report(_repo())
    if json_out:
        typer.echo(_json.dumps(rep, indent=2))
        return

    def _size(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024 or unit == "GB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n / 1:.1f} {unit}"
            n /= 1024
    typer.echo("paths:")
    for name, e in rep["paths"].items():
        mark = "" if e["exists"] else "  (absent)"
        size = f"  {_size(e['bytes'])}" if e["exists"] else ""
        mode = f"  mode {e['mode']}" if e.get("mode") else ""
        typer.echo(f"  {name:13} {e['path']}{size}{mode}{mark}")
    dc = rep["data_classes"]
    typer.echo("store by data class:")
    typer.echo(f"  raw        {dc['raw']['rows']:6} rows  {_size(dc['raw']['content_bytes'])}"
               f"   (source of truth — never mutated)")
    typer.echo(f"  derived    {dc['derived']['rows']:6} rows  {_size(dc['derived']['content_bytes'])}"
               f"   (rebuildable from raw)")
    typer.echo(f"  judgments  {dc['judgments']['rows']:6} rows  {_size(dc['judgments']['content_bytes'])}"
               f"   (yours — never regenerated)")
    cov = rep["coverage"]
    if cov["sessions"]:
        pct = 100 * cov["distilled"] // cov["sessions"]
        tail = f" · {cov['pending']} pending → alluvia refresh" if cov["pending"] else ""
        typer.echo(f"  distilled   {cov['distilled']}/{cov['sessions']} sessions ({pct}%){tail}")
    live = rep["live"]
    typer.echo("live:")
    typer.echo(f"  refresh:   {'running (pid ' + str(live['refresh_lock_pid']) + ')' if live['refresh_lock_pid'] else 'not running'}")
    typer.echo(f"  dashboard: {'http://127.0.0.1:' + str(live['dashboard_port']) if live['dashboard_port'] else 'not running'}")
    from alluvia.resources import snapshot as _snapshot
    procs = _snapshot(sample_s=0.2)
    if procs:
        typer.echo("processes:")
        for p in procs:
            typer.echo(f"  pid {p['pid']} {p['role']}: {p['cpu_pct']}% cpu \u00b7 "
                       f"{_fmt_bytes(p['rss_bytes'])} ram")
    typer.echo("nothing leaves this machine except LLM calls under your key "
               "(secret-scrubbed) — see README \"What leaves your machine\"")


_DOCTOR_ICONS = {"ok": "\u2713", "repaired": "\U0001f527", "warn": "\u26a0",
                 "fail": "\u2717"}


@app.command()
def doctor(
    check: bool = typer.Option(False, "--check",
                               help="Report only — apply no repairs."),
    live: bool = typer.Option(False, "--live",
                              help="Also make one tiny LLM call to prove the key works."),
    rebuild_derived: bool = typer.Option(False, "--rebuild-derived",
                                         help="Discard ALL derived data for a clean rebuild "
                                              "(raw + judgments survive)."),
):
    """Diagnose the installation and repair what is safe to repair.
    Safe repairs never touch raw sessions or your judgments."""
    from alluvia.doctor import rebuild_derived as _rebuild, run_doctor
    repo = _repo()
    if rebuild_derived:
        typer.echo("this discards notes/themes/links/caches so the next refresh "
                   "rebuilds them from raw — it will RE-SPEND LLM budget.")
        typer.echo("raw sessions, your ratings/digests/mutes, and config survive.")
        if not typer.confirm("proceed?", default=False):
            raise typer.Exit(1)
        counts = _rebuild(repo)
        dropped = " · ".join(f"{k}: {v}" for k, v in counts.items() if v)
        typer.echo(f"derived data cleared ({dropped or 'already empty'})")
        typer.echo("run `alluvia refresh` to rebuild the map")
        return
    llm = None
    if live:
        from alluvia.llm.client import make_llm
        from alluvia.store.repo import LLMHealthStore
        llm = make_llm(role="status", health=LLMHealthStore(repo))
    findings = run_doctor(repo, check_only=check, live=live, llm=llm)
    for f in findings:
        tag = "repaired \u2014 " if f.status == "repaired" else ""
        line = f"{_DOCTOR_ICONS[f.status]} {f.name}: {tag}{f.detail}"
        if f.remedy:
            line += f"  \u2192 {f.remedy}"
        typer.echo(line)
    failed = any(f.status == "fail" for f in findings)
    would_repair = check and any(f.repairable for f in findings)
    if would_repair:
        typer.echo("run `alluvia doctor` (without --check) to apply the repairs")
    if failed or would_repair:
        raise typer.Exit(1)


@app.command()
def top(
    watch: float = typer.Option(None, "--watch",
                                help="Refresh every N seconds (Ctrl-C to stop)."),
):
    """Live resource usage of running alluvia processes: CPU, RAM, disk I/O
    — plus alluvia's own network accounting (LLM calls are its only traffic)."""
    import time as _time
    from alluvia.resources import llm_traffic, machine_context, snapshot
    repo = _repo()

    def render():
        ctx = machine_context()
        typer.echo(f"machine: {ctx['cpu_count']} cpus \u00b7 {ctx['cpu_pct']:.0f}% busy \u00b7 "
                   f"mem {ctx['mem_used_pct']:.0f}% of {_fmt_bytes(ctx['mem_total_bytes'])}")
        rows = snapshot()
        if rows:
            typer.echo(f"{'pid':>7}  {'role':<10} {'cpu%':>6} {'mem':>10} "
                       f"{'disk r':>10} {'disk w':>10} {'uptime':>8}")
            for r in rows:
                up = f"{r['uptime_s'] // 3600}h{(r['uptime_s'] % 3600) // 60:02d}m" \
                    if r["uptime_s"] >= 3600 else f"{r['uptime_s'] // 60}m{r['uptime_s'] % 60:02d}s"
                typer.echo(f"{r['pid']:>7}  {r['role']:<10} {r['cpu_pct']:>6} "
                           f"{_fmt_bytes(r['rss_bytes']):>10} "
                           f"{_fmt_bytes(r['disk_read_bytes']):>10} "
                           f"{_fmt_bytes(r['disk_write_bytes']):>10} {up:>8}")
        else:
            typer.echo("no alluvia processes running right now")
        typer.echo("llm traffic (the only network alluvia uses):")
        traffic = llm_traffic(repo)
        if traffic:
            for t in traffic:
                typer.echo(f"  {t['provider']}/{t['model']}: {t['calls']} calls \u00b7 "
                           f"{_fmt_bytes(t['sent_bytes'])} sent \u00b7 "
                           f"{_fmt_bytes(t['recv_bytes'])} received")
        else:
            typer.echo("  none recorded yet")

    if watch is None:
        render()
        return
    try:
        while True:
            typer.echo("\x1b[2J\x1b[H", nl=False)
            render()
            _time.sleep(max(watch, 0.5))
    except KeyboardInterrupt:
        pass


@app.command()
def mcp():
    """Serve alluvia's lenses as MCP tools over stdio (register in Claude Code/Cursor)."""
    from alluvia.mcp_server import serve
    serve()


if __name__ == "__main__":
    app()
