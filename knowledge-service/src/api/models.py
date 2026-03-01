"""
Pydantic models for Vault Knowledge Service REST API.

Defines request/response models for all 5 operations:
- resolve-context: Given a repo, return operational pages for the scope
- search: Full-text + semantic search with progressive disclosure
- get-page: Retrieve full page by identifier
- get-related: Follow links from a page
- list-by-scope: Browse/filter pages by scope, type, mode, tags
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
