"""
Pydantic models for Vault Knowledge Service REST API.

Defines request/response models for all operations:

Read path (5 operations):
- resolve-context: Given a repo, return operational pages for the scope
- search: Full-text + semantic search with progressive disclosure
- get-page: Retrieve full page by identifier
- get-related: Follow links from a page
- list-by-scope: Browse/filter pages by scope, type, mode, tags

Write path (5 operations):
- validate-page: Validate page content against schema + registries
- suggest-metadata: Suggest frontmatter values from content analysis + KB search
- check-duplicates: Score content similarity against existing KB pages
- schema: Return full schema definition + registry contents
- registry/add: Add a new entry to a registry
"""

from typing import Optional
from pydantic import BaseModel, Field


# ============================================================================
# Valid Enums
# ============================================================================

VALID_PAGE_TYPES = [
    "repo-profile", "guide", "concept",
    "procedure", "keystone", "learning",
]

VALID_MODES = ["reference", "operational", "keystone"]


# ============================================================================
# Error Response
# ============================================================================

class ErrorResponse(BaseModel):
    """Structured error response returned by the API."""
    error: bool = True
    code: str = Field(..., description="Error code (e.g., 'page_not_found', 'validation_error')")
    message: str = Field(..., description="Human-readable error description")
    field: Optional[str] = Field(None, description="Field that caused the error, if applicable")
    details: Optional[dict] = Field(None, description="Additional error context")


# ============================================================================
# Core Page Models
# ============================================================================

class ScopeFilter(BaseModel):
    """
    Filter for scoping queries. Two-level scope: program + repo.
    All fields are optional — only non-None fields are used for filtering.
    """
    program: Optional[str] = Field(None, description="Program identifier (ties related repos, e.g., 'anvil-forge-vault')")
    repo: Optional[str] = Field(None, description="Repository name (e.g., 'anvil')")


class PageSummary(BaseModel):
    """
    Progressive disclosure object — description only, no body.
    Used in search results and listings to let agents filter before reading full pages.
    """
    id: str = Field(..., description="File path of the page")
    title: str
    description: str = Field(..., description="~150 char summary for progressive disclosure")
    type: str = Field(..., description="Page type: repo-profile, guide, concept, procedure, keystone, learning")
    mode: str = Field(..., description="Mode: reference, operational, or keystone")
    scope: dict = Field(default_factory=dict, description="Scope dict with optional keys: program, repo")
    tags: list[str] = Field(default_factory=list)
    relevance_score: Optional[float] = Field(None, description="Search relevance score (0-1)")


class PageFull(PageSummary):
    """
    Full page content including body and all relationship fields.
    Extends PageSummary with the complete page data.
    """
    body: str = Field(..., description="Full markdown content without frontmatter")
    related: list = Field(default_factory=list, description="Links to related knowledge pages")
    depends_on: list = Field(default_factory=list, description="Upstream dependencies")
    consumed_by: list = Field(default_factory=list, description="Downstream consumers")
    applies_to: list = Field(default_factory=list, description="Cross-cutting: repos this applies to")
    owner: Optional[str] = None
    last_verified: Optional[str] = None
    auto_generated: Optional[bool] = None
    source: Optional[str] = None


# ============================================================================
# Operation 1: resolve-context
# ============================================================================

class ResolveContextRequest(BaseModel):
    """Request to resolve the scope for a repo and return operational pages."""
    repo: str = Field(..., description="Repository name to resolve context for")
    include_full: bool = Field(False, description="If True, return PageFull objects; if False, return PageSummary objects")


class ResolveContextResponse(BaseModel):
    """Response containing the entry point page, operational pages, and resolved scope."""
    entry_point: Optional[PageSummary] = Field(None, description="The repo-profile page for the given repo")
    operational_pages: list[PageSummary | PageFull] = Field(default_factory=list, description="All operational pages applicable to the scope")
    scope: dict = Field(default_factory=dict, description="Resolved scope: program, repo")


# ============================================================================
# Operation 2: search
# ============================================================================

class SearchRequest(BaseModel):
    """
    Full-text and semantic search with optional filters.
    Uses hybrid search (BM25 + vector + reranking) for best quality.
    """
    query: str = Field(..., description="Search query text")
    mode: Optional[str] = Field(None, description="Filter by mode: reference, operational, or keystone")
    type: Optional[str] = Field(None, description="Filter by page type")
    scope: Optional[ScopeFilter] = Field(None, description="Filter by scope")
    limit: int = Field(10, description="Maximum number of results to return", ge=1, le=100)


class SearchResponse(BaseModel):
    """Search results with progressive disclosure — descriptions only."""
    results: list[PageSummary] = Field(default_factory=list)
    total: int = Field(..., description="Total number of results found")


# ============================================================================
# Operation 3: get-page
# ============================================================================

class GetPageRequest(BaseModel):
    """Request to retrieve a full page by its identifier (file path or title)."""
    id: str = Field(..., description="File path or title of the page to retrieve")


# Response is PageFull directly


# ============================================================================
# Operation 4: get-related
# ============================================================================

class GetRelatedRequest(BaseModel):
    """Request to follow links from a page to find related pages."""
    id: str = Field(..., description="File path or title of the source page")


class GetRelatedResponse(BaseModel):
    """Response containing the source page and all related pages."""
    source: PageSummary = Field(..., description="The source page")
    related: list[PageSummary] = Field(default_factory=list, description="All related pages found by following links")


# ============================================================================
# Operation 5: list-by-scope
# ============================================================================

class ListByScopeRequest(BaseModel):
    """Request to list/filter pages by scope, mode, type, and tags."""
    scope: ScopeFilter = Field(..., description="Scope filter — at least one field must be set")
    mode: Optional[str] = Field(None, description="Filter by mode: reference, operational, or keystone")
    type: Optional[str] = Field(None, description="Filter by page type")
    tags: Optional[list[str]] = Field(None, description="Filter by tags — page must have ALL specified tags")
    limit: int = Field(50, description="Maximum number of results to return", ge=1, le=100)


class ListByScopeResponse(BaseModel):
    """Response containing filtered pages with progressive disclosure."""
    pages: list[PageSummary] = Field(default_factory=list)
    total: int = Field(..., description="Total number of pages found")


# ============================================================================
# Write-Path Operation 6: validate-page
# ============================================================================

class ValidatePageRequest(BaseModel):
    """Validate a full markdown page (with YAML frontmatter) against the schema."""
    content: str = Field(..., description="Full markdown string including YAML frontmatter")


class ValidationErrorModel(BaseModel):
    """A single validation error with actionable guidance."""
    field: str
    value: Optional[str | list] = None
    message: str
    suggestions: list[str] = Field(default_factory=list)
    action_required: str = Field(
        ...,
        description="One of: pick_or_add, provide_value, fix_format, fix_constraint",
    )


class ValidationWarningModel(BaseModel):
    """A non-blocking warning (e.g. recommended field missing)."""
    field: str
    message: str


class ValidatePageResponse(BaseModel):
    """Result of page validation."""
    valid: bool
    errors: list[ValidationErrorModel] = Field(default_factory=list)
    warnings: list[ValidationWarningModel] = Field(default_factory=list)


# ============================================================================
# Write-Path Operation 7: suggest-metadata
# ============================================================================

class SuggestMetadataRequest(BaseModel):
    """Request metadata suggestions for a page."""
    content: str = Field(..., description="Full markdown — may have partial or empty frontmatter")
    hints: Optional[dict] = Field(None, description="Optional partial knowledge, e.g. {'scope.program': 'anvil-forge-vault'}")


class SuggestMetadataResponse(BaseModel):
    """Per-field metadata suggestions with confidence and reasons."""
    kb_status: str = Field(..., description="populated, sparse, or empty")
    suggestions: dict = Field(default_factory=dict, description="Per-field suggestion objects")


# ============================================================================
# Write-Path Operation 8: check-duplicates
# ============================================================================

class DuplicateMatchModel(BaseModel):
    """A single KB page that overlaps with the candidate content."""
    page_path: str = Field(..., description="File path of the matching KB page")
    title: str = Field(..., description="Title of the matching page")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Normalised similarity (0=none, 1=identical)")
    recommendation: str = Field(..., description="create (novel, >=threshold) or merge (overlap, <threshold)")
    matched_snippets: list[str] = Field(default_factory=list, description="Text excerpts showing where overlap was detected")


class CheckDuplicatesRequest(BaseModel):
    """Check candidate page content against existing KB for overlap."""
    title: str = Field(..., description="Proposed page title")
    content: str = Field(..., description="Page body content to check for duplicates")
    threshold: Optional[float] = Field(0.75, ge=0.0, le=1.0, description="Score >= threshold → create (novel). Below → merge.")


class CheckDuplicatesResponse(BaseModel):
    """Duplicate detection results with scored matches."""
    matches: list[DuplicateMatchModel] = Field(default_factory=list)
    has_conflicts: bool = Field(..., description="True if any match scored below threshold (needs user decision)")


# ============================================================================
# Write-Path Operation 9: schema (GET)
# ============================================================================

class SchemaResponse(BaseModel):
    """Full schema definition + all registry contents."""
    version: int
    page_types: list[dict] = Field(default_factory=list)
    field_constraints: dict = Field(default_factory=dict)
    registries: dict = Field(default_factory=dict)


# ============================================================================
# Write-Path Operation 10: registry/add
# ============================================================================

class RegistryEntryModel(BaseModel):
    """A new entry to add to a registry."""
    id: str = Field(..., description="Canonical identifier for the entry")
    description: Optional[str] = Field("", description="Human-readable description")
    aliases: Optional[list[str]] = Field(default_factory=list, description="Alternative names")
    scope_program: Optional[str] = Field(None, description="Program mapping (specific to master's 2-level scope)")


class RegistryAddRequest(BaseModel):
    """Add a new entry to a named registry."""
    registry: str = Field(..., description="Registry name: tags, services, teams, or orgs")
    entry: RegistryEntryModel


class RegistryAddResponse(BaseModel):
    """Confirmation of registry addition."""
    added: bool
    registry: str
    entry: RegistryEntryModel
    total_entries: int
