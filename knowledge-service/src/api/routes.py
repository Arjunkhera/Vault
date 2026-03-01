"""
REST API routes for Vault Knowledge Service.

Implements 5 operations:
1. POST /resolve-context - Resolve operational pages for a repo
2. POST /search - Full-text + semantic search with progressive disclosure
3. POST /get-page - Retrieve full page by ID
4. POST /get-related - Follow links from a page
5. POST /list-by-scope - Browse/filter pages by scope
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from typing import Annotated

from ..errors import VaultError
from ..layer1.interface import SearchStore
from ..layer2.frontmatter import parse_page, to_page_summary, to_page_full
from ..layer2.scope import resolve_scope, collect_operational_pages
from ..layer2.mode_filter import (
    filter_by_mode,
    filter_by_type,
    filter_by_scope,
    filter_by_tags,
    to_summaries
)
from ..layer2.link_navigator import get_related_pages
from .models import (
    ResolveContextRequest,
    ResolveContextResponse,
    SearchRequest,
    SearchResponse,
    GetPageRequest,
    PageFull,
    GetRelatedRequest,
    GetRelatedResponse,
    ListByScopeRequest,
    ListByScopeResponse,
)


logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


# Dependency to get SearchStore from app state
def get_store() -> SearchStore:
    """
    Dependency injection for SearchStore.

    Placeholder replaced via dependency_overrides in main.py.
    """
    raise NotImplementedError("SearchStore dependency not configured")


StoreDepends = Annotated[SearchStore, Depends(get_store)]


@router.post("/resolve-context", response_model=ResolveContextResponse)
async def resolve_context(request: ResolveContextRequest, store: StoreDepends):
    """
    Resolve the scope for a repo and return operational pages.

    Given a repo name:
    1. Resolves program membership (repo → program)
    2. Finds all operational pages applicable to the repo or its program
    3. Returns the repo-profile page as entry_point
    4. Returns operational pages sorted by specificity (repo-level first)
    """
    # Step 1: Resolve the scope (repo → program)
    scope = resolve_scope(request.repo, store)

    # Step 2: Collect operational pages
    operational_pages_tuples = collect_operational_pages(scope, store)

    # Step 3: Find the entry point (repo-profile page)
    entry_point = None
    results = store.search(request.repo, limit=20)

    for result in results:
        content = store.get_document(result.file_path)
        if not content:
            continue

        parsed = parse_page(content)

        if parsed.type == "repo-profile" and parsed.scope.get("repo") == request.repo:
            entry_point = to_page_summary(parsed, result.file_path)
            break

    # Step 4: Convert operational pages to PageSummary or PageFull
    if request.include_full:
        operational_pages = [
            to_page_full(page, path)
            for page, path in operational_pages_tuples
        ]
    else:
        operational_pages = to_summaries(operational_pages_tuples)

    return ResolveContextResponse(
        entry_point=entry_point,
        operational_pages=operational_pages,
        scope=scope.to_dict()
    )


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, store: StoreDepends):
    """
    Full-text and semantic search with progressive disclosure.

    Uses hybrid search (BM25 + vector + reranking) for best quality.
    Returns PageSummary objects (descriptions only) to enable filtering.
    """
    # Step 1: Perform hybrid search
    search_results = store.hybrid_search(request.query, limit=request.limit * 2)

    # Step 2: Parse frontmatter for each result
    pages_with_scores = []

    for result in search_results:
        content = store.get_document(result.file_path)
        if not content:
            continue

        parsed = parse_page(content)
        pages_with_scores.append((parsed, result.file_path, result.score))

    # Step 3: Apply filters
    pages = [(page, path) for page, path, _ in pages_with_scores]

    if request.mode:
        pages = filter_by_mode(pages, request.mode)

    if request.type:
        pages = filter_by_type(pages, request.type)

    if request.scope:
        pages = filter_by_scope(pages, request.scope)

    # Step 4: Cap at limit
    pages = pages[:request.limit]

    # Step 5: Convert to PageSummary with scores
    scores = {path: score for _, path, score in pages_with_scores}
    summaries = to_summaries(pages, scores)

    return SearchResponse(
        results=summaries,
        total=len(summaries)
    )


@router.post("/get-page", response_model=PageFull)
async def get_page(request: GetPageRequest, store: StoreDepends):
    """Retrieve a full page by its identifier (file path or title)."""
    content = store.get_document(request.id)

    if not content:
        raise HTTPException(status_code=404, detail=f"Page not found: {request.id}")

    parsed = parse_page(content)
    page_full = to_page_full(parsed, request.id)

    return page_full


@router.post("/get-related", response_model=GetRelatedResponse)
async def get_related(request: GetRelatedRequest, store: StoreDepends):
    """Follow links from a page to find related pages."""
    content = store.get_document(request.id)

    if not content:
        raise HTTPException(status_code=404, detail=f"Page not found: {request.id}")

    parsed = parse_page(content)
    source_summary = to_page_summary(parsed, request.id)

    related_pages_tuples = get_related_pages(parsed, store)
    related_summaries = to_summaries(related_pages_tuples)

    return GetRelatedResponse(
        source=source_summary,
        related=related_summaries
    )


@router.post("/list-by-scope", response_model=ListByScopeResponse)
async def list_by_scope(request: ListByScopeRequest, store: StoreDepends):
    """List and filter pages by scope, mode, type, and tags."""
    all_paths = store.list_documents()

    all_pages = []
    for path in all_paths:
        content = store.get_document(path)
        if not content:
            continue
        parsed = parse_page(content)
        all_pages.append((parsed, path))

    # Apply filters
    filtered = all_pages
    filtered = filter_by_scope(filtered, request.scope)

    if request.mode:
        filtered = filter_by_mode(filtered, request.mode)

    if request.type:
        filtered = filter_by_type(filtered, request.type)

    if request.tags:
        filtered = filter_by_tags(filtered, request.tags)

    filtered = filtered[:request.limit]
    summaries = to_summaries(filtered)

    return ListByScopeResponse(
        pages=summaries,
        total=len(summaries)
    )
