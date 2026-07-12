"""`alluvia doctor`: diagnoses the whole installation and REPAIRS what is
safe to repair (zero-data-loss, idempotent). Raw data and judgments are
never touched by auto-repair."""
import os
import sqlite3

from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia.doctor import rebuild_derived, run_doctor
from alluvia.models import Message, Note, Proposal, RawSession, content_hash
from alluvia.store.db import init_schema
from alluvia.store.repo import Repo

runner = CliRunner()


def _by(findings, name):
    return next(f for f in findings if f.name == name)


def _seed(repo):
    msgs = [Message(role="user", text="auth token service")]
    repo.upsert_session(RawSession(
        id="claude-code:s1", user_id="local", source="claude-code",
        native_id="s1", title="t", started_at=None, ended_at=None,
        messages=msgs, content_hash=content_hash(msgs)))
    repo.upsert_notes([Note(id="note:1", user_id="local",
                            session_id="claude-code:s1", span_ref="msg:0",
                            kind="idea", text="auth token service",
                            created_at=None)])
    repo.set_embedding("local", "note:1", [0.0] * 8)
    repo.insert_proposal(Proposal(
        id="prop:1", user_id="local", created_at="2026-07-12T00:00:00+00:00",
        kind="theme", source_ref="theme:0", source_hash="h", title="T",
        text="keep me", next_step="s", cites=["note:1"],
        novelty_sim=0.5, feasibility=4, risk=None, model="m"))


def test_orphaned_embeddings_pruned_and_idempotent(repo):
    _seed(repo)
    repo.conn.execute(
        "INSERT INTO note_embeddings VALUES ('local','note:ghost',8,x'00')")
    repo.conn.commit()
    fs = run_doctor(repo)
    assert _by(fs, "orphaned embeddings").status == "repaired"
    left = {r[0] for r in repo.conn.execute(
        "SELECT note_id FROM note_embeddings").fetchall()}
    assert left == {"note:1"}                       # real row untouched
    assert _by(run_doctor(repo), "orphaned embeddings").status == "ok"


def test_dangling_links_pruned(repo):
    _seed(repo)
    repo.conn.execute(
        "INSERT INTO links VALUES ('l1','local','note:1','note:gone',"
        "'t0','t1','surprise',0.9,NULL)")
    repo.conn.commit()
    assert _by(run_doctor(repo), "dangling links").status == "repaired"
    assert repo.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0] == 0


def test_check_only_reports_without_touching(repo):
    repo.conn.execute(
        "INSERT INTO note_embeddings VALUES ('local','note:ghost',8,x'00')")
    repo.conn.commit()
    fs = run_doctor(repo, check_only=True)
    f = _by(fs, "orphaned embeddings")
    assert f.status == "warn" and f.repairable
    assert repo.conn.execute(
        "SELECT COUNT(*) FROM note_embeddings").fetchone()[0] == 1


def test_bogus_cooldown_reset_but_sane_cooldowns_kept(repo):
    repo.llm_health_save("groq", "bad", {"cooldown_until": 10 ** 12})
    repo.llm_health_save("groq", "fine", {"cooldown_until": 0.0})
    assert _by(run_doctor(repo), "llm cooldowns").status == "repaired"
    assert repo.llm_health_load("groq", "bad")["cooldown_until"] == 0
    assert _by(run_doctor(repo), "llm cooldowns").status == "ok"


def test_wal_enabled_on_legacy_store(tmp_path):
    db = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=DELETE")
    init_schema(conn, embed_dim=8)
    repo = Repo(conn)
    assert _by(run_doctor(repo), "wal journal").status == "repaired"
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_config_perms_tightened(repo, tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[llm]\nprovider = "groq"\n')
    os.chmod(cfg, 0o644)
    monkeypatch.setenv("ALLUVIA_CONFIG", str(cfg))
    assert _by(run_doctor(repo), "config permissions").status == "repaired"
    assert oct(os.stat(cfg).st_mode & 0o777) == "0o600"


def test_stale_pending_flag_removed_but_valid_flag_kept(repo, tmp_path,
                                                        monkeypatch):
    flag = tmp_path / "digest-pending"
    flag.write_text("1")
    monkeypatch.setenv("ALLUVIA_PENDING_FLAG", str(flag))
    # no digest in store -> stale -> removed
    assert _by(run_doctor(repo), "digest flag").status == "repaired"
    assert not flag.exists()
    # with a digest present the flag is legitimate -> kept
    repo.insert_digest("local", "2026-07-12T00:00:00+00:00",
                       [{"kind": "connection", "ref": None, "theme_ref": None,
                         "snapshot": "s"}])
    flag.write_text("1")
    assert _by(run_doctor(repo), "digest flag").status == "ok"
    assert flag.exists()


def test_judgments_and_raw_survive_all_repairs(repo):
    _seed(repo)
    repo.conn.execute(
        "INSERT INTO note_embeddings VALUES ('local','note:ghost',8,x'00')")
    repo.conn.commit()
    run_doctor(repo)
    assert repo.get_proposal("local", "prop:1").text == "keep me"
    assert len(repo.list_sessions("local")) == 1


def test_rebuild_derived_preserves_raw_and_judgments(repo):
    _seed(repo)
    counts = rebuild_derived(repo)
    assert counts["notes"] == 1
    assert repo.conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 0
    assert repo.conn.execute(
        "SELECT COUNT(*) FROM note_embeddings").fetchone()[0] == 0
    assert repo.conn.execute(
        "SELECT COUNT(*) FROM distilled_sessions").fetchone()[0] == 0
    assert len(repo.list_sessions("local")) == 1          # raw intact
    assert repo.get_proposal("local", "prop:1") is not None   # judgments intact
    # embed_dim must survive — the store stays usable
    assert repo.conn.execute(
        "SELECT value FROM meta WHERE key='embed_dim'").fetchone()[0] == "8"


def test_live_check_uses_injected_llm(repo):
    class Ok:
        model = "m"
        def complete_json(self, s, u):
            return {"ok": True}

    class Boom:
        model = "m"
        def complete_json(self, s, u):
            raise RuntimeError("nope")

    assert _by(run_doctor(repo, live=True, llm=Ok()),
               "provider round-trip").status == "ok"
    assert _by(run_doctor(repo, live=True, llm=Boom()),
               "provider round-trip").status == "fail"
    assert all(f.name != "provider round-trip" for f in run_doctor(repo))


def test_missing_provider_key_is_a_failure_with_remedy(repo, tmp_path,
                                                       monkeypatch):
    monkeypatch.setenv("ALLUVIA_CONFIG", str(tmp_path / "none.toml"))
    for env in ("GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    from alluvia import config
    config.reset_toml_cache()
    f = _by(run_doctor(repo), "provider key")
    assert f.status == "fail" and "init" in f.remedy


def test_doctor_cli_exit_codes_and_output(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("GROQ_API_KEY", "k")
    monkeypatch.setattr(cli, "EMBED_DIM", 8)
    r = runner.invoke(cli.app, ["doctor"])
    assert "wal journal" in r.output
    # seed an orphan, then: --check flags it (exit 1) but repair run fixes (exit 0)
    repo = cli._repo()
    repo.conn.execute(
        "INSERT INTO note_embeddings VALUES ('local','note:ghost',8,x'00')")
    repo.conn.commit()
    rc = runner.invoke(cli.app, ["doctor", "--check"])
    assert rc.exit_code == 1
    rr = runner.invoke(cli.app, ["doctor"])
    assert rr.exit_code == 0
    assert "repaired" in rr.output
