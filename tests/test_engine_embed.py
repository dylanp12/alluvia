from alluvia.engine.embed import FakeEmbedder


def test_fake_embedder_is_deterministic_and_fixed_dim():
    e = FakeEmbedder(dim=8)
    a = e.embed(["hello", "world"])
    b = e.embed(["hello", "world"])
    assert len(a) == 2 and len(a[0]) == 8
    assert a == b
    assert e.embed(["hello"])[0] != e.embed(["different"])[0]
