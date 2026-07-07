from __future__ import annotations
from alluvia.llm.client import LLM
from alluvia.models import Note

_SYSTEM = (
    "You name and summarize a cluster of a developer's notes. "
    "Return JSON {\"label\": short title (<=6 words), "
    "\"summary\": 1-2 sentence digest of the theme}."
)


def label_cluster(llm: LLM, notes: list[Note]) -> tuple[str, str]:
    body = "\n".join(f"- {n.text}" for n in notes[:40])
    result = llm.complete_json(_SYSTEM, body)
    if isinstance(result, dict):
        return result.get("label", "Untitled"), result.get("summary", "")
    return "Untitled", ""
