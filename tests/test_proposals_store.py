from alluvia.models import Proposal, Theme


def _prop(pid="prop:a1b2c3d4", user="local", feasibility=4, outcome="pending"):
    return Proposal(id=pid, user_id=user, created_at="2026-07-02T00:00:00+00:00",
                    kind="link", source_ref="link:x", source_hash="h1",
                    title="T", text="body", next_step="do X",
                    cites=["note:1"], novelty_sim=0.42, feasibility=feasibility,
                    risk="low", model="m", outcome=outcome)


def test_insert_list_rate_roundtrip(repo):
    repo.insert_proposal(_prop())
    got = repo.list_proposals("local")                      # default: pending only
    assert [p.id for p in got] == ["prop:a1b2c3d4"]
    repo.rate_proposal("local", "prop:a1b2c3d4", "kept", note="great")
    assert repo.list_proposals("local") == []               # no longer pending
    rated = repo.list_proposals("local", outcomes=("kept",))
    assert rated[0].rating_note == "great" and rated[0].rated_at is not None


def test_user_isolation_and_source_hashes(repo):
    repo.insert_proposal(_prop())
    repo.insert_proposal(_prop(pid="prop:other", user="other"))
    assert repo.proposal_source_hashes("local") == {"h1"}
    assert [p.user_id for p in repo.list_proposals("local")] == ["local"]


def test_rejected_proposals_do_not_burn_material(repo):
    p = _prop(pid="prop:rej", outcome="rejected")
    p.source_hash = "h-rej"
    repo.insert_proposal(p)
    assert "h-rej" not in repo.proposal_source_hashes("local")   # retryable


def test_proposals_survive_refresh_rebuilds(repo):
    repo.insert_proposal(_prop())
    repo.replace_themes("local", [Theme(id="t0", user_id="local", label="L", summary="S")])
    repo.replace_links("local", [])
    assert len(repo.list_proposals("local")) == 1           # judgments are durable
