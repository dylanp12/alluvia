from alluvia.engine.engine import Engine, scaled_min_cluster_size


def test_formula_scales_with_corpus_and_clamps():
    assert scaled_min_cluster_size(100) == 2      # floor
    assert scaled_min_cluster_size(1931) == 4     # current corpus
    assert scaled_min_cluster_size(10000) == 8    # ceiling


def test_engine_none_means_scaled_explicit_wins(repo):
    from alluvia.engine.embed import FakeEmbedder
    from alluvia.llm.client import FakeLLM
    auto = Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=None)
    assert auto._min_cluster_size(1931) == 4
    fixed = Engine(repo, FakeEmbedder(dim=8), FakeLLM([]), min_cluster_size=2)
    assert fixed._min_cluster_size(1931) == 2
