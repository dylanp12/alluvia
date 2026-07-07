from __future__ import annotations
import logging
from collections import defaultdict

log = logging.getLogger(__name__)


def scaled_min_cluster_size(n_notes: int) -> int:
    """Corpus-scaled HDBSCAN min_cluster_size (M2b gate: 434 themes / 1,931
    notes was too fragmented). Floor 2, ceiling 8."""
    return max(2, min(8, n_notes // 400))
from alluvia.llm.client import LLM
from alluvia.engine.embed import Embedder
from alluvia.engine.cluster import cluster
from alluvia.engine.label import label_cluster
from alluvia.distill.distiller import Distiller
from alluvia.models import Link, Note, Theme
from alluvia.store.repo import Repo
from datetime import datetime, timezone
from alluvia.engine.link import compute_links
from alluvia.engine.track import classify_status


class Engine:
    def __init__(self, repo: Repo, embedder: Embedder, llm: LLM,
                 min_cluster_size: int | None = None):
        self.repo = repo
        self.embedder = embedder
        self.llm = llm
        self.distiller = Distiller(llm)
        self.min_cluster_size = min_cluster_size    # None -> corpus-scaled

    def _min_cluster_size(self, n_notes: int) -> int:
        if self.min_cluster_size is not None:
            return self.min_cluster_size
        return scaled_min_cluster_size(n_notes)

    def refresh(self, user_id: str, now: datetime | None = None) -> None:
        self._distill_new(user_id)
        self._embed_new(user_id)
        self._rebuild_themes(user_id, now or datetime.now(timezone.utc))
        self._build_links(user_id)

    class _RepoCache:
        def __init__(self, repo):
            self.repo = repo
        def get(self, user_id, h):
            return self.repo.get_status_cache(user_id, h)
        def set(self, user_id, h, s):
            self.repo.set_status_cache(user_id, h, s)

    MAX_CONSECUTIVE_FAILURES = 5

    def _distill_new(self, user_id: str) -> None:
        # union: marker table is authoritative; notes-derived set backfills
        # sessions distilled before the marker existed. Both version-aware:
        # a PIPELINE_VERSION bump re-distills older material.
        from alluvia.config import PIPELINE_VERSION
        done = self.repo.distilled_session_ids(user_id) | \
            self.repo.session_ids_with_notes(user_id, version=PIPELINE_VERSION)
        todo = [s for s in self.repo.list_sessions(user_id) if s.id not in done]
        consecutive = 0
        for n, s in enumerate(todo, 1):
            try:
                self.repo.upsert_notes(self.distiller.distill(s))
                self.repo.mark_distilled(user_id, s.id)   # zero notes counts as done
                consecutive = 0
            except Exception as e:
                if "json_validate_failed" in str(e):
                    # content hijacked the extractor (meta/judge transcripts):
                    # semantically a zero-knowledge session — mark done, move on
                    log.info("distill: %s yielded no valid JSON (meta content); "
                             "marking as zero-note session", s.id)
                    self.repo.mark_distilled(user_id, s.id)
                    consecutive = 0
                    continue
                consecutive += 1
                log.warning("distill failed for %s (%s) [%d consecutive]",
                            s.id, e, consecutive)
                if consecutive >= self.MAX_CONSECUTIVE_FAILURES:
                    log.warning("aborting distill after %d consecutive failures; "
                                "%d/%d sessions done — re-run refresh to resume",
                                consecutive, n, len(todo))
                    break
            if n % 50 == 0:
                log.info("distill progress: %d/%d sessions", n, len(todo))

    def _embed_new(self, user_id: str) -> None:
        have = self.repo.note_ids_with_embeddings(user_id)
        todo = [n for n in self.repo.get_notes(user_id) if n.id not in have]
        if not todo:
            return
        vecs = self.embedder.embed([n.text for n in todo])
        for n, v in zip(todo, vecs):
            self.repo.set_embedding(user_id, n.id, v)

    def _rebuild_themes(self, user_id: str, now: datetime) -> None:
        notes = {n.id: n for n in self.repo.get_notes(user_id)}
        ids, mat = self.repo.all_embeddings(user_id)
        if not ids:
            self.repo.replace_themes(user_id, [])
            return
        labels = cluster([list(row) for row in mat], self._min_cluster_size(len(ids)))
        groups: dict[int, list[str]] = defaultdict(list)
        for nid, lab in zip(ids, labels):
            if lab != -1:
                groups[lab].append(nid)
        cache = Engine._RepoCache(self.repo)
        themes: list[Theme] = []
        from alluvia.engine.track import _status_hash
        for lab, note_ids in sorted(groups.items()):
            members = [notes[i] for i in note_ids if i in notes]
            probe = Theme(id="", user_id=user_id, label="", summary="", note_ids=note_ids)
            content_key = _status_hash(probe, notes)
            cached = self.repo.get_label_cache(user_id, content_key)
            if cached:
                label, summary = cached
            else:
                try:
                    label, summary = label_cluster(self.llm, members)
                    self.repo.set_label_cache(user_id, content_key, label, summary)
                except Exception as e:
                    log.warning("label failed for cluster %s (%s)", lab, e)
                    # fallback NOT cached: retried on the next refresh
                    label, summary = members[0].text[:40] if members else "Untitled", ""
            sids = {m.session_id for m in members}
            sources = {m.session_id.split(":", 1)[0] for m in members}
            times = [m.created_at for m in members if m.created_at]
            theme = Theme(
                id=f"theme:{lab}", user_id=user_id, label=label, summary=summary,
                note_ids=note_ids, first_seen=min(times) if times else None,
                last_seen=max(times) if times else None,
                session_count=len(sids), source_count=len(sources))
            try:
                theme.status = classify_status(user_id, theme, notes, self.llm,
                                               cache, now=now)
            except Exception as e:
                log.warning("status classification failed for %s (%s)", label, e)
                theme.status = "unknown"
            themes.append(theme)
        self.repo.replace_themes(user_id, themes)

    def _build_links(self, user_id: str) -> None:
        notes = {n.id: n for n in self.repo.get_notes(user_id)}
        ids, mat = self.repo.all_embeddings(user_id)
        # embeddings are derived storage and can drift (e.g. after a corpus
        # purge) — keep only rows whose note still exists, never crash
        keep = [i for i, nid in enumerate(ids) if nid in notes]
        if len(keep) != len(ids):
            log.warning("ignoring %d orphaned embeddings", len(ids) - len(keep))
            ids = [ids[i] for i in keep]
            mat = mat[keep] if len(keep) else mat[:0]
        note_theme: dict[str, str] = {}
        for t in self.repo.list_themes(user_id):
            for nid in t.note_ids:
                note_theme[nid] = t.id
        links = compute_links(user_id, notes, ids, mat, note_theme)
        self.repo.replace_links(user_id, links)

    def themes(self, user_id: str) -> list[Theme]:
        return self.repo.list_themes(user_id)

    def ask(self, user_id: str, query: str) -> Theme | None:
        hits = self.repo.search_notes(user_id, self.embedder.embed([query])[0], k=1)
        if not hits:
            return None
        best_note = hits[0][0]
        for t in self.repo.list_themes(user_id):
            if best_note in t.note_ids:
                return t
        return None

    _WHY_SYSTEM = ('Explain in ONE short sentence why these two developer notes are '
                   'related. Return JSON {"why": "..."}.')

    def connections(self, user_id: str, limit: int = 20) -> list[Link]:
        return self.repo.list_links(user_id, limit=limit)

    def explain(self, user_id: str, link: Link) -> str | None:
        """Fill a link's `why` lazily; cache it. Returns why (None on LLM error)."""
        if link.why:
            return link.why
        notes = {n.id: n for n in self.repo.get_notes(user_id)}
        a, b = notes.get(link.from_note_id), notes.get(link.to_note_id)
        if not a or not b:
            return None
        try:
            result = self.llm.complete_json(self._WHY_SYSTEM, f"A: {a.text}\nB: {b.text}")
            why = result.get("why") if isinstance(result, dict) else None
        except Exception:
            return None                                   # degrade: show edge without why
        if why:
            self.repo.set_link_why(user_id, link.id, why)
        return why

    def unfinished(self, user_id: str, include_dormant: bool = False) -> list[Theme]:
        wanted = {"open", "dormant"} if include_dormant else {"open"}
        muted = self.repo.muted_labels(user_id)
        themes = [t for t in self.repo.list_themes(user_id)
                  if t.status in wanted and t.label.lower() not in muted]

        def span_days(t):
            return (t.last_seen - t.first_seen).days if t.first_seen and t.last_seen else 0

        themes.sort(key=lambda t: t.session_count * (span_days(t) + 1), reverse=True)
        return themes
