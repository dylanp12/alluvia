"""Compile the store into a portable graph bundle (contract.json +
gzipped JSONL). Your data, exportable: sessions, notes, themes, and links
become typed nodes and provenance-carrying events; proposals ride along as
judgments unless excluded. Deterministic output: same store, same bytes.

The bundle format is versioned; ONTOLOGY_HASH fingerprints the vocabulary
this exporter emits and is checked by downstream consumers."""
from __future__ import annotations
import gzip
import hashlib
import json
import os
from pathlib import Path

from alluvia.models import Note, to_utc
from alluvia.store.repo import Repo

BUNDLE_VERSION = "0.1.0"
ONTOLOGY_HASH = "a02ef9faedd40a31f70e6b48f09cfac2f195c6ed5fe7ddb47b8d07744e331a99"

NOTE_KIND_TO_NODE = {"idea": "Idea", "decision": "Decision",
                      "question": "Question", "problem": "Problem",
                      "insight": "Lesson"}


def _iso(dt) -> str | None:
    return to_utc(dt).isoformat() if dt else None


def _event_id(event_type: str, relation: str | None,
              participants: list[list[str]], evidence: list[str]) -> str:
    payload = json.dumps([event_type, relation, participants, evidence],
                         sort_keys=True)
    return "ev:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _event(event_type: str, participants: list[list[str]], *,
           relation: str | None = None, event_time=(None, None),
           extraction: dict | None = None, evidence: list[str] | None = None,
           attrs: dict | None = None) -> dict:
    evidence = evidence or []
    return {
        "event_id": _event_id(event_type, relation, participants, evidence),
        "event_type": event_type, "relation": relation,
        "participants": participants,
        "event_time": list(event_time), "derived_at": None,
        "extraction": extraction or {"run_id": None, "model": None,
                                      "pipeline_version": None,
                                      "confidence": None},
        "evidence": evidence, "human_confirmed": False, "derivation": [],
        "attrs": attrs or {},
    }


def _note_event(n: Note, run_models: dict[str, str | None]) -> dict:
    return _event(
        "observation", [["observed", n.id], ["session", n.session_id]],
        event_time=(_iso(n.created_at), None),
        extraction={"run_id": n.run_id,
                     "model": run_models.get(n.run_id) if n.run_id else None,
                     "pipeline_version": n.pipeline_version,
                     "confidence": None},
        evidence=[f"{n.session_id}/{n.span_ref}"] if n.span_ref
        else [n.session_id])


def build_bundle(repo: Repo, user_id: str, now_iso: str | None = None,
                 include_judgments: bool = True):
    """-> (manifest, nodes, events, judgments|None), all deterministic for a
    given store state and now_iso."""
    manifest = {"contract_version": BUNDLE_VERSION,
                "ontology_hash": ONTOLOGY_HASH, "generator": "alluvia",
                "user_scope": "local", "created_at": now_iso}
    nodes: list[dict] = []
    events: list[dict] = []

    for s in repo.list_sessions(user_id):
        nodes.append({"id": s.id, "type": "Session", "label": s.title or s.id,
                       "attrs": {"source": s.source,
                                  "started_at": _iso(s.started_at),
                                  "ended_at": _iso(s.ended_at)}})

    run_models = {r.id: r.model for r in repo.list_extraction_runs(user_id)}
    notes = repo.get_notes(user_id)
    for n in notes:
        nodes.append({"id": n.id,
                       "type": NOTE_KIND_TO_NODE.get(n.kind, "Claim"),
                       "label": n.text, "attrs": {}})
        events.append(_note_event(n, run_models))

    note_ids = {n.id for n in notes}
    for t in repo.list_themes(user_id):
        nodes.append({"id": t.id, "type": "Theme", "label": t.label,
                       "attrs": {"status": t.status, "summary": t.summary}})
        for nid in t.note_ids:
            if nid in note_ids:
                events.append(_event(
                    "inference", [["subject", nid], ["object", t.id]],
                    relation="PART_OF"))

    for link in repo.list_links(user_id):
        if link.from_note_id not in note_ids or link.to_note_id not in note_ids:
            continue
        attrs = {"weight": link.weight}
        if link.why:
            attrs["why"] = link.why
        events.append(_event(
            "inference",
            [["subject", link.from_note_id], ["object", link.to_note_id]],
            relation="open:" + link.kind.replace("_", "-"), attrs=attrs))

    judgments = None
    if include_judgments:
        judgments = []
        for p in repo.list_proposals(
                user_id, outcomes=("pending", "kept", "dismissed", "rejected")):
            judgments.append({
                "id": p.id, "kind": "proposal", "outcome": p.outcome,
                "created_at": p.created_at, "title": p.title, "text": p.text,
                "next_step": p.next_step, "cites": p.cites,
                "source_ref": p.source_ref, "model": p.model,
                "reject_reason": p.reject_reason, "rated_at": p.rated_at,
                "rated_via": p.rated_via})

    return manifest, nodes, events, judgments


def _dump(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def _write_jsonl_gz(path: Path, rows: list[dict], key: str) -> None:
    with open(path, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
            for row in sorted(rows, key=lambda r: r[key]):
                gz.write((_dump(row) + "\n").encode("utf-8"))


def write_bundle(dest, manifest: dict, nodes: list[dict], events: list[dict],
                 judgments: list[dict] | None = None) -> None:
    dest = Path(dest)
    os.makedirs(dest, exist_ok=True)
    (dest / "contract.json").write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    _write_jsonl_gz(dest / "nodes.jsonl.gz", nodes, "id")
    _write_jsonl_gz(dest / "events.jsonl.gz", events, "event_id")
    if judgments is not None:
        _write_jsonl_gz(dest / "judgments.jsonl.gz", judgments, "id")
