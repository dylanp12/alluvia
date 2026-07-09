from __future__ import annotations
import os
import typer
from alluvia import config
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo
from alluvia.ingest.claude_code import ClaudeCodeAdapter

app = typer.Typer(help="alluvia — mine your cross-harness AI history")

# embeddings dim is fixed once the engine phase lands; 384 = bge-small default.
EMBED_DIM = 384


def _repo() -> Repo:
    conn = connect(config.db_path())
    init_schema(conn, embed_dim=EMBED_DIM)
    return Repo(conn)


def build_engine(repo: Repo):
    from alluvia.engine.engine import Engine
    from alluvia.engine.embed import FastEmbedEmbedder
    from alluvia.llm.client import RoleRouter
    from alluvia.store.repo import LLMHealthStore
    # role-routed models, governed with SQLite-persisted breaker state: a
    # short-lived CLI run respects cooldowns learned by previous runs
    return Engine(repo, FastEmbedEmbedder(),
                  RoleRouter(health=LLMHealthStore(repo)),
                  min_cluster_size=config.min_cluster())


@app.command()
def ingest(
    source: str = typer.Option("claude-code", "--source",
                               help="claude-code | cursor | windsurf | antigravity | chatgpt-export"),
    path: str = typer.Option(None, "--path",
                             help="Root/logs dir (claude-code), fork root override, "
                                  "or export ZIP/dir (chatgpt-export)"),
):
    repo = _repo()
    if source == "claude-code":
        if not path:
            from alluvia.platform import claude_code_root
            path = config.source_root("claude-code") or claude_code_root()
        adapter = ClaudeCodeAdapter(path, user_id=config.DEFAULT_USER)
    elif source in ("cursor", "windsurf", "antigravity"):
        from alluvia.ingest.vscode_fork import VSCodeForkAdapter
        adapter = VSCodeForkAdapter(source, root=path, user_id=config.DEFAULT_USER)
    elif source == "chatgpt-export":
        if not path:
            raise typer.BadParameter("--path to the export ZIP/dir is required")
        from alluvia.ingest.chatgpt_export import ChatGPTExportAdapter
        adapter = ChatGPTExportAdapter(path, user_id=config.DEFAULT_USER)
    else:
        raise typer.BadParameter(f"unknown source: {source}")
    n_new = 0
    total = 0
    for s in adapter.read():
        total += 1
        if repo.upsert_session(s):
            n_new += 1
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


def _echo_refresh_summary(stats: dict) -> None:
    """Per-stage outcome of a refresh — a degraded map must never be
    indistinguishable from a healthy one."""
    d, t = stats.get("distill", {}), stats.get("themes", {})
    if d.get("todo"):
        line = f"distilled: {d.get('ok', 0)}/{d['todo']} sessions"
        extras = [f"{d[k]} {w}" for k, w in
                  (("zero_note", "empty"), ("failed", "failed")) if d.get(k)]
        typer.echo(line + (f" ({', '.join(extras)})" if extras else ""))
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
def refresh():
    repo = _repo()
    stats = build_engine(repo).refresh(config.DEFAULT_USER)
    typer.echo(f"themes: {len(repo.list_themes(config.DEFAULT_USER))}")
    if isinstance(stats, dict):
        _echo_refresh_summary(stats)


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
        cands = candidates(repo, config.DEFAULT_USER, limit=limit)
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
            repo = _repo()
            build_engine(repo).refresh(config.DEFAULT_USER)
            typer.echo(f"themes: {len(repo.list_themes(config.DEFAULT_USER))}")

    typer.echo("\nNext steps:")
    typer.echo("  alluvia refresh && alluvia themes")
    typer.echo("  MCP:   claude mcp add alluvia -- uv run --directory <repo> alluvia mcp")
    typer.echo("  shell: [ -f ~/.alluvia/digest-pending ] && echo 'alluvia: digest waiting'")
    typer.echo("  cron:  0 9 * * MON cd <repo> && uv run alluvia digest run --if-due")


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


digest_app = typer.Typer(help="Proactive digest: run/show/dismiss/keep")
app.add_typer(digest_app, name="digest")


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


@app.command()
def serve(
    port: int = typer.Option(8177, "--port"),
    open_browser: bool = typer.Option(False, "--open"),
):
    """Local dashboard: visualizations of your idea-map at http://localhost:<port>."""
    from alluvia.web import serve as make_server
    server = make_server(_repo(), config.DEFAULT_USER, port=port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    typer.echo(f"alluvia dashboard: {url}  (Ctrl-C to stop)")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


@app.command()
def mcp():
    """Serve alluvia's lenses as MCP tools over stdio (register in Claude Code/Cursor)."""
    from alluvia.mcp_server import serve
    serve()


if __name__ == "__main__":
    app()
