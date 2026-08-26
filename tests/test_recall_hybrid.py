"""Hybrid recall: exact-match rescue + rank fusion, still zero LLM spend.

The customer-visible behavior: a query the embedder is blind to (an error
string, a path, an identifier) must still find the note that contains it.
"""
from __future__ import annotations
from datetime import datetime

from alluvia.models import Note
from alluvia.recall import recall

BASE = datetime(2026, 1, 1)


class TopicEmbedder:
    """auth-ish text → e0, infra-ish text → e1, everything else → e2.

    Deliberately blind to identifiers/error strings: 'ECONNREFUSED' in a
    query reads as 'everything else', orthogonal to every seeded note —
    dense search alone cannot find it.
    """
    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            if "auth" in low or "token" in low:
                v = [1.0, 0.0, 0.0]
            elif "worker" in low or "deploy" in low:
                v = [0.0, 1.0, 0.0]
            else:
                v = [0.0, 0.0, 1.0]
            out.append(v + [0.0] * 5)
        return out


def _seed(repo):
    notes = [
        Note(id="note:err", user_id="local", session_id="claude-code:s1",
             span_ref="msg:0", kind="problem",
             text="worker pool dies with ECONNREFUSED 127.0.0.1:5432 on cold start",
             created_at=BASE),
        Note(id="note:a1", user_id="local", session_id="cursor:s2",
             span_ref="msg:0", kind="insight",
             text="auth token rotation lock missing", created_at=BASE),
        Note(id="note:a2", user_id="local", session_id="cursor:s3",
             span_ref="msg:0", kind="idea",
             text="auth token expiry parsing tweak", created_at=BASE),
    ]
    repo.upsert_notes(notes)
    emb = TopicEmbedder()
    for n in notes:
        repo.set_embedding("local", n.id, emb.embed([n.text])[0])


class _DenseOnly:
    """The same repo with the lexical channel hidden — how recall must
    behave on stores that don't offer it (e.g. the cloud pg path today)."""

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name == "search_notes_lexical":
            raise AttributeError(name)
        return getattr(self._inner, name)


def test_exact_match_query_the_embedder_misses_is_rescued(repo):
    _seed(repo)
    # dense-only: the query embeds orthogonally to every note — nothing found
    assert recall(_DenseOnly(repo), TopicEmbedder(), "local", "ECONNREFUSED") == []
    # hybrid: the lexical channel carries it
    hits = recall(repo, TopicEmbedder(), "local", "ECONNREFUSED")
    assert hits, "lexical channel must rescue the exact-match query"
    assert "note:err" in {c for h in hits for c in h.cites}


def test_recall_degrades_to_dense_without_the_lexical_channel(repo):
    _seed(repo)
    hits = recall(_DenseOnly(repo), TopicEmbedder(), "local", "auth token rotation")
    assert hits and any("note:a1" in h.cites for h in hits)


def test_note_matched_by_both_channels_outranks_dense_only_tie(repo):
    _seed(repo)
    # a1 and a2 embed identically (both auth-ish); only a1 matches the
    # query's tokens 'rotation lock' — fusion must break the tie toward a1
    hits = recall(repo, TopicEmbedder(), "local", "auth rotation lock")
    note_hits = [h for h in hits if h.kind == "note"]
    assert note_hits and note_hits[0].cites == ["note:a1"]


def test_unrelated_junk_is_still_excluded(repo):
    _seed(repo)
    # semantically orthogonal AND no token overlap → honest empty result
    assert recall(repo, TopicEmbedder(), "local", "kubernetes ingress annotations") == []
