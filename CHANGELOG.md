# Changelog

## Unreleased

## 0.9.4 — 2026-09-08

- **The plan's limits are said plainly.** When the cloud refuses a second
  machine on Free, the CLI says so in one line and nothing else changes on
  this machine.

## 0.9.3 — 2026-09-08

- **One briefing, two readers.** The session-start briefing is now a structure
  the text is rendered from, so the app can show it as sections that link to
  sessions while the plugin injects the identical text.
- **The push carries the whole derived record.** After the memory bundle, the
  same push sends topics, related work, and suggestions (never raw) so the app
  fills in by itself, plus the number of sessions still waiting on this machine.
- **Processing is a Pro feature.** Free accounts bring their own key; the pause
  says how many sessions are waiting and that Pro processes them with no key.

## 0.9.2 — 2026-09-08

- **An unforget reaches every machine.** A suppression retracted elsewhere
  (the app, or another machine) is applied on import: the note comes back.
  Older records without the field still suppress, as before.

## 0.9.1 — 2026-09-08

Found on the first real sign-in: when Alluvia's own managed gateway failed, the
pause blamed your provider. Now it says whose fault it is.

- **An outage on our side is named as ours.** When the managed gateway fails
  for a reason that is not your budget (its upstream refused, a server error,
  unreachable), the managed candidate rests for fifteen minutes instead of
  failing every remaining session, the pause text says "managed distillation is
  unavailable right now" with one readable sentence of reason, and
  `alluvia cloud status` shows the outage and when it retries. Your own
  provider is still tried first.
- **The sign-in link is always printed.** `alluvia cloud login` opens the
  browser and also prints the link to paste, for SSH sessions and browsers that
  do not open.
- **Failure lines are readable.** A provider's multi-kilobyte error body is no
  longer dumped to the terminal once per session; the log line carries its
  head, the detail stays in the exception.
- Adapters can declare a cooldown on an exception; the Governor opens the
  breaker for exactly that long instead of sleeping through it.

## 0.9.0 — 2026-09-07

One thing to remember: `alluvia cloud login`. Then memory follows you, and a
refresh never stalls.

- **Memory follows you.** After sign-in, the never-raw bundle (session
  metadata, distilled notes, suppressions, mutes) syncs up after every session
  and refresh and down before, so a second machine receives everything on its
  first refresh. No command to run, nothing to schedule. Files
  (`alluvia memory export/import`) and repository-carried memory stay for
  people who prefer them or never sign in.
- **A refresh never stalls.** Once signed in, Alluvia Cloud's managed
  distillation joins the distill chain as the last candidate: when your own
  provider is rate-limited it takes over under your account's monthly budget,
  and with no provider key at all it is the only path. `ALLUVIA_MANAGED_DISTILL=1`
  puts it first, `=0` never uses it. Cloud Free includes $5 a month; Pro raises
  it to $20.
- **The pause says what would end it.** A rate-limited refresh now tells a
  signed-out user what one sign-in changes, and a signed-in user whose managed
  budget is spent what Pro raises it to.
- **`alluvia cloud status`** shows the plan, managed distillation used and
  remaining this month, and when memory last synced. `alluvia cloud login`
  syncs immediately and says what arrived. `alluvia cloud sync` also pushes
  memory.
- Signed out, nothing changes: no network, no prompts, and every path above
  reports "not signed in" instead of failing. Hooks never fail on a sync.

## 0.8.0 — 2026-09-07

Your memory is yours to move, and the record shows what it did.

- **Portable memory.** `alluvia memory export` writes your distilled notes,
  session metadata, suppressions, and mutes to one file; `alluvia memory import`
  merges it on any machine, idempotently. Never raw conversations. Imported
  sessions are never sent to the LLM, and this machine's own sessions always
  win over an import.
- **A repository can carry its own memory.** `alluvia repo share on` keeps
  `.alluvia/memory.jsonl` current after every session and refresh; a fresh
  clone or a second machine receives the repository's handoff on its first
  session. Committing the directory is your act. `alluvia repo status` and
  `alluvia repo share off` complete the set.
- **Proof of use.** Every injected handoff is recorded with the notes it
  showed. `alluvia handoff --kept | --noise` (and the MCP tool `rate_context`,
  behind the MCP write switch) records your verdict; the session's own text is
  checked for the notes it used and stored as a labeled proxy; recall counts
  answers and refusals. `alluvia stats` shows all of it, counts only.
- **One pitch.** README, PyPI description, and plugin copy now lead with: your
  agent remembers this repo, and it will not lie about it.
- The handoff footer asks for a verdict, and a lone session reads as
  "1 session".

## 0.7.1 — 2026-09-06

- **Windows paths.** A repository path recorded on another machine or OS is kept
  verbatim instead of being re-separated, project keys agree whether a path
  was written with `/` or `\`, and `[action]` lines are relative to the
  session's working directory on Windows-shaped transcripts too. Found by the
  public CI on Windows the moment 0.7.0 shipped.

## 0.7.0 — 2026-09-06

Your agent remembers this repo, and it will not lie about it.

- **Claude Code plugin** — one install wires session hooks and the MCP tools.
  Every session start, resume, and post-compaction injects what alluvia knows
  about the repository you are in: last session's decisions and problems, open
  loops, earlier decisions, each with its session receipt. Nothing known,
  nothing injected. Transcripts are captured at session end and before
  compaction; no daemon, no per-tool-call model.
- **Sessions know their repository.** The Claude Code adapter keeps the
  working directory and branch, and records tool actions (files edited,
  commands run) as `[action]` lines, so notes can name files. Re-distill
  required (pipeline v3).
- **Recall ranks by the question.** Bridge weight no longer buys a slot; the
  similarity floor is calibrated to the shipped embedder; hits carry a
  confidence (strong, corroborated, weak) and weak ones are hidden by default;
  `--here` scopes to the current repository; an empty result says "no record".
- **`alluvia forget <note-id>`** suppresses a wrong or stale note everywhere,
  permanently, without touching raw sessions.
- **Long sessions distill in bounded windows** that always include the end of
  the session, where decisions land. A provider limit part-way keeps the notes
  that came back and leaves the session pending instead of discarding them.
  Harness-injected content (skill bodies, command expansions) is never treated
  as your thinking, and re-ingesting a session with a better adapter replaces
  its stale notes instead of piling on.
- **`alluvia mcp` starts on fresh installs again.** The dependency spec allowed
  mcp 2.x, which renamed the server API, so a new `uv tool install alluvia`
  showed "1 MCP server failed" in Claude Code. Pinned below 2 and guarded by a
  test; found by installing the release like a stranger.
- **Coverage is visible.** `refresh`, `status`, and `doctor` state how many
  sessions are distilled and how many are pending, and a paused refresh says
  so instead of finishing quietly.

## 0.6.1 — 2026-09-02

The docs and the brand caught up with the product: a README with receipts, and a kit set on paper.

- **README rewritten for the 0.6 product** — recall with receipts, hybrid and
  time-scoped search, the honest refusal, the ten MCP tools, and the lenses that
  arrived since 0.3 (`loops`, `tensions`, `export-graph`, `mute`, `alluvia cloud`).
  The demo replays now come from alluvia.dev and match the current identity;
  team sign-ups are noted as open.
- **Brand kit brought up to the current identity** — paper, ink, and a gold that
  passes AA when it has to be read as text; Newsreader, Geist, and JetBrains Mono;
  recolored marks and lockups, a regenerated favicon and social preview.
  `docs/BRAND.md` and `assets/alluvia-tokens.css` are the source of truth. The
  localhost dashboard still renders the previous palette; it migrates in a
  later release.
- **`ingest --source` help lists every adapter** — `codex`, `gemini`, and
  `opencode` were accepted but missing from the help text (#21).

## 0.6.0 — 2026-08-18

Recall grew up: ask a question, get the answer — with the receipts.

- **Groq defaults work again** — Groq retired its Meta Llama models (`llama-3.3-70b-versatile`,
  `llama-3.1-8b-instant` now 404), which broke distillation on stock config. The default
  chain is now `openai/gpt-oss-120b → qwen/qwen3.6-27b → openai/gpt-oss-20b`, all live
  on the free tier. Found by a live end-to-end run, not a bug report.
- **Receipts never quote harness scaffolding** — Claude Code's auto-summary prompt
  (written into session files) could surface verbatim as a recall receipt and reach the
  distiller. It's now a recognized meta marker, and the excerpt slicer declines to quote
  any meta message — no receipt beats a garbage receipt.
- **Hybrid recall** — `alluvia recall` (and the MCP + team recall built on it) now
  pairs vector search with an exact-match channel: error strings, file paths, and
  snake_case identifiers find their note even where embeddings go blind
  (`ECONNREFUSED`, `auth/refresh.py`, `DATABASE_URL`). A note matched by both
  channels rises; one shared word is not a match; still retrieval-only, still zero
  LLM spend. Existing stores index themselves on first search — nothing to migrate.
- **Recall eval gate** — a golden query set (semantic · exact-match · must-refuse)
  runs with the test suite; retrieval changes must beat the dense-only baseline on
  exact-match and never regress semantics or honest refusal.
- **Time-scoped recall** — recall now understands time: `alluvia recall "the auth
  fix last tuesday"` searches only that window ("last week", "in march",
  "march 2025", "3 days ago", "since march", "before march", "2025" all work),
  the time words stop polluting matching, and an empty window answers honestly
  empty instead of surfacing the wrong era. Undated notes never fake membership
  in a window. Without a time expression, freshness only breaks ties — a
  14-month-old cross-tool rediscovery still outranks a weak fresh match.
  Deterministic parser, no LLM, works identically in team recall.
- **Receipts** — every recall hit now carries the verbatim quote behind its cites,
  sliced fresh from the raw session (wrapper-stripped, secret-redacted, capped).
  The CLI prints it, `--handoff` pastes it, and the MCP `recall_now` returns it,
  so an answer is checkable at a glance. Team recall serves receipts from synced
  excerpts (for sources opted into excerpt/raw sync), and cloud synthesis grounds
  its answer on the verbatim quote rather than a paraphrase. Proposal grounding
  now runs through the same redacted excerpt path.

## 0.5.0 — 2026-08-10

Your memory can leave the laptop now — opt in to Alluvia Cloud and a team shares one map.

- **`alluvia cloud`** — opt-in sync of your derived memory to Alluvia Cloud, so a
  team shares one map. `login` signs in through your browser (a one-shot local
  listener catches the token); `sync` previews exactly what will leave first —
  notes, themes, links, and session metadata, every text secret-scrubbed — and raw
  transcripts stay on your machine unless you opt a source into `raw`; plus
  `status` and `logout`.
- **New sources** — `alluvia ingest --source` now covers the Cline family (`cline`, `kilo-code`,
  `roo-code`), **`opencode`**, **`codex`** (OpenAI Codex CLI), and **`gemini`** (Gemini CLI) — reading
  each tool's own on-disk history. A shared adapter toolkit makes new sources thin to add.
- **Cleaner distillation** — the distiller no longer surfaces the assistant's own
  process/state chatter (waiting-for-input, "no autonomous work", tool/permission
  narration) as notes, and now also filters **runtime-injected scaffolding** that lands in
  user-role slots (system reminders, command echoes, background task notifications,
  continuation summaries) so harness noise isn't attributed to the human. Secrets **and
  common PII** (emails, JWTs) are redacted before any text leaves the machine. The source
  contract (`docs/SOURCES.md`) now spells out what senders should strip and exclude.
- **`alluvia loops`** — problems you recorded and never resolved: no fix
  decision points at them, in your notes or your confirmed findings. Pure
  lookup, zero LLM spend, each with age, theme, and source.
- **Rate your tensions** — `alluvia tensions --keep <id>` confirms a finding
  and promotes it into your map as a confirmed relation (with a
  human-confirmed judgment event carrying the evidence); `--dismiss <id>`
  records the verdict. Predictions never become part of your map without
  your say-so.
- **MCP `tensions_now`** — the typed findings, readable from Claude Code /
  Cursor mid-conversation. Read-only; spends nothing; rating stays in the
  CLI.
- The relation vocabulary gains **transfers**: a solution from one area that
  structurally applies to a problem in another.
- **`alluvia tensions`** — a new lens for the map's disagreements:
  contradictions, superseded decisions, and recurring problems, each with a
  confidence, a one-sentence why, and the exact source sessions as evidence.
  `--scan 20` classifies your top connections first (one LLM call per pair,
  Governor-managed). Findings are predictions you can inspect — never silent
  rewrites of your map.
- **`alluvia export-graph`** — export your whole knowledge map as a portable,
  open bundle: typed nodes and provenance-carrying events (gzipped JSONL plus
  a versioned manifest). Your data was always yours; now it travels.
  `--no-judgments` leaves your ratings out.
- **Extraction provenance** — every distill pass now records which model
  produced it; new notes carry a pointer to their extraction run. Exports
  include it, so every derived fact can say who wrote it down and from where.
- **Selection transparency** — propose and digest now record their full
  considered pool (what was shown, what was scored but cut, at which rank,
  under which policy) locally. Nothing leaves your machine; future ranking
  improvements can be judged against honest records instead of survivor bias.
- **Digest exploration slot** — every 4th digest trades one connection pick
  for a long-shot from beyond the usual cutoff, marked `EXPLORE:`. Tune with
  `ALLUVIA_DIGEST_EXPLORE_EVERY` (0 disables).


## 0.4.0 — 2026-07-17

Recall becomes the front door — and any source can feed it.

- **`alluvia recall "<problem>"`** — the fastest path from "I know I solved
  this before" to cited proof. Fuses your themes, bridges, and unfinished
  threads into a few high-signal hits, each with sources and status.
  Retrieval only — **zero LLM spend**. `--handoff` emits a paste-ready
  context block for whatever assistant you're in; `--json` for scripting.
- **MCP `recall_now`** — the same recall inside Claude Code / Cursor,
  mid-conversation. Read-only; spends nothing. When git is present, recall
  conservatively flags "possibly implemented in <commit>" by matching your
  local history — a pointer to verify, never a claim.
- **Bare `alluvia`** now prints a now-view: open loops, freshest bridges,
  and whether a refresh is due.
- **`alluvia demo`** — every lens alive in ~30 seconds on a tiny synthetic
  corpus, with no API key and no LLM calls, in its own store (never your
  real one). `--clean` removes it.
- **A source contract** (#15) — anything that writes
  [normalized-session JSONL](docs/SOURCES.md) is now a source:
  `alluvia ingest --source jsonl --path <file|dir>`. Multi-machine history
  without cloud, and formats we don't ship parsers for arrive normalized.
- Internally, the sqlite-vec and numpy vector backends now return the same
  cosine scores, so ranking is identical whichever is active.


## 0.3.0 — 2026-07-13

The first five minutes, fixed — and MCP writes become opt-in.

- **Newest sessions first** — distillation now always processes your most
  recent sessions first, so the map is freshest where it matters.
- **First-run cap** — the very first refresh distills your ~50 most recent
  sessions and says so ("the remaining N backfill automatically on the next
  refresh"). You see labeled themes, connections, and unfinished threads in
  minutes instead of waiting out a full-history distill — and the label/
  status stages keep budget headroom on day one. Tune or disable with
  `ALLUVIA_FIRST_RUN_CAP` (0 turns it off). (#11-class first-run failures,
  designed out.)
- **MCP is read-only by default** (#12) — `rate_proposal` and `propose_next`
  (the tools that write your judgments or spend your LLM budget) now return
  a clear "disabled" message unless you opt in on your machine:
  `[mcp] writes = true` in config.toml or `ALLUVIA_MCP_WRITES=1`. Surprise
  writes are impossible, not merely detectable.
- **Windows CI** (#13) — the platform detection that already claimed Windows
  is now tested there.
- Docs: SECURITY.md (private vulnerability reporting), CONTRIBUTING.md,
  a ChatGPT-history import guide, and a README that says the quiet part
  loudly: the whole product works end-to-end on a free-tier key.


## 0.2.2 — 2026-07-13

Visual identity — **sediment & gold**. alluvia now looks like what it does: a
patient field survey of your own thinking, with one scarce point of gold at the
find.

- **New mark & wordmark** — three tributaries converge at a gold node and
  continue as one stem (it diagrams the product, and reads as a merge graph).
  Lockup, wide/square marks, favicon, and a social-preview card live in
  `assets/`; the README carries a dark/light-aware lockup.
- **Dashboard reskin** — the `alluvia serve` dashboard moves onto the brand
  palette (Ink/Basin/Paper/Wash/Silt/Gold), now **light- and dark-aware** instead
  of dark-only, with IBM Plex Mono station labels and an inlined favicon. Zero
  external requests, as before.
- **Accessible by construction** — every theme status carries a labelled dot
  (never colour alone), status and source palettes are contrast- and
  colour-vision-validated on both grounds, and gold is a *filled mark* reserved
  for the find/active state — never text on a light surface.
- **Brand guide** — `docs/BRAND.md` documents the palette, the scarcity rule, the
  ground-scoped token roles, and the voice.
- No engine, CLI, MCP, or storage behaviour changed.

## 0.2.1 — 2026-07-12

- **`alluvia top`** (#10) — live resource usage of every running alluvia
  process: sampled CPU %, RAM, cumulative disk read/write, uptime, with a
  machine context line. `--watch N` for a refreshing view; `status` shows
  the same process list.
- **Network accounting at the source** (#10) — per-process network bytes
  aren't visible to unprivileged userland on any OS, and alluvia's only
  traffic is its LLM calls — so the governor now counts them itself:
  calls and bytes sent/received per model, persisted with the breaker
  state and reported by `top`.
- New dependency: psutil (cross-platform process metrics).


## 0.2.0 — 2026-07-12

The good-citizen release: alluvia now runs concurrently, dies cleanly, shows
you everything it keeps, and repairs itself (#5, #6, #7, #8).

- **Concurrent sessions** (#5) — the store runs in WAL mode (readers never
  block a running refresh; legacy stores upgrade transparently), refresh
  takes a single-writer lock released by the OS on any process death
  ("already running (pid N)" instead of double-spending your LLM budget),
  and `serve` reuses an already-running dashboard or walks to a free port.
- **Kill-anytime contract** (#5) — any alluvia process can be killed at any
  instant with zero corruption and zero cleanup debt. SIGTERM behaves like
  Ctrl-C; interrupting a refresh prints "paused — everything done so far is
  saved" and resumes on the next run.
- **`alluvia status`** (#6) — every path alluvia touches with sizes, the
  store broken down by data class (raw = source of truth · derived =
  rebuildable · judgments = yours), and what's live right now. `--json` for
  scripting.
- **`alluvia doctor`** (#7) — diagnoses the whole installation and applies
  every safe repair automatically: WAL on legacy stores, schema migrations,
  pruning orphaned derived rows, config permissions, stale digest flags,
  impossible governor cooldowns. Raw data and judgments are never touched.
  `--check` reports without repairing (exit 1 if repairs are needed),
  `--live` proves your provider key with one tiny call, and
  `--rebuild-derived` is the confirmed recovery lever that discards derived
  data while raw sessions and your ratings survive.
- **`--verbose` and `refresh --plan`** (#8) — see the pipeline and governor
  think; preview exactly what a refresh would do (sessions pending, theme
  work, cooldowns in effect) without spending a single LLM call.

## 0.1.2 — 2026-07-09

You can now see what alluvia is doing (#4). Long stages used to run silently and
look hung — worst of all a first `refresh`, which downloads the local
embedding model with no output at all.

- **Live progress everywhere it was silent** — `refresh` shows each stage
  (distilling N sessions, embedding, mapping themes, linking) with rich
  progress bars on a terminal and plain line output when piped or in CI.
  `ingest` shows a running session count.
- **Deliberate waits are narrated** — when the governor waits out a rate
  limit it says so (`⏳ rate-limited: waiting 30s (model)`) instead of
  freezing; the first-run embedding-model download announces itself.
- Embeddings run in batches so progress moves (and memory stays flat).
- `alluvia --version`.
- Issue templates (bug report asks exactly for the refresh summary and
  version; feature template fits both small asks and full RFCs) and a PR
  template with a test-first checklist.
- MCP tools, library callers, and the test suite see zero new output —
  progress is CLI-only by construction.

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
