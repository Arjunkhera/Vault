"""
REST API routes for Knowledge Service.

Implements 5 operations:
1. POST /resolve-context - Resolve operational pages for a repo
2. POST /search - Full-text + semantic search with progressive disclosure
3. POST /get-page - Retrieve full page by ID
4. POST /get-related - Follow links from a page
5. POST /list-by-scope - Browse/filter pages by scope
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Annotated

from ..layer1.interface import SearchStore
from ..layer2.frontmatter import parse_page, to_page_summary, to_page_full
from ..layer2.scope_chain import resolve_scope_chain, collect_operational_pages
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


# Create router
router = APIRouter()


# Dependency to get SearchStore from app state
# This will be set up in main.py during app startup
def get_store() -> SearchStore:
    """
    Dependency injection for SearchStore.
    
    This is a placeholder that will be replaced with actual app.state.store
    via dependency_overrides in main.py.
    """
    raise NotImplementedError("SearchStore dependency not configured")


StoreDepends = Annotated[SearchStore, Depends(get_store)]


@router.post("/resolve-context", response_model=ResolveContextResponse)
async def resolve_context(request: ResolveContextRequest, store: StoreDepends):
    """
    Resolve the full scope chain for a repo and return operational pages.
    
    This is the primary operation for US-4 (Knowledge Base Seeding).
    Given a repo name, it:
    1. Resolves the full organizational hierarchy (repo → service → squad → org → company)
    2. Finds all operational pages applicable to any level in the scope chain
    3. Returns the repo-profile page as entry_point
    4. Returns operational pages sorted by specificity (repo-level first, company-level last)
    
    Args:
        request: ResolveContextRequest with repo name and include_full flag
        store: SearchStore instance (injected)
        
    Returns:
        ResolveContextResponse with entry_point, operational_pages, and scope_chain
    """
    # Step 1: Resolve the scope chain
    chain = resolve_scope_chain(request.repo, store)
    
    # Step 2: Collect operational pages
    operational_pages_tuples = collect_operational_pages(chain, store)
    
    # Step 3: Find the entry point (repo-profile page)
    entry_point = None
    results = store.search(request.repo, limit=20)
    
    for result in results:
        content = store.get_document(result.file_path)
        if not content:
            continue
        
        parsed = parse_page(content)
        
        # Check if this is the repo-profile page
        if parsed.scope.get("repo") == request.repo:
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
        scope_chain=chain.to_dict()
    )


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, store: StoreDepends):
    """
    Full-text and semantic search with progressive disclosure.
    
    Uses hybrid search (BM25 + vector + reranking) for best quality.
    Returns PageSummary objects (descriptions only) to enable filtering
    before requesting full pages.
    
    Optional filters:
    - mode: reference, operational, or keystone
    - type: service-overview, repo-profile, procedure, guide, etc.
    - scope: filter by company, org, squad, service, or repo
    
    Args:
        request: SearchRequest with query and optional filters
        store: SearchStore instance (injected)
        
    Returns:
        SearchResponse with results and total count
    """
    # Step 1: Perform hybrid search
    search_results = store.hybrid_search(request.query, limit=request.limit * 2)  # Get extra for filtering
    
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
    """
    Retrieve a full page by its identifier (file path or title).
    
    Returns the complete page content including body and all relationship fields.
    
    Args:
        request: GetPageRequest with page ID (file path)
        store: SearchStore instance (injected)
        
    Returns:
        PageFull with complete page content
        
    Raises:
        HTTPException 404 if page not found
    """
    # Try to get the document directly by file path
    content = store.get_document(request.id)
    
    if not content:
        raise HTTPException(status_code=404, detail=f"Page not found: {request.id}")
    
    # Parse and convert to PageFull
    parsed = parse_page(content)
    page_full = to_page_full(parsed, request.id)
    
    return page_full


@router.post("/get-related", response_model=GetRelatedResponse)
async def get_related(request: GetRelatedRequest, store: StoreDepends):
    """
    Follow links from a page to find related pages.
    
    Follows all relationship fields:
    - related: explicitly linked pages
    - depends_on: upstream dependencies
    - consumed_by: downstream consumers
    - applies_to: cross-cutting references
    
    Handles wiki-links [[Page Title]], dict refs {"repo": "name"}, and plain strings.
    
    Args:
        request: GetRelatedRequest with source page ID
        store: SearchStore instance (injected)
        
    Returns:
        GetRelatedResponse with source page and related pages
        
    Raises:
        HTTPException 404 if source page not found
    """
    # Get the source page
    content = store.get_document(request.id)
    
    if not content:
        raise HTTPException(status_code=404, detail=f"Page not found: {request.id}")
    
    # Parse the source page
    parsed = parse_page(content)
    source_summary = to_page_summary(parsed, request.id)
    
    # Follow links to find related pages
    related_pages_tuples = get_related_pages(parsed, store)
    
    # Convert to PageSummary list
    related_summaries = to_summaries(related_pages_tuples)
    
    return GetRelatedResponse(
        source=source_summary,
        related=related_summaries
    )


@router.post("/list-by-scope", response_model=ListByScopeResponse)
async def list_by_scope(request: ListByScopeRequest, store: StoreDepends):
    """
    List and filter pages by scope, mode, type, and tags.
    
    Useful for browsing the knowledge base by organizational hierarchy.
    All filters use AND logic - a page must match ALL specified criteria.
    
    Filters:
    - scope: company, org, squad, service, or repo (at least one required)
    - mode: reference, operational, or keystone (optional)
    - type: service-overview, repo-profile, procedure, etc. (optional)
    - tags: list of tags - page must have ALL specified tags (optional)
    
    Args:
        request: ListByScopeRequest with scope filter and optional filters
        store: SearchStore instance (injected)
        
    Returns:
        ListByScopeResponse with filtered pages and total count
    """
    # Step 1: Get all documents
    all_paths = store.list_documents()
    
    # Step 2: Parse frontmatter for each document
    all_pages = []
    
    for path in all_paths:
        content = store.get_document(path)
        if not content:
            continue
        
        parsed = parse_page(content)
        all_pages.append((parsed, path))
    
    # Step 3: Apply filters in order
    filtered = all_pages
    
    # Scope filter (required)
    filtered = filter_by_scope(filtered, request.scope)
    
    # Mode filter (optional)
    if request.mode:
        filtered = filter_by_mode(filtered, request.mode)
    
    # Type filter (optional)
    if request.type:
        filtered = filter_by_type(filtered, request.type)
    
    # Tags filter (optional)
    if request.tags:
        filtered = filter_by_tags(filtered, request.tags)
    
    # Step 4: Cap at limit
    filtered = filtered[:request.limit]
    
    # Step 5: Convert to PageSummary list
    summaries = to_summaries(filtered)
    
    return ListByScopeResponse(
        pages=summaries,
        total=len(summaries)
    )
