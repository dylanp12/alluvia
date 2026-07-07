# Changelog

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
