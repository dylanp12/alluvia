from alluvia.llm.client import FakeLLM


def test_fake_llm_returns_canned_in_order():
    llm = FakeLLM([{"a": 1}, [1, 2, 3]])
    assert llm.complete_json("sys", "u1") == {"a": 1}
    assert llm.complete_json("sys", "u2") == [1, 2, 3]
