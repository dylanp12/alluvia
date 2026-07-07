from __future__ import annotations
import re

_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9\-]{10,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC )?PRIVATE KEY-----"),
]


def scrub_secrets(text: str) -> str:
    for pat in _PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


_WRAPPER_TAGS = ("local-command-caveat", "command-name", "command-message",
                 "command-args", "command-contents", "local-command-stdout",
                 "system-reminder")
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


# Harness meta-noise embedded INSIDE real sessions (stop-hook feedback,
# continuation-judge verdicts). Session-level filtering can't catch these —
# they produced the M2b gate's top theme. Matched against the stripped head
# of each message at distill-render time; raw storage is untouched.
MESSAGE_META_MARKERS = (
    "Stop hook feedback:",
    "Claude evaluator determined",
)


def is_meta_message(text: str) -> bool:
    head = strip_wrappers(text)[:200]
    return any(marker in head for marker in MESSAGE_META_MARKERS)
