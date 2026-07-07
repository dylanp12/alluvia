from datetime import datetime, timedelta, timezone
from alluvia.models import Link, Note, Theme
from alluvia.llm.client import FakeLLM
from alluvia.engine.digest import due, generate

NOW = datetime(2026, 7, 4, tzinfo=timezone.utc)


class _Emb:
    dim = 8

    def embed(self, texts):
        return [[0.0, 1.0] + [0.0] * 6 for _ in texts]


class _Deps:
    def __init__(self, repo, gen=None, critic=None):
        self.repo = repo
        self.embedder = _Emb()
        self.gen_llm = gen or FakeLLM([])
        self.critic_llm = critic or FakeLLM([])


class _ExplodingLLM:
    def complete_json(self, s, u):
        raise RuntimeError("no budget")


def _note(nid, source="claude-code"):
    return Note(id=nid, user_id="local", session_id=f"{source}:s-{nid}",
                span_ref="msg:0", kind="idea", text=f"text {nid}",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _theme(tid, label, status="open", sessions=3):
    return Theme(id=tid, user_id="local", label=label, summary="s",
                 note_ids=[], first_seen=datetime(2025, 1, 1, tzinfo=timezone.utc),
                 last_seen=datetime(2026, 6, 1, tzinfo=timezone.utc),
                 session_count=sessions, source_count=1, status=status)


def _seed(repo, n_links=3):
    notes = [_note(f"note:{i}", "cursor" if i % 2 else "claude-code")
             for i in range(2 * n_links)]
    repo.upsert_notes(notes)
    links = [Link(id=f"link:{i}", user_id="local",
                  from_note_id=f"note:{2*i}", to_note_id=f"note:{2*i+1}",
                  from_theme_id="tA", to_theme_id="tB",
                  kind="cross_source_surprise", weight=3.0 - i * 0.1)
             for i in range(n_links)]
    repo.replace_links("local", links)
    repo.replace_themes("local", [_theme("tA", "Alpha", sessions=5),
                                  _theme("tB", "Beta", sessions=4),
                                  _theme("tC", "Gamma", sessions=3)])


def test_due_windows(repo):
    assert due(repo, "local", NOW, days=7)                      # no digest yet
    generate(repo, _Deps(repo), "local", NOW)
    assert not due(repo, "local", NOW + timedelta(days=3), days=7)
    assert due(repo, "local", NOW + timedelta(days=7), days=7)


def test_budgets_and_newness(repo):
    _seed(repo)
    _, items = generate(repo, _Deps(repo, gen=_ExplodingLLM()), "local", NOW)
    kinds = [i["kind"] for i in items]
    assert kinds.count("connection") == 2 and kinds.count("nudge") == 2
    assert kinds.count("proposal") == 0                          # slot degraded
    # second digest: shown links excluded (newness), third link surfaces
    _, items2 = generate(repo, _Deps(repo, gen=_ExplodingLLM()), "local",
                         NOW + timedelta(days=7))
    conn_refs2 = [i["ref"] for i in items2 if i["kind"] == "connection"]
    assert conn_refs2 == ["link:2"]                              # only unseen one


def test_nudge_cooldown_and_dismissal_learning(repo):
    _seed(repo, n_links=0)
    d1, items1 = generate(repo, _Deps(repo), "local", NOW)
    nudged1 = {i["ref"] for i in items1 if i["kind"] == "nudge"}
    assert nudged1 == {"tA", "tB"}                               # top 2 by session×span
    _, items2 = generate(repo, _Deps(repo), "local", NOW + timedelta(days=7))
    nudged2 = {i["ref"] for i in items2 if i["kind"] == "nudge"}
    assert nudged2 == {"tC"}                                     # cooldown on tA/tB
    # dismiss tC twice across digests -> excluded thereafter
    last = repo.latest_digest("local")[0]
    for it in repo.digest_items("local", last):
        if it["ref"] == "tC":
            repo.set_digest_item_outcome("local", last, it["n"], "dismissed")
    d3, items3 = generate(repo, _Deps(repo), "local", NOW + timedelta(days=21))
    for it in repo.digest_items("local", d3):
        if it["ref"] == "tC":
            repo.set_digest_item_outcome("local", d3, it["n"], "dismissed")
    _, items4 = generate(repo, _Deps(repo), "local", NOW + timedelta(days=35))
    assert all(i["ref"] != "tC" for i in items4 if i["kind"] == "nudge")


def test_digest_proposals_env_off_skips_generation(repo, monkeypatch):
    _seed(repo)
    monkeypatch.setenv("SIFT_DIGEST_PROPOSALS", "0")

    class _MustNotBeCalled:
        def complete_json(self, s, u):
            raise AssertionError("generation must not run when disabled")

    _, items = generate(repo, _Deps(repo, gen=_MustNotBeCalled()), "local", NOW)
    assert all(i["kind"] != "proposal" for i in items)
    assert items                                              # recall items still present


def test_mute_excludes_and_silence_records_empty(repo):
    _seed(repo, n_links=0)
    repo.mute_label("local", "Alpha")
    _, items = generate(repo, _Deps(repo), "local", NOW)
    assert all(i["theme_ref"] != "tA" for i in items)
    # empty corpus -> allowed silence: digest recorded with 0 items
    repo.replace_themes("local", [])
    did, items2 = generate(repo, _Deps(repo), "local", NOW + timedelta(days=7))
    assert items2 == [] and repo.latest_digest("local")[2] == 0
    assert not due(repo, "local", NOW + timedelta(days=8), days=7)   # stays quiet
