import pytest
from alluvia import config as _config
from alluvia.store.db import connect, init_schema
from alluvia.store.repo import Repo

EMBED_DIM = 8


@pytest.fixture(autouse=True)
def _fresh_config_cache():
    _config.reset_toml_cache()
    yield
    _config.reset_toml_cache()


@pytest.fixture(autouse=True)
def _no_real_cloud_session(tmp_path, monkeypatch):
    """Tests must never read the developer's real sign-in: with no session file,
    every cloud path is the honest 'not signed in' result and never touches the
    network. Tests that need a session set ALLUVIA_CLOUD_SESSION themselves."""
    monkeypatch.setenv("ALLUVIA_CLOUD_SESSION", str(tmp_path / "no-cloud-session.json"))


@pytest.fixture
def repo(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn, embed_dim=EMBED_DIM)
    return Repo(conn)
