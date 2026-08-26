"""Shared tokenization for the lexical (exact-match) channel of hybrid
recall. One definition, two stores: the OSS FTS5 index and the cloud pg
store both match the queries developers actually paste — error strings,
snake_case identifiers, file paths — with identical semantics."""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z0-9_\-]{2,}")
STOPWORDS = {"the", "and", "for", "with", "that", "this", "from", "into",
             "your", "our", "how", "what", "when", "where", "why", "did",
             "does", "do", "we", "was", "is", "are", "or", "not", "near"}
MAX_TOKENS = 12


def lex_tokens(query: str) -> list[str]:
    """Lowercased literal tokens worth exact-matching, stopwords dropped."""
    return [t for t in (m.group(0).lower() for m in _TOKEN.finditer(query))
            if t not in STOPWORDS][:MAX_TOKENS]


def required_count(tokens: list[str]) -> int:
    """How many tokens a note must contain to count as a lexical match:
    every token of a 1-2-token query, at least half of a longer one —
    one shared word is not an answer."""
    return len(tokens) if len(tokens) <= 2 else -(-len(tokens) // 2)
