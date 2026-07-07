from alluvia.models import Proposal


def _prop(pid="prop:x"):
    return Proposal(id=pid, user_id="local", created_at="2026-07-03T00:00:00+00:00",
                    kind="link", source_ref="l", source_hash=pid, title="T", text="b",
                    next_step="n", cites=["note:1"], novelty_sim=None, feasibility=4,
                    risk=None, model="m")


def test_rated_via_defaults_cli_and_records_mcp(repo):
    repo.insert_proposal(_prop("prop:a"))
    repo.insert_proposal(_prop("prop:b"))
    repo.rate_proposal("local", "prop:a", "kept")                 # default via
    repo.rate_proposal("local", "prop:b", "dismissed", via="mcp")
    a = repo.get_proposal("local", "prop:a")
    b = repo.get_proposal("local", "prop:b")
    assert a.rated_via == "cli" and b.rated_via == "mcp"
