from __future__ import annotations
import re

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}"),  # Stripe
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),                          # Groq
    re.compile(r"AIza[0-9A-Za-z\-_]{35}"),                        # Google API
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC )?PRIVATE KEY-----"),
]


def scrub_secrets(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


# PII / auth-token shapes redacted before ANY egress. High-confidence patterns only
# (near-zero false positives), so distillation quality is preserved; broader PII
# (names, arbitrary IDs, IPs vs. version strings) is a NER follow-up, not regex.
_PII_PATTERNS = [
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[REDACTED]"),  # JWT
]


def scrub_pii(text: str) -> str:
    for pat, repl in _PII_PATTERNS:
        text = pat.sub(repl, text)
    return text


def redact(text: str) -> str:
    """Full pre-egress redaction: secrets + PII. The single entry point for text that
    leaves the machine — distillation LLM calls (BYOK or managed) and cloud-sync bundles."""
    return scrub_pii(scrub_secrets(text))


_WRAPPER_TAGS = ("local-command-caveat", "command-name", "command-message",
                 "command-args", "command-contents", "local-command-stdout",
                 "system-reminder", "task-notification")
_WRAPPER_RX = [
    re.compile(rf"<{t}>[\s\S]*?</{t}>", re.IGNORECASE) for t in _WRAPPER_TAGS
]


def strip_wrappers(text: str) -> str:
    """Remove harness wrapper blocks (slash-command echoes, caveats, reminders).

    Applied at TITLE-derivation and DISTILL-render time only — stored message
    text stays raw (raw-first principle)."""
    for rx in _WRAPPER_RX:
        text = rx.sub("", text)
    return text.strip()


# Harness meta-noise / runtime-injected scaffolding that lands in a USER-role slot
# shaped like a real turn but authored by nobody (stop-hook feedback, continuation-judge
# verdicts, background task notifications, compaction/continuation summaries). Left
# unfiltered these get attributed to the human and pollute themes/bridges (issue #15).
# Matched against the stripped head of each message at distill-render time; raw storage
# is untouched. Sources should strip their own injection patterns too (docs/SOURCES.md) —
# this is a backstop for the common harnesses, not a substitute for sender fidelity.
MESSAGE_META_MARKERS = (
    "Stop hook feedback:",
    "Claude evaluator determined",
    "[SYSTEM NOTIFICATION - NOT USER INPUT]",
    "This session is being continued from a previous conversation",
)


def is_meta_message(text: str) -> bool:
    head = strip_wrappers(text)[:200]
    return any(marker in head for marker in MESSAGE_META_MARKERS)


# Agent-process / session / tool chatter an assistant narrates about its OWN
# workflow — never domain knowledge. Deterministic backstop to the distill prompt
# (the LLM doesn't reliably obey the ignore instruction). High-precision: keyed on
# process predicates, not the subject, so a real decision like "the assistant should
# validate the bet" survives while "the assistant should pause and wait" is dropped.
PROCESS_NOTE_MARKERS = (
    "autonomous work", "autonomously", "no more autonomous", "further autonomous",
    "await clarification", "awaiting clarification", "waiting for clarification",
    "stop and await", "waiting for guidance",
    "pause and wait", "wait for the user", "waiting for the user", "wait for additional context",
    "blocked on user input", "provide guidance on how to proceed",
    "bypasspermissions", "session configured", "taskupdate", "should_continue",
)


def is_process_note(text: str) -> bool:
    """True for a note that is agent-process/state/tool chatter rather than domain
    knowledge. Substring match on the lowercased text; markers are distinctive to
    agent orchestration so precision stays high (err toward keeping)."""
    t = text.lower()
    return any(m in t for m in PROCESS_NOTE_MARKERS)
