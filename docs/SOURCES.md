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
