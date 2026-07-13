# Contributing

Thanks for caring about alluvia.

**Start with an issue.** Bug reports and feature discussions are the front
door — templates ask for exactly what's needed (`alluvia --version`,
`alluvia doctor --check` output; never your session content).

**About pull requests:** development currently happens in a private
repository that also hosts unreleased work; this public repo mirrors it
exactly, release by release. Small PRs (docs, clear fixes) are welcome and
will be reviewed and landed upstream with credit. For anything larger,
open an issue first so the design lands before the code — otherwise a sync
may overwrite work you spent real time on.

**Local dev:**

```bash
uv sync --all-groups
uv run pytest -q          # the whole suite runs on FakeLLM — no API key needed
```

Conventions the suite enforces: tests first, engine stays UI-free, MCP
tools return errors as values, raw sessions are never mutated, and nothing
personal ships — not in code, fixtures, or comments.
