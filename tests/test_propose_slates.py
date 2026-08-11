"""Exposure logging: every surfaced selection records the FULL considered
pool — what was shown, what was scored but cut, at which rank, by which
policy. Without this, future ranking learns only the old heuristic's blind
spots (selection bias baked into the labels)."""
from datetime import datetime, timezone

from alluvia.engine.propose import POLICY_VERSION, _source_hash, candidates
from alluvia.models import Link, Note, Proposal, Theme


def _note(nid, text=None):
    return Note(id=nid, user_id="local", session_id=f"claude-code:s-{nid}",
                span_ref="msg:0", kind="problem", text=text or f"text {nid}",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _seed(repo):
    notes = [_note(f"note:{i}") for i in range(5)]
    repo.upsert_notes(notes)
    links = [Link(id=f"link:{i}", user_id="local", from_note_id=f"note:{i}",
                  to_note_id=f"note:{i + 1}", from_theme_id="t0",
                  to_theme_id="t1", kind="cross_source_surprise",
                  weight=3.0 - i * 0.5) for i in range(4)]
    repo.replace_links("local", links)
    repo.replace_themes("local", [Theme(
        id="th:1", user_id="local", label="Open Thing", summary="s",
        note_ids=["note:0"], session_count=3, source_count=1, status="open")])
    # link:1's material was already proposed-from -> considered but not selected
    grounding = [notes[1], notes[2]]
    repo.insert_proposal(Proposal(
        id="prop:old", user_id="local", created_at="2026-07-01T00:00:00+00:00",
        kind="link", source_ref="link:1", source_hash=_source_hash(grounding),
        title="T", text="X", next_step="n", cites=["note:1"], novelty_sim=None,
        feasibility=None, risk=None, model="m", outcome="kept"))


def test_surface_logs_full_considered_pool(repo):
    _seed(repo)
    cands = candidates(repo, "local", limit=5, surface="propose")
    assert cands
    slates = repo.list_slates("local", surface="propose")
    assert len(slates) == 1
    slate = slates[0]
    assert slate["policy_version"] == POLICY_VERSION
    items = slate["items"]
    link_items = [i for i in items if i["kind"] == "link"]
    assert len(link_items) == 4                      # full window, not just picks
    unselected = [i for i in link_items if not i["selected"]]
    assert [i["ref"] for i in unselected] == ["link:1"]      # dedup-cut, logged
    selected_refs = {i["ref"] for i in items if i["selected"]}
    assert selected_refs == {c.source_ref for c in cands}
    ranks = [i["rank"] for i in items]
    assert ranks == sorted(ranks)
    assert all("score" in i for i in items)
    theme_items = [i for i in items if i["kind"] == "theme"]
    assert theme_items and theme_items[0]["ref"] == "th:1"


def test_no_surface_no_slate(repo):
    _seed(repo)
    candidates(repo, "local", limit=5)
    assert repo.list_slates("local") == []
