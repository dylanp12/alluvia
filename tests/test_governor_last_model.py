"""After a successful call the Governor remembers which model served it —
extraction provenance depends on this being observable."""
from alluvia.llm.governor import Governor


class _Ok:
    def complete_json(self, system, user):
        return {"ok": True}


class _RateLimited:
    def complete_json(self, system, user):
        exc = Exception("429")
        exc.status_code = 429
        raise exc


def test_last_model_none_before_any_call():
    g = Governor("test", [("m1", _Ok())], patience=0.0, sleeper=lambda s: None)
    assert g.last_model is None


def test_last_model_set_on_success():
    g = Governor("test", [("m1", _Ok())], patience=0.0, sleeper=lambda s: None)
    g.complete_json("s", "u")
    assert g.last_model == "m1"


def test_last_model_reflects_fallthrough():
    g = Governor("test", [("m1", _RateLimited()), ("m2", _Ok())],
                 patience=0.0, sleeper=lambda s: None)
    g.complete_json("s", "u")
    assert g.last_model == "m2"
