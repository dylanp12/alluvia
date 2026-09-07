"""Shared tokenization for the lexical (exact-match) channel of hybrid
recall. One definition, two stores: the OSS FTS5 index and the cloud pg
store both match the queries developers actually paste — error strings,
snake_case identifiers, file paths — with identical semantics."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

_TOKEN = re.compile(r"[A-Za-z0-9_\-]{2,}")
_PATH_CHUNK = re.compile(r"[\w\-./\\]*[/\\][\w\-./\\]*")
STOPWORDS = {"the", "and", "for", "with", "that", "this", "from", "into",
             "your", "our", "how", "what", "when", "where", "why", "did",
             "does", "do", "we", "was", "is", "are", "or", "not", "near"}
# file extensions are not evidence: half a codebase "contains py"
EXT_STOPWORDS = {"py", "js", "ts", "tsx", "jsx", "md", "json", "yaml", "yml",
                 "toml", "txt", "html", "css", "rs", "go", "sh", "sql"}
MAX_TOKENS = 12


def lex_tokens(query: str) -> list[str]:
    """Lowercased literal tokens worth exact-matching, stopwords dropped."""
    return [t for t in (m.group(0).lower() for m in _TOKEN.finditer(query))
            if t not in STOPWORDS and t not in EXT_STOPWORDS][:MAX_TOKENS]


def required_count(tokens: list[str]) -> int:
    """How many tokens a note must contain to count as a lexical match:
    every token of a 1-2-token query, at least half of a longer one —
    one shared word is not an answer."""
    return len(tokens) if len(tokens) <= 2 else -(-len(tokens) // 2)


def path_anchors(query: str) -> list[str]:
    """File names inside path-shaped chunks ("auth/refresh.py" → "refresh.py").
    A path query is about THE FILE, not about every directory on the way."""
    out: list[str] = []
    for chunk in _PATH_CHUNK.findall(query):
        base = os.path.basename(chunk.replace("\\", "/").rstrip("/"))
        if base and base.lower() not in out:
            out.append(base.lower())
    return out


@dataclass
class LexQuery:
    tokens: list[str]
    anchors: list[str] = field(default_factory=list)
    required: int = 0

    def matches(self, text: str) -> bool:
        low = text.lower()
        if self.anchors:
            return all(a in low or os.path.splitext(a)[0] in low for a in self.anchors)
        return sum(1 for t in self.tokens if t in low) >= self.required


def lex_query(query: str) -> LexQuery:
    toks = lex_tokens(query)
    anchors = path_anchors(query)
    return LexQuery(tokens=toks, anchors=anchors,
                    required=0 if anchors else required_count(toks))
