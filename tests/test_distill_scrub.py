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


def test_scrubs_stripe_groq_google_keys():
    from alluvia.distill.scrub import scrub_secrets
    for secret in ("sk_live_" + "A" * 24,      # constructed, not literal —
                   "rk_test_" + "Z" * 22,      # a shipping file must never
                   "gsk_" + "G" * 30,          # contain a real-key-shaped string
                   "AIza" + "B" * 35):
        out = scrub_secrets(f"key is {secret} ok")
        assert secret not in out, secret
        assert "[REDACTED]" in out


def test_redact_removes_email_and_jwt_keeps_prose():
    from alluvia.distill.scrub import redact
    jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5"
    out = redact(f"ping dylan@alluvia.dev re {jwt} and sk-ant-api03-ABCdef123456 about the auth race")
    assert "dylan@alluvia.dev" not in out and "[EMAIL]" in out    # PII email redacted
    assert jwt not in out                                          # JWT redacted
    assert "sk-ant-api03-ABCdef123456" not in out                 # secrets still caught
    assert "auth race" in out                                     # prose preserved
