"""Exploration slot: every Nth digest trades one exploitation pick for a
below-cutoff connection — the label support a pure top-K policy can never
collect. Off by default cadence 4; env-tunable; 0 disables."""
from datetime import datetime, timezone

from alluvia.engine.digest import BUDGET_CONNECTIONS, generate
from alluvia.models import Link, Note, Theme

NOW = datetime(2026, 7, 17, tzinfo=timezone.utc)


def _seed(repo, n_links=110):
    notes = []
    for i in range(n_links + 1):
        notes.append(Note(
            id=f"note:{i:03d}", user_id="local",
            session_id=f"claude-code:s{i:03d}", span_ref="msg:0",
            kind="problem", text=f"problem number {i}",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    repo.upsert_notes(notes)
    repo.replace_themes("local", [Theme(
        id="theme:0", user_id="local", label="all", summary="s",
        note_ids=[n.id for n in notes], session_count=2, source_count=1,
        status="open")])
    links = [Link(id=f"link:{i:03d}", user_id="local",
                  from_note_id=f"note:{i:03d}", to_note_id=f"note:{i + 1:03d}",
                  from_theme_id="theme:0", to_theme_id="theme:0",
                  kind="cross_source_surprise", weight=500.0 - i)
             for i in range(n_links)]
    repo.replace_links("local", links)


def test_explore_slot_fires_on_cadence(repo, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DIGEST_PROPOSALS", "0")
    monkeypatch.setenv("ALLUVIA_DIGEST_EXPLORE_EVERY", "1")
    _seed(repo)
    _, items = generate(repo, None, "local", NOW)
    conns = [i for i in items if i["kind"] == "connection"]
    explore = [i for i in conns if i["snapshot"].startswith("EXPLORE:")]
    assert len(explore) == 1
    assert len(conns) <= BUDGET_CONNECTIONS          # traded, not added
    # the explored link comes from BEYOND the normal top-100 window
    assert explore[0]["ref"] >= "link:100"
    slates = repo.list_slates("local", surface="digest")
    assert len(slates) == 1
    flags = {i["ref"]: i.get("explore", False) for i in slates[0]["items"]}
    assert flags[explore[0]["ref"]] is True
    assert any(not v for v in flags.values())


def test_explore_disabled_with_zero(repo, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DIGEST_PROPOSALS", "0")
    monkeypatch.setenv("ALLUVIA_DIGEST_EXPLORE_EVERY", "0")
    _seed(repo)
    _, items = generate(repo, None, "local", NOW)
    assert not any(i["snapshot"].startswith("EXPLORE:") for i in items)
    assert repo.list_slates("local", surface="digest")   # slate still logged


def test_default_cadence_skips_first_digest(repo, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DIGEST_PROPOSALS", "0")
    monkeypatch.delenv("ALLUVIA_DIGEST_EXPLORE_EVERY", raising=False)
    _seed(repo)
    _, items = generate(repo, None, "local", NOW)      # ordinal 1, cadence 4
    assert not any(i["snapshot"].startswith("EXPLORE:") for i in items)
