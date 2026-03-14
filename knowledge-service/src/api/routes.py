"""
REST API routes for Vault Knowledge Service.

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
from fastapi import APIRouter, Depends
from typing import Annotated, Any

from ..config.settings import VaultSettings
from ..layer1.interface import SearchStore
from ..layer2.uuid_registry import UUIDRegistry
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
from ..layer2.schema import SchemaLoader, PageValidator, RegistryEntry
from ..layer2.suggester import MetadataSuggester
from ..layer2.dedup import DuplicateChecker
from ..layer2.git_writer import GitWriter
from ..errors import not_found, parse_error, schema_not_loaded, internal_error, registry_not_found, duplicate_entry, validation_error
from .models import (
    ResolveContextRequest,
    ResolveContextResponse,
    SearchRequest,
    SearchResponse,
    GetPageRequest,
    PageFull,
    PageSummary,
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
    WritePageRequest,
    WritePageResponse,
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


def get_settings() -> VaultSettings:
    """
    Dependency injection for VaultSettings.

    Placeholder replaced via dependency_overrides in main.py.
    """
    raise NotImplementedError("Settings dependency not configured")


SettingsDepends = Annotated[VaultSettings, Depends(get_settings)]


def get_uuid_registry() -> UUIDRegistry:
    """
    Dependency injection for UUIDRegistry.

    Placeholder replaced via dependency_overrides in main.py.
    """
    raise NotImplementedError("UUIDRegistry dependency not configured")


UUIDRegistryDepends = Annotated[UUIDRegistry, Depends(get_uuid_registry)]


# ============================================================================
# Synchronous handler implementations.
# Each is called via asyncio.to_thread() from the async route handler so that
# blocking subprocess.run() calls inside the QMD adapter do not starve the
# uvicorn event loop.
# ============================================================================

def _resolve_context_sync(request: ResolveContextRequest, store: SearchStore) -> ResolveContextResponse:
    """Synchronous implementation of resolve-context."""
    doc_cache = store.get_all_documents()
    scope = resolve_scope(request.repo, store, doc_cache=doc_cache)
    operational_pages_tuples = collect_operational_pages(scope, store, doc_cache=doc_cache)

    entry_point: PageSummary | None = None
    results = store.search(request.repo, limit=20)

    for result in results:
        content = doc_cache.get(result.file_path)
        if not content:
            continue

        parsed = parse_page(content)

        if parsed.type == "repo-profile" and parsed.scope.get("repo") == request.repo:
            entry_point = to_page_summary(parsed, result.file_path)
            break

    if request.include_full:
        operational_pages_list: list[PageFull] = [
            to_page_full(page, path)
            for page, path in operational_pages_tuples
        ]
        operational_pages: list[PageSummary | PageFull] = operational_pages_list  # type: ignore[assignment]
    else:
        operational_pages = to_summaries(operational_pages_tuples)
    return ResolveContextResponse(
        entry_point=entry_point,
        operational_pages=operational_pages,
        scope=scope.to_dict()
    )


@router.post("/resolve-context", response_model=ResolveContextResponse)
async def resolve_context(request: ResolveContextRequest, store: StoreDepends) -> ResolveContextResponse:
    """
    Resolve the scope for a repo and return operational pages.

    Given a repo name:
    1. Resolves program membership (repo → program)
    2. Finds all operational pages applicable to the repo or its program
    3. Returns the repo-profile page as entry_point
    4. Returns operational pages sorted by specificity (repo-level first)
    """
    return await asyncio.to_thread(_resolve_context_sync, request, store)


def _search_sync(request: SearchRequest, store: SearchStore) -> SearchResponse:
    """Synchronous implementation of search."""
    # BM25 keyword search. Hybrid disabled — see WI-4.
    search_results = store.search(request.query, limit=request.limit * 2)
    doc_cache = store.get_all_documents()

    # If both search and doc_cache returned nothing, this is likely a system
    # error (e.g. QMD down AND FTS5 index empty) rather than "no results".
    if not search_results and not doc_cache:
        logger.error(
            "Search returned zero results AND doc_cache is empty for query '%s'. "
            "Both QMD and FTS5 fallback may be non-functional. "
            "Store status: %s",
            request.query,
            store.status() if hasattr(store, "status") else "unknown",
        )

    pages_with_scores: list[tuple[Any, str, float]] = []

    for result in search_results:
        content = doc_cache.get(result.file_path)
        if not content:
            continue

        parsed = parse_page(content)
        pages_with_scores.append((parsed, result.file_path, result.score))

    pages: list[tuple[Any, str]] = [(page, path) for page, path, _ in pages_with_scores]

    if request.mode:
        pages = filter_by_mode(pages, request.mode)

    if request.type:
        pages = filter_by_type(pages, request.type)

    if request.scope:
        pages = filter_by_scope(pages, request.scope)

    pages = pages[:request.limit]

    scores: dict[str, float] = {path: score for _, path, score in pages_with_scores}
    summaries = to_summaries(pages, scores)

    return SearchResponse(
        results=summaries,
        total=len(summaries)
    )


@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, store: StoreDepends) -> SearchResponse:
    """
    Full-text and semantic search with progressive disclosure.

    Uses BM25 keyword search (hybrid disabled).
    Returns PageSummary objects (descriptions only) to enable filtering.
    """
    return await asyncio.to_thread(_search_sync, request, store)


def _get_page_sync(request: GetPageRequest, store: SearchStore, registry: UUIDRegistry) -> PageFull:
    """Synchronous implementation of get-page."""
    file_path = registry.resolve(request.id)
    if not file_path:
        raise not_found("Page", request.id)

    # store.get_document expects a collection-prefixed path (e.g. "shared/repos/anvil.md")
    store_path = f"shared/{file_path}"
    content = store.get_document(store_path)
    if not content:
        raise not_found("Page", request.id)

    parsed = parse_page(content)
    return to_page_full(parsed, store_path)


@router.post("/get-page", response_model=PageFull)
async def get_page(request: GetPageRequest, store: StoreDepends, registry: UUIDRegistryDepends) -> PageFull:
    """Retrieve a full page by its UUID."""
    return await asyncio.to_thread(_get_page_sync, request, store, registry)


def _get_related_sync(request: GetRelatedRequest, store: SearchStore, registry: UUIDRegistry) -> GetRelatedResponse:
    """Synchronous implementation of get-related."""
    file_path = registry.resolve(request.id)
    if not file_path:
        raise not_found("Page", request.id)

    store_path = f"shared/{file_path}"
    content = store.get_document(store_path)
    if not content:
        raise not_found("Page", request.id)

    parsed = parse_page(content)
    source_summary = to_page_summary(parsed, store_path)

    related_pages_tuples = get_related_pages(parsed, store)
    related_summaries = to_summaries(related_pages_tuples)

    return GetRelatedResponse(
        source=source_summary,
        related=related_summaries
    )


@router.post("/get-related", response_model=GetRelatedResponse)
async def get_related(request: GetRelatedRequest, store: StoreDepends, registry: UUIDRegistryDepends) -> GetRelatedResponse:
    """Follow links from a page to find related pages."""
    return await asyncio.to_thread(_get_related_sync, request, store, registry)


def _list_by_scope_sync(request: ListByScopeRequest, store: SearchStore) -> ListByScopeResponse:
    """Synchronous implementation of list-by-scope."""
    doc_cache = store.get_all_documents()

    all_pages: list[tuple[Any, str]] = []
    for path, content in doc_cache.items():
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


@router.post("/list-by-scope", response_model=ListByScopeResponse)
async def list_by_scope(request: ListByScopeRequest, store: StoreDepends) -> ListByScopeResponse:
    """List and filter pages by scope, mode, type, and tags."""
    return await asyncio.to_thread(_list_by_scope_sync, request, store)


# ============================================================================
# Write-Path Operations
# ============================================================================

def _validate_page_sync(request: ValidatePageRequest, loader: SchemaLoader) -> ValidatePageResponse:
    """Synchronous implementation of validate-page."""
    import frontmatter as fm

    if not loader.page_types:
        raise schema_not_loaded("Schema has no page types loaded")

    try:
        post = fm.loads(request.content)
        metadata: dict[str, Any] = dict(post.metadata)
    except Exception as e:
        raise parse_error(
            f"Failed to parse YAML frontmatter: {e}",
            {"error_type": type(e).__name__}
        )

    validator = PageValidator(loader)
    result = validator.validate(metadata)

    return ValidatePageResponse(
        valid=result.valid,
        errors=[
            ValidationErrorModel(
                field=err.field_name,
                value=err.value,
                message=err.message,
                suggestions=err.suggestions,
                action_required=err.action_required,
            )
            for err in result.errors
        ],
        warnings=[
            ValidationWarningModel(field=w.field_name, message=w.message)
            for w in result.warnings
        ],
    )


@router.post("/validate-page", response_model=ValidatePageResponse)
async def validate_page(request: ValidatePageRequest, loader: SchemaLoaderDepends) -> ValidatePageResponse:
    """
    Validate a page against the schema and registries.

    Parses YAML frontmatter, runs all validation checks, and returns structured
    errors with fuzzy-match suggestions for unknown registry values.
    """
    return await asyncio.to_thread(_validate_page_sync, request, loader)


def _suggest_metadata_sync(request: SuggestMetadataRequest, loader: SchemaLoader, store: SearchStore) -> dict[str, Any]:
    """Synchronous implementation of suggest-metadata."""
    if not loader.page_types:
        raise schema_not_loaded("Schema has no page types loaded")

    suggester = MetadataSuggester(loader, store=store)
    result = suggester.suggest(request.content, hints=request.hints)
    return result.to_dict()


@router.post("/suggest-metadata", response_model=SuggestMetadataResponse)
async def suggest_metadata(
    request: SuggestMetadataRequest,
    loader: SchemaLoaderDepends,
    store: StoreDepends,
) -> SuggestMetadataResponse:
    """
    Suggest frontmatter metadata for a page.

    Analyses content, searches registries and the KB, and returns per-field
    suggestions with confidence levels and reasons.
    """
    result_dict = await asyncio.to_thread(_suggest_metadata_sync, request, loader, store)

    return SuggestMetadataResponse(
        kb_status=result_dict["kb_status"],
        suggestions=result_dict["suggestions"],
    )


def _check_duplicates_sync(request: CheckDuplicatesRequest, store: SearchStore) -> Any:
    """Synchronous implementation of check-duplicates."""
    try:
        checker = DuplicateChecker(store)
        threshold = request.threshold if request.threshold is not None else 0.75
        return checker.check(request.title, request.content, threshold=threshold)
    except Exception as e:
        logger.error("Duplicate check failed: %s", e, exc_info=True)
        raise internal_error(f"Duplicate check failed: {e}")


@router.post("/check-duplicates", response_model=CheckDuplicatesResponse)
async def check_duplicates(request: CheckDuplicatesRequest, store: StoreDepends) -> CheckDuplicatesResponse:
    """
    Check candidate page content against existing KB pages for overlap.

    Uses hybrid search with a two-query strategy (title + body excerpt).
    Returns scored matches with recommendations: "create" if the content is
    sufficiently novel (score >= threshold), "merge" if overlap is detected.
    """
    result = await asyncio.to_thread(_check_duplicates_sync, request, store)

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


def _get_schema_sync(loader: SchemaLoader) -> dict[str, Any]:
    """Synchronous implementation of get-schema."""
    if not loader.page_types:
        raise schema_not_loaded("Schema has no page types loaded")
    return loader.get_schema()


@router.get("/schema", response_model=SchemaResponse)
async def get_schema_endpoint(loader: SchemaLoaderDepends) -> SchemaResponse:
    """
    Return the full schema definition and all registry contents.

    Agents call this to discover available page types, field constraints,
    and known registry values before generating pages.
    """
    schema_dict = await asyncio.to_thread(_get_schema_sync, loader)
    return SchemaResponse(**schema_dict)


def _registry_add_sync(request: RegistryAddRequest, loader: SchemaLoader) -> RegistryAddResponse:
    """Synchronous implementation of registry/add."""
    if not loader.registries:
        raise schema_not_loaded("Schema has no registries loaded")

    registry = loader.get_registry(request.registry)
    if registry is None:
        raise registry_not_found(request.registry)

    # Check for duplicate entry
    existing = next((e for e in registry if e.id == request.entry.id), None)
    if existing is not None:
        raise duplicate_entry(request.registry, request.entry.id)

    entry = RegistryEntry(
        id=request.entry.id,
        description=request.entry.description or "",
        aliases=request.entry.aliases or [],
        scope_program=request.entry.scope_program,
    )

    try:
        loader.add_registry_entry(request.registry, entry)
    except ValueError as e:
        raise internal_error(str(e))

    total = len(loader.get_registry(request.registry))
    logger.info("Registry '%s': added '%s' (total: %d)", request.registry, entry.id, total)

    return RegistryAddResponse(
        added=True,
        registry=request.registry,
        entry=RegistryEntryModel(
            id=entry.id,
            description=entry.description,
            aliases=entry.aliases,
            scope_program=entry.scope_program,
        ),
        total_entries=total,
    )


@router.post("/registry/add", response_model=RegistryAddResponse)
async def registry_add(request: RegistryAddRequest, loader: SchemaLoaderDepends) -> RegistryAddResponse:
    """
    Add a new entry to a named registry.

    Writes the entry to the registry YAML file on disk and reloads the
    in-memory registry. Returns confirmation with the new total count.
    """
    return await asyncio.to_thread(_registry_add_sync, request, loader)


def _write_page_sync(request: WritePageRequest, loader: SchemaLoader, settings: VaultSettings) -> WritePageResponse:
    """Synchronous implementation of write-page."""
    import frontmatter as fm
    import hashlib
    from datetime import datetime

    # Validate GitHub configuration
    if not settings.github_token:
        raise validation_error(
            "GitHub token not configured",
            details={"setting": "github_token"}
        )
    if not settings.github_repo:
        raise validation_error(
            "GitHub repo not configured",
            details={"setting": "github_repo"}
        )

    # Parse and validate frontmatter
    try:
        post = fm.loads(request.content)
        metadata: dict[str, Any] = dict(post.metadata)
    except Exception as e:
        raise parse_error(
            f"Failed to parse YAML frontmatter: {e}",
            {"error_type": type(e).__name__}
        )

    # Validate against schema
    if not loader.page_types:
        raise schema_not_loaded("Schema has no page types loaded")

    validator = PageValidator(loader)
    result = validator.validate(metadata)
    if not result.valid:
        raise validation_error(
            "Page validation failed",
            details={
                "errors": [
                    {"field": e.field_name, "message": e.message}
                    for e in result.errors
                ]
            }
        )

    # Strip collection prefix if caller passed the ID format (e.g. "shared/repos/foo.md")
    path = request.path
    for _prefix in ("shared/", "workspace/"):
        if path.startswith(_prefix):
            path = path[len(_prefix):]
            break

    # Derive branch, commit_message, pr_title if not provided
    branch_name = path.replace("/", "-").replace(".md", "").replace("_", "-")
    branch = f"write-page-{branch_name}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    commit_message = request.commit_message or f"Add/update page: {path}"
    pr_title = request.pr_title or f"Add/update knowledge page: {path}"

    # Initialize GitWriter and write page
    writer = GitWriter(
        repo_path=settings.knowledge_repo_path,
        github_token=settings.github_token,
        github_repo=settings.github_repo,
        base_branch=settings.github_base_branch,
    )

    pr_url, commit_sha = writer.write_page(
        page_path=path,
        content=request.content,
        branch=branch,
        commit_message=commit_message,
        pr_title=pr_title,
        pr_body=request.pr_body or "",
    )

    logger.info(
        "Page written and PR created: %s → %s",
        request.path,
        pr_url,
        extra={"commit_sha": commit_sha}
    )

    return WritePageResponse(
        pr_url=pr_url,
        branch=branch,
        commit_sha=commit_sha,
        path=path,
    )


@router.post("/write-page", response_model=WritePageResponse)
async def write_page(
    request: WritePageRequest,
    loader: SchemaLoaderDepends,
    settings: SettingsDepends,
) -> WritePageResponse:
    """
    Write a validated knowledge page to the knowledge-base repo, commit it to a new branch,
    and open a GitHub PR for human review.

    This completes the write-path pipeline:
    1. Validate page content against schema + registries
    2. Derive branch, commit, and PR metadata
    3. Create feature branch
    4. Write page to disk and commit
    5. Push to GitHub
    6. Open PR
    7. Return PR URL (human review gate)

    Requires GitHub configuration (GITHUB_TOKEN, GITHUB_REPO).
    """
    return await asyncio.to_thread(_write_page_sync, request, loader, settings)
