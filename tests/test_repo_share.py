"""Opt-in: a repository carries its own distilled memory in .alluvia/memory.jsonl."""
import json
from alluvia.models import Message, Note, RawSession, content_hash
from alluvia.repo_share import (import_share_if_changed, is_shared, set_shared, share_file,
                                write_share)
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo


def _seed(repo, root):
    ms = [Message(role="user", text="hi")]
    repo.upsert_session(RawSession(id="claude-code:s1", user_id="local", source="claude-code", native_id="s1",
                                   title="t", started_at=None, ended_at=None, messages=ms,
                                   content_hash=content_hash(ms), project=str(root), branch="main"))
    repo.upsert_notes([Note(id="n:a", user_id="local", session_id="claude-code:s1", span_ref="msg:0",
                            kind="decision", text="use postgres", created_at=None)])


def test_share_on_writes_project_relative_file(repo, tmp_path):
    root = tmp_path / "acme"; (root / ".git").mkdir(parents=True)
    _seed(repo, root)
    assert not is_shared(str(root))
    set_shared(str(root), True)
    assert is_shared(str(root))
    n = write_share(repo, "local", str(root))
    assert n == 1
    recs = [json.loads(l) for l in share_file(str(root)).read_text().splitlines()]
    assert all(r["project"] is None and r["project_rel"] == "." for r in recs if r["kind"] == "session")
    set_shared(str(root), False)
    assert not share_file(str(root)).exists() and not is_shared(str(root))


def test_import_share_binds_to_this_checkout_and_gates_on_hash(repo, tmp_path):
    root = tmp_path / "acme"; (root / ".git").mkdir(parents=True)
    _seed(repo, root); set_shared(str(root), True); write_share(repo, "local", str(root))
    clone = tmp_path / "clone"; (clone / ".git").mkdir(parents=True)
    (clone / ".alluvia").mkdir(); (clone / ".alluvia/memory.jsonl").write_bytes(share_file(str(root)).read_bytes())
    other = Repo(connect(str(tmp_path / "o.db"))); init_schema(other.conn, embed_dim=8)
    first = import_share_if_changed(other, "local", str(clone))
    assert first["notes_added"] == 1 and other.session_projects("local") == {"claude-code:s1": str(clone)}
    assert import_share_if_changed(other, "local", str(clone)) is None          # unchanged: skipped
    assert import_share_if_changed(other, "local", str(tmp_path / "nowhere")) is None
