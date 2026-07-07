from alluvia.models import Note
from alluvia.llm.client import FakeLLM
from alluvia.engine.label import label_cluster


def _n(text):
    return Note(id="note:" + text[:4], user_id="local",
                session_id="claude-code:s1", span_ref="msg:0",
                kind="idea", text=text, created_at=None)


def test_label_cluster_returns_label_and_summary():
    llm = FakeLLM([{"label": "Auth design", "summary": "Recurring auth-architecture thinking."}])
    label, summary = label_cluster(llm, [_n("token service"), _n("middleware auth")])
    assert label == "Auth design"
    assert "auth" in summary.lower()
