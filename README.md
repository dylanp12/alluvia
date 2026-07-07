<p align="center"><img src="assets/logo.svg" width="110" alt="Alluvia"></p>

<p align="center">
  <a href="https://github.com/dylanp12/alluvia/actions/workflows/ci.yml"><img src="https://github.com/dylanp12/alluvia/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <a href="https://pypi.org/project/alluvia/"><img src="https://img.shields.io/pypi/v/alluvia?color=d4a017" alt="pypi"></a>
  <img src="https://img.shields.io/badge/license-MIT-d4a017" alt="MIT">
  <img src="https://img.shields.io/badge/python-3.12+-d4a017" alt="python">
  <img src="https://img.shields.io/badge/local--first-always-d4a017" alt="local-first">
</p>

# Alluvia

**Pan your AI history for gold.**

Every conversation you've ever had with an AI tool is sediment. Most of it is
sand — but scattered through it are the nuggets: ideas you never chased,
solutions you solved once and forgot, threads you meant to finish. alluvia is the
pan.

You think through problems in Claude Code. You debug in Cursor. You explore in
ChatGPT. Each tool remembers nothing about the others, and neither do you. The
idea you need today is sitting in a session from last spring, in a different
app, under a title you'll never search for. alluvia finds it.

**Local-first memory for AI-assisted work — across tools, with provenance and
human judgment.** Not another "AI memory": your raw sessions never leave the
machine, every surfaced idea cites its source, and *you* rate what's gold.

alluvia ingests all of it into one local store, distills it into atomic ideas,
clusters those into themes, and then does the part nothing else does: **it
finds the bridges** — the places where your past self already met the problem
your present self is holding.

> **A true story from alluvia's own validation gate:** a security review in one
> tool flagged a server-side validation gap. `alluvia connections` linked it to
> debugging sessions in a *different* tool from **14 months earlier** — same
> root cause, long forgotten. Then `alluvia propose` turned that bridge into a
> concrete fix plan, cited back to both sources. The human kept it.
> Every claim in this README traces to a logged validation gate —
> see [docs/validation](docs/validation/).

## Sixty seconds

```bash
uv tool install alluvia    # or: pip install alluvia
alluvia init               # detects your sources, sets up your LLM provider
alluvia refresh            # distill → embed → cluster → map (local embeddings)
alluvia themes && alluvia serve --open
```

One-shot trial without installing: `uvx alluvia init`.

## The four lenses

```
$ alluvia themes            # D — your thinking, clustered
• Docker Issues  [84 sessions/2 sources]  (2025-03→2026-06)
• Refresh Token Storage  [9 sessions/2 sources]
    Insecure localStorage tokens vulnerable to XSS; approaches discussed...

$ alluvia connections       # A — bridges across tools and months
🔗 "no cross-check between ids enables forgery"   [tool-A · 2026-06]
   ↔ "service isn't storing the id on upload"      [tool-B · 2025-04]
   why: same missing validation, found twice, 14 months apart.

$ alluvia unfinished        # B — threads you keep circling, never closing
🧵 Test Infra Reorganization   open · 4 sessions over 388 days

$ alluvia propose           # C — new next-steps, grounded in YOUR notes
[prop:50bda956] Add server-side consistency check  (feasibility 4/5)
    ...cites: note:104966a3, note:93de85cc
$ alluvia rate prop:50bda956 --keep
```

Plus a **weekly digest** (`alluvia digest run --if-due`) that brings ≤5
interrupt-worthy items to you — and stays silent when nothing clears the bar.

## See it: the dashboard

```bash
alluvia serve --open        # http://localhost:8177
```

Five views over your map — corpus overview, theme bubbles by status, the
**cross-tool bridge graph**, a weekly activity timeline with your
longest-unfinished threads, and your full judgments history. One
self-contained page, zero external requests, served only on 127.0.0.1.

## Inside your assistant (MCP)

```bash
claude mcp add alluvia -- uv run --directory <repo> alluvia mcp
```

Eight tools let Claude Code / Cursor / any MCP client query your idea-map
mid-conversation: *"you circled this in April — here's where you landed."*

## What leaves your machine

| Data | Where it goes |
|---|---|
| Raw conversations | **Nowhere.** Local SQLite, forever yours |
| Embeddings | **Nowhere.** Computed locally (fastembed/ONNX) |
| Distill / label / propose calls | Your configured LLM provider, under your API key, secret-scrubbed first |
| Telemetry | **There is none.** |

Provider is your choice — Groq (free tier works; alluvia chains per-model daily
budgets automatically), OpenAI, or Anthropic — with per-role model overrides
(`SIFT_LLM_MODEL_PROPOSE=...` for a stronger generator, cheap models for bulk
extraction).

## How it works

```
sources ─► ingest ─► RAW (never mutated) ─► distill ─► notes ─► embed
                                                                  │
              lenses ◄── themes/links/status ◄── cluster/link/track
                │
   CLI · MCP · weekly digest        ratings ─► the eval corpus (yours)
```

Three data classes with different guarantees: **raw** (source of truth, never
touched), **derived** (rebuildable from raw — improve the pipeline, re-run,
nothing lost), **judgments** (your ratings and digests — durable, never
regenerated).

## Honest limits

- Windsurf/Antigravity transcripts live in schema-less protobuf stores; alluvia
  detects and skips them cleanly. ChatGPT ingestion uses the official data
  export (ZIP), not live capture.
- Generated proposals are guardrailed (must cite your notes, novelty-gated,
  feasibility-labeled) but they're LLM output — you rate, alluvia learns.
- All accepted trade-offs live in [docs/DEBT.md](docs/DEBT.md), each with the
  condition that triggers fixing it.

MIT · built local-first on purpose: the research this project started from
found that for developers, trust in this category is *owned data or nothing*.
