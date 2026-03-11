"""
Two-tier search store: tries QMD first, falls back to FTS5 on failure.
"""

import logging
from typing import Any, Optional

from .interface import SearchStore, SearchResult, Document
from .qmd_adapter import QMDAdapter
from .fts_engine import FtsSearchEngine

logger = logging.getLogger(__name__)


class FallbackSearchStore(SearchStore):

    # Minimum top score to consider QMD results useful. Below this threshold
    # we fall through to FTS5 (e.g. QMD body-weight bug returns ~0.000002).
    MIN_USEFUL_SCORE = 0.01

    def __init__(self, primary: QMDAdapter, fallback: FtsSearchEngine) -> None:
        self._primary = primary
        self._fallback = fallback

    def _has_useful_scores(self, results: list[SearchResult]) -> bool:
        """Check if search results have meaningful relevance scores."""
        return bool(results) and max(r.score for r in results) >= self.MIN_USEFUL_SCORE

    # Delegate collection management to both
    def ensure_collections(self, shared_path: str = "/data/knowledge-repo", workspace_path: str = "/workspace") -> None:
        self._primary.ensure_collections(shared_path, workspace_path)
        self._fallback.ensure_collections(shared_path, workspace_path)

    def search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        try:
            results = self._primary.search(query, collection, limit)
            if self._has_useful_scores(results):
                return results
            if results:
                logger.info("QMD returned %d results but max score %.6f < %.2f, falling back to FTS5",
                            len(results), max(r.score for r in results), self.MIN_USEFUL_SCORE)
        except Exception:
            logger.warning("QMD search failed for '%s', falling back to FTS5", query)
        return self._fallback.search(query, collection, limit)

    def semantic_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        try:
            results = self._primary.semantic_search(query, collection, limit)
            if self._has_useful_scores(results):
                return results
        except Exception:
            logger.warning("QMD semantic search failed for '%s', falling back to FTS5", query)
        return self._fallback.semantic_search(query, collection, limit)

    def hybrid_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        try:
            results = self._primary.hybrid_search(query, collection, limit)
            if self._has_useful_scores(results):
                return results
        except Exception:
            logger.warning("QMD hybrid search failed for '%s', falling back to FTS5", query)
        return self._fallback.hybrid_search(query, collection, limit)

    def get_document(self, file_path: str) -> Optional[str]:
        # Try primary first (may have QMD-indexed content), fall back to FTS5 (disk read)
        try:
            doc = self._primary.get_document(file_path)
            if doc:
                return doc
        except Exception:
            pass
        return self._fallback.get_document(file_path)

    def get_documents_by_glob(self, pattern: str) -> list[Document]:
        try:
            docs = self._primary.get_documents_by_glob(pattern)
            if docs:
                return docs
        except Exception:
            pass
        return self._fallback.get_documents_by_glob(pattern)

    def get_all_documents(self) -> dict[str, str]:
        try:
            docs = self._primary.get_all_documents()
            if docs:
                # QMD returns qmd:// URIs (e.g. "qmd://shared/repos/anvil.md").
                # FTS5 search returns plain paths ("shared/repos/anvil.md").
                # Provide both keys so lookups work regardless of search backend.
                normalized: dict[str, str] = {}
                for key, content in docs.items():
                    normalized[key] = content
                    if key.startswith("qmd://"):
                        normalized[key[len("qmd://"):]] = content
                return normalized
        except Exception:
            pass
        return self._fallback.get_all_documents()

    def list_documents(self, collection: Optional[str] = None) -> list[str]:
        try:
            docs = self._primary.list_documents(collection)
            if docs:
                return docs
        except Exception:
            pass
        return self._fallback.list_documents(collection)

    def reindex(self) -> None:
        # Reindex both -- primary may fail but fallback should always work
        try:
            self._primary.reindex()
        except Exception as e:
            logger.warning("QMD reindex failed: %s", e)
        self._fallback.reindex()

    def status(self) -> dict[str, Any]:
        primary_status = self._primary.status()
        fallback_status = self._fallback.status()
        return {
            "primary": primary_status,
            "fallback": fallback_status,
            "active": "primary" if primary_status.get("status") == "ok" else "fallback",
        }
