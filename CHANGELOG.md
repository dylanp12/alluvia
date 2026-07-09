# Changelog

## 0.1.1 — 2026-07-09

Resilience release: provider rate limits no longer darken the map (#1, #2, #3).

- **LLM governor** — every provider call now runs behind a provider-agnostic
  governor: escalating cooldown ladder, per-model circuit breakers, and
  role→model fallthrough chains, all driven by abstract call outcomes (HTTP
  status and the standard `Retry-After` header are optional fast-paths, never
  dependencies). Breaker state persists in SQLite, so short CLI runs respect
  cooldowns learned by earlier runs instead of re-hammering an exhausted model.
- **Fallthrough chains** — on Groq's free tier each model has its own daily
  budget; distill/label/status/why calls fall through to sibling models when
  the head model hits a wall. `propose` never falls through — generation fails
  loud rather than silently downgrading. Override per role with
  `ALLUVIA_LLM_CHAIN_<ROLE>` (comma-separated).
- **`unfinished` never goes dark** — when the status classifier is
  unavailable, recurring themes get a heuristic status (recently touched →
  open, stale → dormant) instead of `unknown`. Heuristics are never cached;
  the classifier upgrades them on a later refresh.
- **Degradation is visible** — `refresh` prints a per-stage summary and a
  warning with the provider retry time when a stage degraded; `themes` /
  `unfinished`, the MCP tools, and the dashboard surface the same signal. An
  all-`unknown` map now says "the classifier hasn't completed" instead of
  pretending nothing is unfinished.
- Distillation pauses immediately (and resumably) when every model is cooling;
  fallback labels cut at word boundaries; adaptive pacing (AIMD) discovers a
  provider's sustainable request rate empirically.
- **Breaking:** every environment variable now uses the `ALLUVIA_` prefix
  (`ALLUVIA_DB`, `ALLUVIA_LLM_MODEL_<ROLE>`, `ALLUVIA_LLM_CHAIN_<ROLE>`, …) — 0.1.0
  shipped them under an inconsistent prefix. If you exported variables for
  0.1.0, re-export them with the new prefix; `config.toml` users are
  unaffected.

## 0.1.0 — 2026-07-05

First installable release. Everything to date: five source adapters
(Claude Code, Cursor, Windsurf*, Antigravity*, ChatGPT export), raw-first
SQLite store with a swappable vector index (sqlite-vec/numpy), the
distill→embed→cluster→label→status→link engine, four lenses
(themes / connections / unfinished / propose) with a human ratings loop,
a proactive weekly digest with mute + dismissal-learning, eight MCP tools,
multi-provider role-mapped LLM support (Groq/OpenAI/Anthropic), config.toml
+ `alluvia init` onboarding, and cross-platform source detection.
(*Windsurf/Antigravity ship log-and-skip: their stores are schema-less
protobuf — see docs/DEBT.md.)

Every capability was validated against a real 400+-session corpus through
live gates; see docs/validation/.
