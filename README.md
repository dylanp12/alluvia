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

Every conversation you've ever had with an AI tool is sediment. Most of it is
sand, but scattered through it are the nuggets: ideas you never chased,
solutions you solved once and forgot, threads you meant to finish. alluvia is
the pan.

You think through problems in Claude Code. You debug in Cursor. You explore in
ChatGPT. Each tool remembers nothing about the others, and neither do you. The
idea you need today is sitting in a session from last spring, in a different
app, under a title you'll never search for. alluvia finds it, and shows you
where it found it.

> *"I know I've already thought about this. Resurface it inside the tool I'm
> using now, with the receipts, without giving another cloud service my raw
> history."* That sentence is the product.

**Local-first recall for AI-assisted work: across tools, with receipts and
human judgment.** Not another "AI memory": your raw sessions never leave the
machine, every answer quotes the session it came from, and when there is no
record it says so instead of inventing one.

alluvia ingests all of it into one local store, distills it into atomic notes,
clusters those into themes, and then does the part nothing else does: **it
finds the bridges**, the places where your past self already met the problem
your present self is holding.

> **A true story from alluvia's own validation gate:** a security review in one
> tool flagged a server-side validation gap. `alluvia connections` linked it to
> debugging sessions in a *different* tool from **14 months earlier**: same
> root cause, long forgotten. Then `alluvia propose` turned that bridge into a
> concrete fix plan, cited back to both sources. The human kept it.
> Every claim in this README traces to a logged validation gate; see
> [docs/validation](docs/validation/).

## Sixty seconds

![alluvia finding a cross-tool bridge](https://alluvia.dev/alluvia-demo.gif)

*([the full replay](https://alluvia.dev/alluvia-demo.mp4), rendered from real
pipeline output; the team dashboard has its own replay on
[alluvia.dev](https://alluvia.dev))*

```bash
uv tool install alluvia    # or: pip install alluvia
alluvia demo               # every lens in 30s: no API key, synthetic data
alluvia init               # detect your sources, choose your provider
alluvia refresh            # distill → embed → cluster → map (local embeddings)
alluvia recall "the thing I'm debugging"   # cited recall from your own history
```

One-shot trial without installing: `uvx alluvia init`.

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

```bash
uv tool install alluvia && alluvia init          # once
/plugin marketplace add dylanp12/alluvia          # in Claude Code
/plugin install alluvia@alluvia
```

From then on, every session in a repository starts with what alluvia knows
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

## For teams: Alluvia Cloud

The same pipeline, multiplayer. Teams opt in to sync **distilled notes only**
(raw history still never leaves each machine) into a shared index, so anyone
can ask what the team already figured out and get the answer with receipts:

> *"Yes. That was fixed in March, in the token-refresh module, by pinning the
> clock skew. Here are the sessions."* Or an honest *"no record of that."*

Team recall with citations, verified answers (confirm one, and everyone gets
the verified version first), and a living registry of decisions, including
what superseded them.

```bash
alluvia cloud login       # then:
alluvia cloud sync        # distilled notes up; raw history stays home
alluvia cloud status
```

Sign-ups are open at [alluvia.dev](https://alluvia.dev). Free for founding
teams during early access.

---

MIT · built local-first on purpose: the research this project started from
found that for developers, trust in this category is *owned data or nothing*.
[Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) ·
[Security policy](SECURITY.md) · [Brand](docs/BRAND.md)
