"""Recall eval gate v0 — the quality bar retrieval changes must clear.

A golden query set over a synthetic corpus, scored deterministically
(hit@5 + MRR via cited note ids), with the shipped dense-only path as the
baseline every change must beat or match:

  - exact-match queries (error strings, paths, identifiers): hybrid = 100%
  - semantic queries: hybrid never regresses below dense-only
  - out-of-corpus queries: recall stays honestly empty — no junk answers

The corpus is synthetic on purpose (runs everywhere, no keys, no personal
data); a real-history golden set plugs into the same runner.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from alluvia.models import Note
from alluvia.recall import recall

BASE = datetime(2026, 1, 1)
EVAL_NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)   # frozen clock: temporal
# queries score the same forever, regardless of when the suite runs

CORPUS = [
    ("note:auth1", "cursor:s1", "auth token refresh race — two tabs rotate the same refresh token"),
    ("note:auth2", "claude-code:s2", "decided: rotate refresh tokens server-side, client keeps access token only"),
    ("note:auth3", "claude-code:s2", "fixed the rotation race in auth/refresh.py by pinning clock skew"),
    ("note:db1", "claude-code:s3", "worker pool dies with ECONNREFUSED 127.0.0.1:5432 on cold start"),
    ("note:db2", "cursor:s4", "force-honor DATABASE_URL over the config default; regression test added"),
    ("note:dep1", "claude-code:s5", "deploy cache layer invalidates on every push — dead end, reverted"),
    ("note:dep2", "cursor:s6", "deploy pipeline caching works with content-hash keys"),
]


class EvalEmbedder:
    """Topic buckets only — blind to identifiers, paths, and error strings,
    like a real embedder is in the tail. 8-dim to match the test schema."""
    dim = 8

    def embed(self, texts):
        out = []
        for t in texts:
            low = t.lower()
            if "auth" in low or "token" in low:
                v = [1.0, 0.0, 0.0, 0.0]
            elif "worker" in low or "config" in low:
                v = [0.0, 1.0, 0.0, 0.0]
            elif "deploy" in low or "cache" in low or "caching" in low:
                v = [0.0, 0.0, 1.0, 0.0]
            else:
                v = [0.0, 0.0, 0.0, 1.0]   # no topical signal: orthogonal to corpus
            out.append(v + [0.0] * 4)
        return out


@dataclass
class Golden:
    query: str
    expect: str | None          # note id, or None = must return nothing
    category: str               # semantic | exact | unanswerable


GOLDEN = [
    Golden("auth token refresh race", "note:auth1", "semantic"),
    Golden("how do we rotate refresh tokens", "note:auth2", "semantic"),
    Golden("deploy pipeline caching", "note:dep2", "semantic"),
    Golden("ECONNREFUSED", "note:db1", "exact"),
    Golden("auth/refresh.py", "note:auth3", "exact"),
    Golden("DATABASE_URL", "note:db2", "exact"),
    Golden("auth race in january", "note:auth1", "temporal"),
    Golden("worker crash since march", None, "temporal"),   # window is empty → refuse
    Golden("kubernetes ingress cert rotation", None, "unanswerable"),
    Golden("stripe webhook signature mismatch", None, "unanswerable"),
]


class _DenseOnly:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        if name == "search_notes_lexical":
            raise AttributeError(name)
        return getattr(self._inner, name)


def _seed(repo):
    emb = EvalEmbedder()
    notes = [Note(id=nid, user_id="local", session_id=sid, span_ref="msg:0",
                  kind="insight", text=text, created_at=BASE + timedelta(days=i))
             for i, (nid, sid, text) in enumerate(CORPUS)]
    repo.upsert_notes(notes)
    for n in notes:
        repo.set_embedding("local", n.id, emb.embed([n.text])[0])


def run_eval(repo, embedder, golden: list[Golden]) -> dict:
    """hit@5 and MRR per category from the cited note ids of recall hits."""
    per: dict[str, list[float]] = {}
    refusals_correct = 0
    refusals_total = 0
    for g in golden:
        hits = recall(repo, embedder, "local", g.query, now=EVAL_NOW)
        cited = [c for h in hits for c in h.cites]
        if g.expect is None:
            refusals_total += 1
            refusals_correct += (not hits)
            continue
        rr = 0.0
        for rank, nid in enumerate(list(dict.fromkeys(cited))[:5]):
            if nid == g.expect:
                rr = 1.0 / (rank + 1)
                break
        per.setdefault(g.category, []).append(rr)
    out = {cat: {"hit@5": sum(1.0 for r in rrs if r > 0) / len(rrs),
                 "mrr": sum(rrs) / len(rrs)} for cat, rrs in per.items()}
    out["refusal"] = refusals_correct / refusals_total if refusals_total else 1.0
    return out


def test_hybrid_beats_dense_baseline_on_the_golden_set(repo):
    _seed(repo)
    emb = EvalEmbedder()
    dense = run_eval(_DenseOnly(repo), emb, GOLDEN)
    hybrid = run_eval(repo, emb, GOLDEN)

    # the gate: exact-match queries are the feature — all of them, top-5
    assert hybrid["exact"]["hit@5"] == 1.0, f"exact-match must be total: {hybrid}"
    # time-scoped queries answer from inside the window, every time
    assert hybrid["temporal"]["hit@5"] == 1.0, f"temporal must hit: {hybrid}"
    # never regress semantics vs the shipped dense-only path
    assert hybrid["semantic"]["hit@5"] >= dense["semantic"]["hit@5"]
    assert hybrid["semantic"]["mrr"] >= dense["semantic"]["mrr"] - 1e-9
    # honest refusal: out-of-corpus queries stay empty in both modes
    assert hybrid["refusal"] == 1.0
    assert dense["refusal"] == 1.0
    # and the baseline really is weaker on exact-match — else this gate is fake
    # ("auth/refresh.py" may reach dense via its 'auth' topical leak; the error
    # string and the identifier must not)
    assert dense["exact"]["hit@5"] < hybrid["exact"]["hit@5"]


def test_eval_metrics_are_computed_from_citations(repo):
    _seed(repo)
    res = run_eval(repo, EvalEmbedder(), [GOLDEN[0]])
    assert res["semantic"]["hit@5"] in (0.0, 1.0)
    assert 0.0 <= res["semantic"]["mrr"] <= 1.0
