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
    # Step 1: Perform hybrid search, fall back to BM25 if hybrid fails
    search_results = store.hybrid_search(request.query, limit=request.limit * 2)
    if not search_results:
        search_results = store.search(request.query, limit=request.limit * 2)
    
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


# ============================================================================
# Write-Path Operations
# ============================================================================

@router.post("/validate-page", response_model=ValidatePageResponse)
async def validate_page(request: ValidatePageRequest, loader: SchemaLoaderDepends):
    """
    Validate a page against the schema and registries.

    Parses YAML frontmatter, runs all validation checks, and returns structured
    errors with fuzzy-match suggestions for unknown registry values.
    """
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
    """
    Suggest frontmatter metadata for a page.

    Analyses content, searches registries and the KB, and returns per-field
    suggestions with confidence levels and reasons.
    """
    suggester = MetadataSuggester(loader, store=store)
    result = suggester.suggest(request.content, hints=request.hints)
    result_dict = result.to_dict()

    return SuggestMetadataResponse(
        kb_status=result_dict["kb_status"],
        suggestions=result_dict["suggestions"],
    )


@router.post("/check-duplicates", response_model=CheckDuplicatesResponse)
async def check_duplicates(request: CheckDuplicatesRequest, store: StoreDepends):
    """
    Check candidate page content against existing KB pages for overlap.

    Uses hybrid search with a two-query strategy (title + body excerpt).
    Returns scored matches with recommendations: "create" if the content is
    sufficiently novel (score >= threshold), "merge" if overlap is detected.
    """
    checker = DuplicateChecker(store)
    threshold = request.threshold if request.threshold is not None else 0.75
    result = checker.check(request.title, request.content, threshold=threshold)

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
    """
    Return the full schema definition and all registry contents.

    Agents call this to discover available page types, field constraints,
    and known registry values before generating pages.
    """
    schema_dict = loader.get_schema()
    return SchemaResponse(**schema_dict)


@router.post("/registry/add", response_model=RegistryAddResponse)
async def registry_add(request: RegistryAddRequest, loader: SchemaLoaderDepends):
    """
    Add a new entry to a named registry.

    Writes the entry to the registry YAML file on disk and reloads the
    in-memory registry. Returns confirmation with the new total count.
    """
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
