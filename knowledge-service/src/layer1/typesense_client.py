"""
Typesense search client for Vault Knowledge Service.

Provides a unified search interface using Typesense as the search backend.
Replaces the FallbackSearchStore/QMD/FTS5 chain with deterministic,
faceted search via Typesense's built-in filter_by and sort_by capabilities.

The client:
- Connects to Typesense (configurable host/port/api_key)
- Translates SearchQuery into Typesense native query format
- Builds filter_by strings for exact-match faceted queries
- Returns normalized SearchResult objects
- Handles graceful degradation when Typesense is unreachable
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import typesense
from typesense.exceptions import (
    ObjectNotFound,
    RequestUnauthorized,
    ServerError,
    ServiceUnavailable,
    HTTPStatus0Error,
)

logger = logging.getLogger(__name__)

# ── Collection schema ─────────────────────────────────────────────────────────

COLLECTION_NAME = "horus_documents"

COLLECTION_SCHEMA: dict[str, Any] = {
    "name": COLLECTION_NAME,
    "fields": [
        {"name": "id", "type": "string"},
        {"name": "source", "type": "string", "facet": True},
        {"name": "source_type", "type": "string", "facet": True},
        {"name": "title", "type": "string"},
        {"name": "body", "type": "string"},
        {"name": "tags", "type": "string[]", "facet": True},
        {"name": "mode", "type": "string", "facet": True, "optional": True},
        {"name": "scope_repo", "type": "string", "facet": True, "optional": True},
        {"name": "scope_program", "type": "string", "facet": True, "optional": True},
        {"name": "vault_name", "type": "string", "facet": True, "optional": True},
        {"name": "created_at", "type": "int64", "optional": True},
        {"name": "modified_at", "type": "int64", "optional": True},
    ],
}


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class DateRange:
    """Date range filter (unix timestamps)."""
    gte: int | None = None
    lte: int | None = None


@dataclass
class SearchFilters:
    """Facet filters for Typesense queries."""
    source: list[str] | None = None
    source_type: list[str] | None = None
    status: list[str] | None = None
    tags: list[str] | None = None
    mode: list[str] | None = None
    scope_repo: str | None = None
    scope_program: str | None = None
    vault_name: str | None = None
    modified: DateRange | None = None
    created: DateRange | None = None


@dataclass
class SortClause:
    """A single sort directive."""
    field: str
    order: str = "desc"  # "asc" or "desc"


@dataclass
class SearchQuery:
    """Unified search query for Typesense."""
    q: str | None = None
    semantic: str | None = None
    filters: SearchFilters | None = None
    sort: list[SortClause] | None = None
    limit: int = 20
    offset: int = 0


@dataclass
class SearchResult:
    """A single search result from Typesense."""
    id: str
    source: str
    source_type: str
    title: str
    snippet: str
    score: float
    tags: list[str] = field(default_factory=list)
    mode: str | None = None
    scope_repo: str | None = None
    scope_program: str | None = None
    modified_at: int = 0
    created_at: int = 0


@dataclass
class SearchResponse:
    """Search response with results and metadata."""
    results: list[SearchResult] = field(default_factory=list)
    total: int = 0
    search_time_ms: int = 0
    search_unavailable: bool = False
    error: str | None = None


# ── Typesense client ──────────────────────────────────────────────────────────

class TypesenseSearchClient:
    """
    Search client backed by Typesense.

    Provides deterministic faceted search for the unified horus_documents
    collection. Handles connection errors gracefully by returning a
    SearchResponse with search_unavailable=True.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8108,
        api_key: str = "horus-local-key",
        protocol: str = "http",
        connection_timeout: int = 5,
    ) -> None:
        self._client = typesense.Client({
            "nodes": [{"host": host, "port": str(port), "protocol": protocol}],
            "api_key": api_key,
            "connection_timeout_seconds": connection_timeout,
        })
        self._collection_name = COLLECTION_NAME

    # ── Collection management ────────────────────────────────────────────

    def ensure_collection(self) -> None:
        """Create the horus_documents collection if it does not exist."""
        try:
            self._client.collections[self._collection_name].retrieve()
            logger.info("Typesense collection '%s' already exists", self._collection_name)
        except ObjectNotFound:
            self._client.collections.create(COLLECTION_SCHEMA)
            logger.info("Created Typesense collection '%s'", self._collection_name)

    def drop_collection(self) -> None:
        """Drop the collection (used for full re-index)."""
        try:
            self._client.collections[self._collection_name].delete()
            logger.info("Dropped Typesense collection '%s'", self._collection_name)
        except ObjectNotFound:
            pass

    # ── Document CRUD ────────────────────────────────────────────────────

    def upsert_document(self, document: dict[str, Any]) -> None:
        """Upsert a single document into Typesense."""
        try:
            self._client.collections[self._collection_name].documents.upsert(document)
        except Exception as e:
            logger.error("Failed to upsert document '%s': %s", document.get("id"), e)
            raise

    def upsert_documents_batch(self, documents: list[dict[str, Any]]) -> int:
        """
        Batch upsert documents. Returns the number successfully indexed.

        Uses Typesense's import endpoint with action=upsert for efficiency.
        """
        if not documents:
            return 0

        try:
            results = self._client.collections[self._collection_name].documents.import_(
                documents, {"action": "upsert"}
            )
            success_count = sum(1 for r in results if r.get("success", False))
            fail_count = len(results) - success_count
            if fail_count > 0:
                # Log first few failures for debugging
                failures = [r for r in results if not r.get("success", False)][:3]
                logger.warning(
                    "Batch upsert: %d/%d failed. First failures: %s",
                    fail_count, len(results), failures
                )
            return success_count
        except Exception as e:
            logger.error("Batch upsert failed: %s", e)
            raise

    def delete_document(self, document_id: str) -> None:
        """Delete a document by its ID."""
        try:
            self._client.collections[self._collection_name].documents[document_id].delete()
        except ObjectNotFound:
            logger.debug("Document '%s' not found for deletion (already removed)", document_id)
        except Exception as e:
            logger.error("Failed to delete document '%s': %s", document_id, e)
            raise

    # ── Search ───────────────────────────────────────────────────────────

    def search(self, query: SearchQuery) -> SearchResponse:
        """
        Execute a search query against Typesense.

        Translates the SearchQuery into Typesense's native search parameters,
        executes, and returns a normalized SearchResponse.

        If Typesense is unreachable, returns SearchResponse with
        search_unavailable=True and the error message.
        """
        try:
            params = self._build_search_params(query)
            raw = self._client.collections[self._collection_name].documents.search(params)
            return self._parse_results(raw)

        except (
            HTTPStatus0Error,
            ServiceUnavailable,
            ServerError,
            RequestUnauthorized,
            ConnectionError,
            OSError,
        ) as e:
            logger.error("Typesense search unavailable: %s", e)
            return SearchResponse(
                search_unavailable=True,
                error=f"Search unavailable: {e}",
            )
        except Exception as e:
            logger.error("Typesense search failed: %s", e, exc_info=True)
            return SearchResponse(
                search_unavailable=True,
                error=f"Search error: {e}",
            )

    # ── Filter building ──────────────────────────────────────────────────

    def _build_filter_by(self, filters: SearchFilters | None) -> str:
        """
        Build a Typesense filter_by string from SearchFilters.

        Examples:
            source:=vault && source_type:=repo-profile && scope_repo:=anvil
            tags:=search && tags:=vault   (AND semantics for tags)
            modified_at:>[1700000000]
        """
        if filters is None:
            return ""

        clauses: list[str] = []

        if filters.source:
            clauses.append(f"source:={self._escape_filter_values(filters.source)}")

        if filters.source_type:
            clauses.append(f"source_type:={self._escape_filter_values(filters.source_type)}")

        if filters.mode:
            clauses.append(f"mode:={self._escape_filter_values(filters.mode)}")

        # Tags use AND semantics: each tag gets its own clause
        if filters.tags:
            for tag in filters.tags:
                clauses.append(f"tags:={self._escape_value(tag)}")

        if filters.scope_repo:
            clauses.append(f"scope_repo:={self._escape_value(filters.scope_repo)}")

        if filters.scope_program:
            clauses.append(f"scope_program:={self._escape_value(filters.scope_program)}")

        if filters.vault_name:
            clauses.append(f"vault_name:={self._escape_value(filters.vault_name)}")

        if filters.modified:
            if filters.modified.gte is not None:
                clauses.append(f"modified_at:>={filters.modified.gte}")
            if filters.modified.lte is not None:
                clauses.append(f"modified_at:<={filters.modified.lte}")

        if filters.created:
            if filters.created.gte is not None:
                clauses.append(f"created_at:>={filters.created.gte}")
            if filters.created.lte is not None:
                clauses.append(f"created_at:<={filters.created.lte}")

        return " && ".join(clauses)

    @staticmethod
    def _escape_value(value: str) -> str:
        """Escape a single filter value for Typesense."""
        # Typesense filter values containing backticks need escaping
        return f"`{value}`" if value and (" " in value or ":" in value) else value

    @staticmethod
    def _escape_filter_values(values: list[str]) -> str:
        """Format a list of values for Typesense OR filter: [val1, val2]."""
        if len(values) == 1:
            v = values[0]
            return f"`{v}`" if " " in v or ":" in v else v
        escaped = []
        for v in values:
            escaped.append(f"`{v}`" if " " in v or ":" in v else v)
        return f"[{','.join(escaped)}]"

    # ── Query building ───────────────────────────────────────────────────

    def _build_search_params(self, query: SearchQuery) -> dict[str, Any]:
        """Build Typesense search parameters from a SearchQuery."""
        q = query.q or "*"
        params: dict[str, Any] = {
            "q": q,
            "query_by": "title,body,tags",
            "per_page": query.limit,
            "page": (query.offset // query.limit) + 1 if query.limit > 0 else 1,
            "highlight_fields": "title,body",
            "highlight_affix_num_tokens": 12,
        }

        # Use text search weights when doing keyword search
        if q != "*":
            params["query_by_weights"] = "3,1,2"

        filter_by = self._build_filter_by(query.filters)
        if filter_by:
            params["filter_by"] = filter_by

        if query.sort:
            sort_parts = [f"{s.field}:{s.order}" for s in query.sort]
            params["sort_by"] = ",".join(sort_parts)

        return params

    # ── Result parsing ───────────────────────────────────────────────────

    def _parse_results(self, raw: dict[str, Any]) -> SearchResponse:
        """Parse Typesense raw response into SearchResponse."""
        results: list[SearchResult] = []

        for hit in raw.get("hits", []):
            doc = hit.get("document", {})
            highlights = hit.get("highlights", [])

            # Build snippet from highlights
            snippet = ""
            for hl in highlights:
                if hl.get("field") == "body" and hl.get("snippet"):
                    snippet = hl["snippet"]
                    break
            if not snippet:
                for hl in highlights:
                    if hl.get("snippet"):
                        snippet = hl["snippet"]
                        break

            # Calculate normalized score
            text_match = hit.get("text_match", 0)
            # Typesense text_match is a large integer; normalize to 0-1
            raw_score = text_match / 1e18 if text_match > 0 else 0.0
            normalized_score = min(raw_score, 1.0)

            results.append(SearchResult(
                id=doc.get("id", ""),
                source=doc.get("source", ""),
                source_type=doc.get("source_type", ""),
                title=doc.get("title", ""),
                snippet=snippet,
                score=normalized_score,
                tags=doc.get("tags", []),
                mode=doc.get("mode"),
                scope_repo=doc.get("scope_repo"),
                scope_program=doc.get("scope_program"),
                modified_at=doc.get("modified_at", 0),
                created_at=doc.get("created_at", 0),
            ))

        return SearchResponse(
            results=results,
            total=raw.get("found", 0),
            search_time_ms=raw.get("search_time_ms", 0),
        )

    # ── Status ───────────────────────────────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Return Typesense health and collection stats."""
        try:
            health = self._client.operations.is_healthy()
            try:
                coll = self._client.collections[self._collection_name].retrieve()
                num_docs = coll.get("num_documents", 0)
            except ObjectNotFound:
                num_docs = 0

            return {
                "status": "ok" if health else "degraded",
                "engine": "typesense",
                "collection": self._collection_name,
                "num_documents": num_docs,
            }
        except Exception as e:
            return {
                "status": "unavailable",
                "engine": "typesense",
                "error": str(e),
            }
