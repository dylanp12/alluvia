<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/alluvia-lockup-dark.svg">
    <img src="assets/alluvia-lockup.svg" alt="alluvia" width="420">
  </picture>
</p>

<p align="center"><em>Pan your AI history for gold.</em></p>

<p align="center">
  <a href="https://github.com/dylanp12/alluvia/actions/workflows/ci.yml"><img src="https://github.com/dylanp12/alluvia/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <a href="https://pypi.org/project/alluvia/"><img src="https://img.shields.io/pypi/v/alluvia?color=9A6B15" alt="pypi"></a>
  <img src="https://img.shields.io/badge/license-MIT-9A6B15" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12+-9A6B15" alt="python">
  <img src="https://img.shields.io/badge/local--first-always-9A6B15" alt="local-first">
</p>

# alluvia

**Your agent remembers this repo, and it will not lie about it.**

Every Claude Code session in a repository starts with what you already decided
there: the decisions and problems from your last session, the loops still
open, earlier decisions, each line naming the session it came from. The same
block comes back after every compaction. When alluvia knows nothing about a
repo, it injects nothing. When you ask a question and there is no record, it
says "no record" instead of inventing one.

Local-first, MIT. Raw conversations never leave your machine.

## Sixty seconds

```bash
uv tool install alluvia && alluvia init          # detect your sources, pick a provider
alluvia refresh                                  # distill what is already on disk (local embeddings)
/plugin marketplace add dylanp12/alluvia          # in Claude Code
/plugin install alluvia@alluvia
```

No plugin yet? `alluvia demo` shows every lens in 30 seconds on synthetic data,
and `alluvia recall "the thing I'm debugging"` answers from your own history.

## What arrives at session start

Real output, from alluvia's own repository, the session after it was built:

```
alluvia · prior context for this repo (alluvia)
last session 2026-09-05 on release/0.6.1:
- [decision] Implement replace-on-full behavior in the store and both engine paths. (session 19b79170)
- [decision] Implement union-on-partial behavior in the store and both engine paths. (session 19b79170)
- [decision] Pull funnel data: site traffic, repo traffic, PyPI installs, and cloud signups (session 19b79170)
1 session in this repo
prior context, not ground truth — verify against the code. more: alluvia recall "<question>" --here · wrong? alluvia forget <note-id>
useful? alluvia handoff --kept · noise? alluvia handoff --noise
```

Captured at session end and before compaction, distilled in bounded windows
that always keep the end of the session (where decisions land), with no
resident process and no model call per tool use. Injection needs an
interactive session; headless `claude -p` runs receive no session-start
context in Claude Code, though the capture hooks still run.

## Memory you can trust

- **Receipts.** Every line names its session; every recall hit carries the
  verbatim quote behind it, string-match verified.
- **Confidence you can read.** A hit is *strong*, *corroborated* by an exact
  term, or hidden as *weak*. A stored bridge never outranks the note that
  actually answers you.
- **Honest refusal.** No record means "no record". A golden query set of
  must-refuse questions runs with the test suite.
- **Correctable.** `alluvia forget <note-id>` suppresses a wrong or stale note
  everywhere, for good, without touching raw sessions.
- **Nothing of yours becomes a note.** Harness-injected content (skill bodies,
  command expansions, compaction summaries) is never treated as your thinking.

## Your history, owned

Claude Code deletes transcripts after 30 days by default. alluvia's notes and
receipts stay, and they are yours to move:

```bash
alluvia memory export ~/memory.jsonl     # distilled notes + judgments, never raw
alluvia memory import ~/memory.jsonl     # on the other machine: idempotent merge
alluvia repo share on                    # opt-in: this repo carries its own memory in .alluvia/
```

With sharing on, a fresh clone or a second machine receives the repository's
handoff on its first session. Committing `.alluvia/` is your act; alluvia
never touches git. Sources: Claude Code, Cursor, Codex CLI, Gemini CLI,
OpenCode, the Cline family, ChatGPT exports, and any tool that writes a
[normalized JSONL](docs/SOURCES.md).

Or remember one command and skip the files:

```bash
alluvia cloud login       # once, on each machine
```

After that, memory follows you: the same never-raw bundle syncs up after
every session and refresh and down before, so a second machine receives
everything on its first refresh. And a refresh never stalls: when your own
provider is rate-limited or you have no key at all, distillation falls
through to Alluvia Cloud's managed gateway under your account's monthly
budget. Cloud Free includes $5 of managed distillation a month; Pro ($25 a
month) raises it to $20. `alluvia cloud status` shows the plan, what is
left this month, and when memory last synced. Never signing in is a
complete product: everything above works forever, locally.

## Proof, not vibes

```
$ alluvia stats
handoffs: 12 delivered · 41 lines · kept 5 · noise 1 · referenced (proxy) 17/41
recall:   38 answered · 9 said no record
forget:   3 notes suppressed
```

`alluvia handoff --kept` or `--noise` records your verdict on what was shown;
the reference count is a labeled proxy (the session's own text used the note's
terms or files). Counts only, never rates dressed up as accuracy.

## Recall: the front door

```bash
$ alluvia recall "refresh token storage in the browser" --handoff
```

`recall` fuses your themes, bridges, and unfinished threads into a few cited
hits. It is retrieval only, **zero LLM spend**, and it has grown up since the
first release:

- **Receipts.** Every hit carries the verbatim quote from the session behind
  it, string-match verified. A fabricated quote never survives.
- **Hybrid search.** Vector search paired with an exact-match channel, so error
  strings, file paths, and `snake_case` identifiers find their note even where
  embeddings go blind (`ECONNREFUSED`, `auth/refresh.py`, `DATABASE_URL`).
- **Time-scoped.** `alluvia recall "the auth fix last tuesday"` searches only
  that window. "last week", "in march", "since march", "3 days ago", "2025" all
  work, and an empty window answers honestly empty instead of surfacing the
  wrong era.
- **Honest refusal.** A golden query set (semantic, exact-match, must-refuse)
  runs with the test suite; retrieval changes must never regress the refusals.
  An empty result says "no record", never a near miss dressed as an answer.
- **Confidence you can read.** A hit is *strong* (semantically close),
  *corroborated* (an exact term matched), or hidden as *weak*; `--include-weak`
  shows the near misses, `--here` limits recall to the repository you are in,
  and a stored bridge never outranks the note that actually answers you.

`--handoff` prints a paste-ready block for whatever assistant you're in right
now:

```
Relevant prior context from alluvia (query: "refresh token storage…"):

1. Auth token lifecycle [open]: refresh races and rotation.
   why: 2 of your prior notes match; thread status: open
   sources: claude-code · 2025-04-18; chatgpt-export · 2025-11-02

Treat this as prior context, not ground truth. Verify against the current code.
```

Inside your assistant, the MCP tool **`recall_now`** does the same thing
mid-conversation. And bare `alluvia` prints a now-view: open loops, fresh
bridges, whether a refresh is due.

## The lenses

```
$ alluvia themes            # your thinking, clustered
• Docker Issues  [84 sessions/2 sources]  (2025-03→2026-06)
• Refresh Token Storage  [9 sessions/2 sources]
    Insecure localStorage tokens vulnerable to XSS; approaches discussed...

$ alluvia connections       # bridges across tools and months
🔗 "no cross-check between ids enables forgery"   [tool-A · 2026-06]
   ↔ "service isn't storing the id on upload"      [tool-B · 2025-04]
   why: same missing validation, found twice, 14 months apart.

$ alluvia unfinished        # threads you keep circling, never closing
🧵 Test Infra Reorganization   open · 4 sessions over 388 days

$ alluvia propose           # new next-steps, grounded in YOUR notes
[prop:50bda956] Add server-side consistency check  (feasibility 4/5)
    ...cites: note:104966a3, note:93de85cc
$ alluvia rate prop:50bda956 --keep
```

Two more lenses read the record for trouble: `alluvia loops` lists problems
you recorded and never resolved (pure lookup, spends nothing), and
`alluvia tensions` surfaces contradictions, superseded decisions, and
recurring problems as typed findings with confidence, rationale, and evidence;
confirm one with `--keep`. When a theme is noise, `alluvia mute LABEL` drops
it from digests, recall, and proposals; `unmute` and `muted` reverse and list.

Plus a **weekly digest** (`alluvia digest run --if-due`) that brings at most
five interrupt-worthy items to you, and stays silent when nothing clears the
bar.

## See it: the dashboard

```bash
alluvia serve --open        # http://localhost:8177
```

Five views over your map: corpus overview, theme bubbles by status, the
**cross-tool bridge graph**, a weekly activity timeline with your
longest-unfinished threads, and your full judgments history. One
self-contained page, zero external requests, served only on 127.0.0.1.

## Inside your assistant

Installed as above (`/plugin install alluvia@alluvia`), every session in a
repository starts with what alluvia knows
about **that repository**: the decisions and problems from your last session
there, the loops still open, earlier decisions, each line naming the session
it came from. The same block comes back after every compaction, so a
compacted thread does not lose what it was doing. When alluvia knows nothing
about a repo, it injects nothing. (Injection needs an interactive session; in
headless `claude -p` runs Claude Code applies no session-start context, though
the capture hooks still run.)

It works from transcripts already on your disk, distilled at session end and
before compaction, with no resident process and no model call per tool use.
Claude Code deletes transcripts after 30 days by default; alluvia's notes and
receipts stay.

Something wrong or stale? `alluvia forget <note-id>` and it never comes back.
Ten MCP tools are wired by the same plugin: `recall_now`, `recall_themes`,
`find_connections`, `unfinished_threads`, `tensions_now`, `show_source`,
`propose_next`, `list_proposals`, `rate_proposal`, and `get_digest`, so Claude
Code or Cursor can ask mid-conversation. *"You circled this in April. Here's
where you landed."* Manual registration still works:
`claude mcp add alluvia -- alluvia mcp`.

## Your machine, visible

```bash
alluvia status    # every path + size, store by data class, what's running
alluvia top       # live CPU/RAM/disk of alluvia processes + its LLM traffic
alluvia doctor    # diagnoses the install and repairs what's safe to repair
alluvia export-graph --out map/   # your whole map as a portable graph bundle
```

Concurrent sessions are safe by design (WAL store, single-writer refresh
lock), and any alluvia process can be killed at any instant: everything done
so far is saved and resumes on the next run.

## What leaves your machine

| Data | Where it goes |
|---|---|
| Raw conversations | **Nowhere.** Local SQLite, forever yours |
| Embeddings | **Nowhere.** Computed locally (fastembed/ONNX) |
| Distill / label / propose calls | Your configured LLM provider, under your API key, secret-scrubbed first |
| Cloud memory sync | Only after `alluvia cloud login`. Distilled notes, session metadata, and your judgments, never raw history |
| Managed distillation | Only after sign-in, and only when your own provider is limited or absent. Secret-scrubbed transcripts, under your account's monthly budget |
| Team sync | Opt-in only (`alluvia cloud sync`). Distilled notes, never raw history |
| Telemetry | **There is none.** |

Provider is your choice: Groq, OpenAI, or Anthropic. **The whole product
works end-to-end on Groq's free tier.** No card, no cloud account, a real trial
on your real history where nothing leaves your machine, with per-role model
overrides (`ALLUVIA_LLM_MODEL_PROPOSE=...` for a stronger generator, cheap
models for bulk extraction).

Rate limits are handled for you: every call runs behind a provider-agnostic
governor with backoff, per-model circuit breakers, and automatic fallthrough
across models (on Groq's free tier each model has its own daily budget; when
one hits a wall, alluvia moves to the next and comes back later). If a stage
still can't complete, `alluvia refresh` says so, with per-stage counts and the
provider retry time, and finishes the rest of the map instead of failing.
Pending labels and statuses retry automatically on the next refresh.

## How it works

```
sources ─► ingest ─► RAW (never mutated) ─► distill ─► notes ─► embed
                                                                  │
              lenses ◄── themes/links/status ◄── cluster/link/track
                │
   CLI · MCP · weekly digest        ratings ─► the eval corpus (yours)
```

Three data classes with different guarantees: **raw** (source of truth, never
touched), **derived** (rebuildable from raw: improve the pipeline, re-run,
nothing lost), **judgments** (your ratings and digests: durable, never
regenerated).

## Bring your ChatGPT history

ChatGPT ingestion uses the official data export: ChatGPT → Settings → Data
controls → Export data. When the ZIP arrives by email:

```bash
alluvia ingest --source chatgpt-export --path ~/Downloads/chatgpt-export.zip
alluvia refresh
```

Your ChatGPT threads join the same map as Claude Code and Cursor. That's
where the cross-tool bridges come from.

## Honest limits

- Windsurf and Antigravity transcripts live in schema-less protobuf stores;
  alluvia detects and skips them cleanly. ChatGPT ingestion uses the official
  data export (ZIP), not live capture.
- Generated proposals are guardrailed (must cite your notes, novelty-gated,
  feasibility-labeled) but they're LLM output: you rate, alluvia learns.
- All accepted trade-offs live in [docs/DEBT.md](docs/DEBT.md), each with the
  condition that triggers fixing it.

### Any source, one contract

Built-in adapters cover **Claude Code, Cursor, Codex CLI, Gemini CLI,
OpenCode, the Cline family (Cline, Roo, Kilo), and ChatGPT exports.** Beyond
those, anything that writes a simple
[normalized-session JSONL](docs/SOURCES.md) is a source:

```bash
alluvia ingest --source jsonl --path ./exports/
```

That's how **multi-machine** setups work with no cloud (aggregate your hosts'
histories into one directory), and how tools we don't ship a parser for
arrive already normalized. Community feeders welcome.

## Alluvia Cloud: one sign-in, then it just works

```bash
alluvia cloud login       # the one thing to remember
alluvia cloud status      # plan · managed budget left this month · last memory sync
```

| Tier | Price | What it adds |
|---|---|---|
| Open Source | $0 | Everything above, forever, on your machine |
| Cloud Free | $0 | Memory synced across your machines; refresh falls through to managed distillation, $5 a month included |
| Cloud Pro | $25 a month | $20 a month of managed distillation, priority backfill |
| Team | $20 a seat a month | Shared recall with receipts, verified answers, a registry of decisions |
| Enterprise | contact | SSO/SAML, audit, self-host |

For teams it is the same pipeline, multiplayer: opt in to sync **distilled
notes only** (raw history still never leaves each machine) into a shared
index, so anyone can ask what the team already figured out and get the answer
with receipts:

> *"Yes. That was fixed in March, in the token-refresh module, by pinning the
> clock skew. Here are the sessions."* Or an honest *"no record of that."*

Team recall with citations, verified answers (confirm one, and everyone gets
the verified version first), and a living registry of decisions, including
what superseded them (`alluvia cloud sync`).

Sign-ups are open at [alluvia.dev](https://alluvia.dev).

---

MIT · built local-first on purpose: the research this project started from
found that for developers, trust in this category is *owned data or nothing*.
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) ·
[Security policy](SECURITY.md) · [Brand](docs/BRAND.md)
