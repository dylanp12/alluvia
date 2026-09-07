from alluvia.lexical import lex_tokens, lex_query


def test_extension_tokens_are_not_terms():
    assert lex_tokens("alluvia/llm/governor.py") == ["alluvia", "llm", "governor"]
    assert "py" not in lex_tokens("governor.py breaker")


def test_path_query_anchors_on_the_file_name():
    q = lex_query("alluvia/llm/governor.py")
    assert q.anchors == ["governor.py"]
    assert q.matches("fixed backoff in governor.py yesterday")
    assert q.matches("the governor module retries")          # stem alone counts
    assert not q.matches("we use llm calls in alluvia")      # shared segments are not the file


def test_plain_queries_keep_the_majority_rule():
    q = lex_query("auth rotation lock missing")
    assert q.anchors == [] and q.required == 2
    assert q.matches("auth token rotation lacks lock")
    assert not q.matches("rotation of the on-call schedule")
