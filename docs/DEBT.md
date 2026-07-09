# Known debt & deferred hardening

Reviewed 2026-07-04 (external LLM review of M2d/M2e). Items here are *accepted*
trade-offs with their trigger conditions — not TODOs.

| Debt | Today's mitigation | Build it when |
|---|---|---|
| MCP write/spend tools rely on tool-contract compliance, not enforcement | Contract docstrings + `rated_via` audit trail (pollution is identifiable/filterable) | Product-B era / any second user: add confirm-before-write/spend mode (host-side elicitation or a pending-approval queue) |
| Label-keyed mute can collide (exact-label dupes) or drift (relabeled theme escapes mute) | Exact `label_lc` match only (never substring); `alluvia mute` warns on multi-match or no-match | First observed drift/collision in practice: anchor mutes to content (status-hash or representative note ids) alongside the label |
| Digest C-slot spends LLM budget on a schedule | Bounded to 1 proposal; `ALLUVIA_DIGEST_PROPOSALS=0` for pure-recall digests; provider-down degrades to skip | Fine as-is; revisit defaults if hit-rate data says generation quality doesn't earn the spend |
| Mixed-model distilled notes (free-tier chain) | `pipeline_version` bump re-distills uniformly | Paid-tier day: one-pass uniform re-distill |
| Windsurf/Antigravity log-and-skip (protobuf stores, no schema) | Documented in adapter docstring; probe script kept | Their storage formats become parseable |
| No fair-share budget reservation between pipeline stages (bulk distill can drain a shared daily budget before label/status run) | Per-model breakers + fallthrough chains give label/status their own budget pools; distill pauses resumably when all models cool; heuristic statuses keep `unfinished` alive meanwhile | Starvation still observed *with* chains in practice — then interleave label/status between distill batches (requires incremental re-cluster) or reserve per-role call quotas |
