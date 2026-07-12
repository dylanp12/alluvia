"""Kill-anytime contract polish: dashboard port handling, SIGTERM parity
with Ctrl-C, friendly refresh interruption."""
import threading

import pytest
from typer.testing import CliRunner

import alluvia.cli as cli
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo
from alluvia.web import looks_like_alluvia, pick_port, serve as make_server

runner = CliRunner()


def _repo(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn, embed_dim=8)
    return Repo(conn)


def test_probe_recognizes_running_dashboard(tmp_path):
    server = make_server(_repo(tmp_path), "local", port=0)    # ephemeral port
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    port = server.server_address[1]
    try:
        assert looks_like_alluvia(port) is True
        assert looks_like_alluvia(port + 1) is False          # nothing there
    finally:
        server.shutdown()
        server.server_close()


def test_pick_port_walks_past_busy(tmp_path):
    server = make_server(_repo(tmp_path), "local", port=0)
    busy = server.server_address[1]
    try:
        got = pick_port(busy)
        assert got != busy
    finally:
        server.server_close()


def test_sigterm_handler_reuses_ctrl_c_path():
    with pytest.raises(KeyboardInterrupt):
        cli._sigterm(15, None)


def test_refresh_ctrl_c_is_friendly_and_resumable(tmp_path, monkeypatch):
    monkeypatch.setenv("ALLUVIA_DB", str(tmp_path / "t.db"))
    monkeypatch.setattr(cli, "EMBED_DIM", 8)

    class Interrupting:
        def refresh(self, user, reporter=None):
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build_engine",
                        lambda repo, reporter=None: Interrupting())
    r = runner.invoke(cli.app, ["refresh"])
    assert r.exit_code == 130
    assert "paused" in r.output and "resume" in r.output
    assert "Traceback" not in r.output
