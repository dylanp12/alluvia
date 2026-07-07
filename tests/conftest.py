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


@pytest.fixture
def repo(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn, embed_dim=EMBED_DIM)
    return Repo(conn)
