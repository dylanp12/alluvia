from alluvia.distill.scrub import scrub_secrets


def test_scrubs_common_secret_shapes():
    text = (
        "key sk-ant-api03-ABCdef123456 and AKIAIOSFODNN7EXAMPLE plus "
        "ghp_1234567890abcdefghijABCDEFGHIJ1234 done"
    )
    out = scrub_secrets(text)
    assert "sk-ant-api03-ABCdef123456" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "ghp_1234567890abcdefghijABCDEFGHIJ1234" not in out
    assert out.count("[REDACTED]") == 3
    assert "done" in out
