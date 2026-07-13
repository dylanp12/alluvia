# Security policy

alluvia's core promise is that your raw AI history stays on your machine —
security reports that touch that promise are the highest-priority work in
the project.

**Report privately** via GitHub: Security → "Report a vulnerability" on this
repository (private advisory). Please do not open public issues for
vulnerabilities.

In scope, especially: anything that exfiltrates session content, defeats
secret scrubbing before LLM calls, escapes the localhost-only dashboard, or
lets an MCP client write or spend without the machine-level opt-in.

You'll get an acknowledgment within a few days, and credit in the release
notes if you want it.
