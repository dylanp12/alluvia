# Source contract — bring any AI-session history to alluvia

alluvia ships parsers for a few tools, but the store itself is
source-agnostic. Anything that writes the **normalized-session JSONL**
schema below is an ingestion source:

```bash
alluvia ingest --source jsonl --path ./sessions.jsonl      # one file
alluvia ingest --source jsonl --path ./exports/            # every *.jsonl under a dir
```

This is how multi-machine setups work without any cloud (aggregate your
hosts' histories into one directory by any means — an archiver, rsync,
object storage you own) and how tools alluvia has no parser for arrive
already normalized.

## Schema — one JSON object per line

```json
{"source": "codex",
 "native_id": "sess-8f3a",
 "title": "auth token refresh race",
 "started_at": "2026-06-01T10:00:00+00:00",
 "ended_at": null,
 "messages": [
   {"role": "user", "text": "why does refresh double-fire?", "ts": "2026-06-01T10:00:00+00:00"},
   {"role": "assistant", "text": "two tabs race the same refresh token…", "ts": null}
 ]}
```

Fields:

- `source` (required) — short stable slug for the origin tool
  (`codex`, `opencode`, `claude-desktop`, …). Shown in every lens and on
  cross-tool bridges; sessions are identified as `source:native_id`.
- `native_id` (required) — the session's id in its origin tool. Stable ids
  make re-exports idempotent.
- `messages` (required, non-empty) — objects with `role`
  (`user` | `assistant`; other roles are ignored), `text` (non-empty), and
  optional ISO-8601 `ts`.
- `title` (optional) — defaults to the first message's opening words.
- `started_at` / `ended_at` (optional) — ISO-8601.

There is no `project`/workspace field: attribution is per `source`. If cross-project vs
within-project bridges ever matter, an optional field can be added compatibly.

## What to send

`messages[].text` must be **conversation authored by the user or the model** — not
harness-injected scaffolding. Real transcripts stuff the user role with runtime content
shaped like a user turn that nobody wrote: system reminders, slash-command echoes,
environment/context blocks, background task notifications, tool output. Only the source
knows its own injection patterns, so **strip them before emitting** — otherwise that noise
is attributed to the human and pollutes themes and bridges. (alluvia filters the common
harness patterns as a backstop, but the sender owns fidelity.)

**Exclude subagent / child sessions.** If a tool runs sub-sessions (a parent spawning
helpers), don't emit them as top-level sessions — they're mostly duplicated parent context
with little unique signal, and they'd pollute themes and bridges the way they'd pollute a
search index.

**Emit settled sessions, not live ones.** Re-emitting a session with the same
`source:native_id` replaces it and **re-distills** it (an LLM call). A scheduled exporter
over a growing archive should emit a session only once it's settled — e.g. no new messages
for a few minutes — so a live session isn't re-distilled on every sync.

## Semantics

- **Idempotent**: re-ingesting is safe — sessions dedupe on content; a
  changed transcript with the same `source:native_id` replaces the old one
  and re-distills.
- **Raw means raw**: what you ingest is stored verbatim in the raw class
  (never mutated). Secret-scrubbing happens before any LLM call, not in
  the store — keep full fidelity upstream.
- **Invalid lines are skipped and logged**, never fatal.
- Everything downstream (themes, bridges, unfinished, proposals, MCP,
  dashboard) treats contract-fed sources exactly like built-in ones.

Feeders that already target this contract are welcome in the README —
open an issue.
