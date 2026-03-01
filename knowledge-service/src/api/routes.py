"""
REST API routes for Knowledge Service.

Read path (5 operations):
1. POST /resolve-context - Resolve operational pages for a repo
2. POST /search - Full-text + semantic search with progressive disclosure
3. POST /get-page - Retrieve full page by ID
4. POST /get-related - Follow links from a page
5. POST /list-by-scope - Browse/filter pages by scope

Write path (5 operations):
6. POST /validate-page - Validate page content against schema + registries
7. POST /suggest-metadata - Suggest frontmatter values from content analysis
8. POST /check-duplicates - Score content similarity against existing KB pages
9. GET  /schema - Return full schema definition + registries
10. POST /registry/add - Add a new entry to a registry
"""

import asyncio
import logging
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
from ..layer2.schema import SchemaLoader, PageValidator, RegistryEntry
from ..layer2.suggester import MetadataSuggester
from ..layer2.dedup import DuplicateChecker
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
    ValidatePageRequest,
    ValidatePageResponse,
    ValidationErrorModel,
    ValidationWarningModel,
    SuggestMetadataRequest,
    SuggestMetadataResponse,
    CheckDuplicatesRequest,
    CheckDuplicatesResponse,
    DuplicateMatchModel,
    SchemaResponse,
    RegistryAddRequest,
    RegistryAddResponse,
    RegistryEntryModel,
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

logger = logging.getLogger(__name__)


def get_schema_loader() -> SchemaLoader:
    """
    Dependency injection for SchemaLoader.

    Placeholder replaced via dependency_overrides in main.py.
    """
    raise NotImplementedError("SchemaLoader dependency not configured")


SchemaLoaderDepends = Annotated[SchemaLoader, Depends(get_schema_loader)]


# ============================================================================
# Synchronous handler implementations.
# Each is called via asyncio.to_thread() from the async route handler so that
# blocking subprocess.run() calls inside the QMD adapter do not starve the
# uvicorn event loop.
# ============================================================================

def _resolve_context_sync(request: ResolveContextRequest, store: SearchStore):
    doc_cache = store.get_all_documents()
    chain = resolve_scope_chain(request.repo, store, doc_cache=doc_cache)
    operational_pages_tuples = collect_operational_pages(chain, store, doc_cache=doc_cache)

    entry_point = None
    results = store.search(request.repo, limit=20)
    for result in results:
        content = doc_cache.get(result.file_path)
        if not content:
            continue
        parsed = parse_page(content)
        if parsed.scope.get("repo") == request.repo:
            entry_point = to_page_summary(parsed, result.file_path)
            break

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


def _search_sync(request: SearchRequest, store: SearchStore):
    # BM25 keyword search. Hybrid disabled — see WI-4.
    search_results = store.search(request.query, limit=request.limit * 2)
    doc_cache = store.get_all_documents()

    pages_with_scores = []
    for result in search_results:
        content = doc_cache.get(result.file_path)
        if not content:
            continue
        parsed = parse_page(content)
        pages_with_scores.append((parsed, result.file_path, result.score))

    pages = [(page, path) for page, path, _ in pages_with_scores]

    if request.mode:
        pages = filter_by_mode(pages, request.mode)
    if request.type:
        pages = filter_by_type(pages, request.type)
    if request.scope:
        pages = filter_by_scope(pages, request.scope)

    pages = pages[:request.limit]

    scores = {path: score for _, path, score in pages_with_scores}
    summaries = to_summaries(pages, scores)

    return SearchResponse(results=summaries, total=len(summaries))


def _get_page_sync(request: GetPageRequest, store: SearchStore):
    content = store.get_document(request.id)
    if not content:
        return None
    parsed = parse_page(content)
    return to_page_full(parsed, request.id)


def _get_related_sync(request: GetRelatedRequest, store: SearchStore):
    content = store.get_document(request.id)
    if not content:
        return None
    parsed = parse_page(content)
    source_summary = to_page_summary(parsed, request.id)
    related_pages_tuples = get_related_pages(parsed, store)
    related_summaries = to_summaries(related_pages_tuples)
    return GetRelatedResponse(source=source_summary, related=related_summaries)


def _list_by_scope_sync(request: ListByScopeRequest, store: SearchStore):
    doc_cache = store.get_all_documents()

    all_pages = []
    for path, content in doc_cache.items():
        if not content:
            continue
        parsed = parse_page(content)
        all_pages.append((parsed, path))

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

    return ListByScopeResponse(pages=summaries, total=len(summaries))


# ============================================================================
# Async route handlers — delegate to thread pool so subprocess calls
# don't block the event loop.
# ============================================================================

@router.post("/resolve-context", response_model=ResolveContextResponse)
async def resolve_context(request: ResolveContextRequest, store: StoreDepends):
    """Resolve the full scope chain for a repo and return operational pages."""
    return await asyncio.to_thread(_resolve_context_sync, request, store)


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, store: StoreDepends):
    """Full-text search with progressive disclosure and optional filters."""
    return await asyncio.to_thread(_search_sync, request, store)


@router.post("/get-page", response_model=PageFull)
async def get_page(request: GetPageRequest, store: StoreDepends):
    """Retrieve a full page by its identifier (file path)."""
    result = await asyncio.to_thread(_get_page_sync, request, store)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {request.id}")
    return result


@router.post("/get-related", response_model=GetRelatedResponse)
async def get_related(request: GetRelatedRequest, store: StoreDepends):
    """Follow links from a page to find related pages."""
    result = await asyncio.to_thread(_get_related_sync, request, store)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Page not found: {request.id}")
    return result


@router.post("/list-by-scope", response_model=ListByScopeResponse)
async def list_by_scope(request: ListByScopeRequest, store: StoreDepends):
    """List and filter pages by scope, mode, type, and tags."""
    return await asyncio.to_thread(_list_by_scope_sync, request, store)


# ============================================================================
# Write-Path Operations
# ============================================================================

@router.post("/validate-page", response_model=ValidatePageResponse)
async def validate_page(request: ValidatePageRequest, loader: SchemaLoaderDepends):
    """Validate a page against the schema and registries."""
    import frontmatter as fm

    try:
        post = fm.loads(request.content)
        metadata = dict(post.metadata)
    except Exception as e:
        return ValidatePageResponse(
            valid=False,
            errors=[ValidationErrorModel(
                field="frontmatter",
                message=f"Failed to parse YAML frontmatter: {e}",
                action_required="fix_format",
            )],
        )

    validator = PageValidator(loader)
    result = validator.validate(metadata)

    return ValidatePageResponse(
        valid=result.valid,
        errors=[
            ValidationErrorModel(
                field=err.field,
                value=err.value,
                message=err.message,
                suggestions=err.suggestions,
                action_required=err.action_required,
            )
            for err in result.errors
        ],
        warnings=[
            ValidationWarningModel(field=w.field, message=w.message)
            for w in result.warnings
        ],
    )


@router.post("/suggest-metadata", response_model=SuggestMetadataResponse)
async def suggest_metadata(
    request: SuggestMetadataRequest,
    loader: SchemaLoaderDepends,
    store: StoreDepends,
):
    """Suggest frontmatter metadata for a page."""
    def _sync():
        suggester = MetadataSuggester(loader, store=store)
        result = suggester.suggest(request.content, hints=request.hints)
        return result.to_dict()

    result_dict = await asyncio.to_thread(_sync)

    return SuggestMetadataResponse(
        kb_status=result_dict["kb_status"],
        suggestions=result_dict["suggestions"],
    )


@router.post("/check-duplicates", response_model=CheckDuplicatesResponse)
async def check_duplicates(request: CheckDuplicatesRequest, store: StoreDepends):
    """Check candidate page content against existing KB pages for overlap."""
    def _sync():
        checker = DuplicateChecker(store)
        threshold = request.threshold if request.threshold is not None else 0.75
        return checker.check(request.title, request.content, threshold=threshold)

    result = await asyncio.to_thread(_sync)

    return CheckDuplicatesResponse(
        matches=[
            DuplicateMatchModel(
                page_path=m.page_path,
                title=m.title,
                similarity_score=m.similarity_score,
                recommendation=m.recommendation,
                matched_snippets=m.matched_snippets,
            )
            for m in result.matches
        ],
        has_conflicts=result.has_conflicts,
    )


@router.get("/schema", response_model=SchemaResponse)
async def get_schema_endpoint(loader: SchemaLoaderDepends):
    """Return the full schema definition and all registry contents."""
    schema_dict = loader.get_schema()
    return SchemaResponse(**schema_dict)


@router.post("/registry/add", response_model=RegistryAddResponse)
async def registry_add(request: RegistryAddRequest, loader: SchemaLoaderDepends):
    """Add a new entry to a named registry."""
    entry = RegistryEntry(
        id=request.entry.id,
        description=request.entry.description or "",
        aliases=request.entry.aliases or [],
        scope_org=request.entry.scope_org,
    )

    try:
        loader.add_registry_entry(request.registry, entry)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    total = len(loader.get_registry(request.registry))
    logger.info("Registry '%s': added '%s' (total: %d)", request.registry, entry.id, total)

    return RegistryAddResponse(
        added=True,
        registry=request.registry,
        entry=RegistryEntryModel(
            id=entry.id,
            description=entry.description,
            aliases=entry.aliases,
            scope_org=entry.scope_org,
        ),
        total_entries=total,
    )
