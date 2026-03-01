"""
Duplicate detection for Knowledge Service pages.

Scores content similarity against existing KB pages using hybrid search.
Two-query strategy: title-based search + body-based search, take the higher score.
Threshold: >=0.75 → recommend "create" (content is novel enough), <0.75 → recommend "merge".
"""

import logging
from dataclasses import dataclass
from typing import Optional

from ..layer1.interface import SearchStore
from ..layer2.frontmatter import parse_page

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.75
BODY_QUERY_CHARS = 500


@dataclass
class DuplicateMatch:
    """A single KB page that overlaps with the candidate content."""
    page_path: str
    title: str
    similarity_score: float
    recommendation: str
    matched_snippets: list[str]


@dataclass
class DuplicateCheckOutput:
    """Aggregate result of checking a candidate against the KB."""
    matches: list[DuplicateMatch]
    has_conflicts: bool


class DuplicateChecker:
    """
    Checks candidate page content against existing KB pages for overlap.

    Uses QMD hybrid search (BM25 + vector + LLM reranking) with a two-query
    strategy: one search by title, one by body excerpt. The higher score wins.
    """

    def __init__(self, store: SearchStore):
        self._store = store

    def check(
        self,
        title: str,
        content: str,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> DuplicateCheckOutput:
        """
        Run duplicate detection for a candidate page.

        Args:
            title: Proposed page title.
            content: Full page content (markdown body, no frontmatter needed).
            threshold: Score at or above which content is considered novel.
                       Below threshold → recommend merge.

        Returns:
            DuplicateCheckOutput with scored matches and conflict flag.
        """
        title_results = self._store.hybrid_search(title, limit=5)

        body_query = content[:BODY_QUERY_CHARS]
        body_results = self._store.hybrid_search(body_query, limit=5) if body_query.strip() else []

        scored: dict[str, tuple[float, list[str]]] = {}

        for result in title_results:
            path = result.file_path
            score = result.score
            snippets = [result.snippet] if result.snippet else []
            if path not in scored or score > scored[path][0]:
                scored[path] = (score, snippets)

        for result in body_results:
            path = result.file_path
            score = result.score
            snippets = [result.snippet] if result.snippet else []
            prev_score, prev_snippets = scored.get(path, (0.0, []))
            if score > prev_score:
                scored[path] = (score, snippets)
            else:
                existing_score, existing_snippets = scored[path]
                merged = existing_snippets + [s for s in snippets if s not in existing_snippets]
                scored[path] = (existing_score, merged)

        matches: list[DuplicateMatch] = []
        for path, (score, snippets) in scored.items():
            page_title = self._resolve_title(path)
            recommendation = "create" if score >= threshold else "merge"
            matches.append(DuplicateMatch(
                page_path=path,
                title=page_title,
                similarity_score=round(score, 4),
                recommendation=recommendation,
                matched_snippets=snippets,
            ))

        matches.sort(key=lambda m: m.similarity_score)
        has_conflicts = any(m.recommendation == "merge" for m in matches)

        return DuplicateCheckOutput(matches=matches, has_conflicts=has_conflicts)

    def _resolve_title(self, file_path: str) -> str:
        """Best-effort title resolution from a KB page path."""
        try:
            doc_content = self._store.get_document(file_path)
            if doc_content:
                parsed = parse_page(doc_content)
                return parsed.title
        except Exception:
            logger.debug("Could not resolve title for %s", file_path)
        return file_path.rsplit("/", 1)[-1].replace(".md", "").replace("-", " ").title()
