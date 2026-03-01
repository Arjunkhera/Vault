"""
Data models for the bootstrap pipeline.

Defines the contracts between pipeline stages:
  Ingest → SourceDocument → Generate → DraftPage → Suggest+Validate →
  ReviewablePage → Store → StoredPage

Deduplication models (used across Generate and Store stages):
  DuplicateCheckResult — per-page similarity scoring against existing KB
  SynthesisResult — outcome of merging new content into an existing page

Also defines the FeedbackContext that accumulates across batches within a run.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================================
# Enums
# ============================================================================

class SourceType(str, Enum):
    REPO = "repo"
    LOCAL = "local"


class PageType(str, Enum):
    REPO_PROFILE = "repo-profile"
    PROCEDURE = "procedure"
    GUIDE = "guide"
    CONCEPT = "concept"
    KEYSTONE = "keystone"
    LEARNING = "learning"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ReviewStatus(str, Enum):
    VALID = "valid"
    NEEDS_INPUT = "needs_input"
    INVALID = "invalid"


class DuplicateRecommendation(str, Enum):
    CREATE = "create"
    MERGE = "merge"
    SKIP = "skip"


class StoredPageAction(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"


# ============================================================================
# Stage 1: Ingest output
# ============================================================================

class FileEntry(BaseModel):
    """A single file read from the source, with its content."""
    path: str = Field(..., description="Relative path within the source root")
    content: str = Field(..., description="UTF-8 text content of the file")
    size_bytes: int = Field(..., description="Original file size in bytes")
    extension: str = Field("", description="File extension without dot, e.g. 'py', 'md'")


class RepoMetadata(BaseModel):
    """Metadata extracted from a cloned repository."""
    name: str = Field(..., description="Repository name (last segment of URL or dir name)")
    default_branch: str = Field("master", description="Default branch that was cloned")
    origin_url: Optional[str] = Field(None, description="Remote URL if cloned from GitHub")
    languages: list[str] = Field(default_factory=list, description="Detected programming languages")
    has_readme: bool = False
    has_openapi: bool = False
    has_dockerfile: bool = False
    has_ci: bool = False
    package_manager: Optional[str] = Field(None, description="npm, maven, pip, etc.")
    total_files: int = Field(0, description="Total files before exclusion filter")
    included_files: int = Field(0, description="Files after exclusion filter")
    excluded_files: int = Field(0, description="Files removed by exclusion filter")


class IngestResult(BaseModel):
    """Output of the ingest stage — everything the LLM needs to decide what pages to generate."""
    source_type: SourceType
    origin: str = Field(..., description="GitHub URL or local directory path")
    metadata: RepoMetadata
    files: list[FileEntry] = Field(default_factory=list)
    tree: str = Field("", description="Filtered directory tree as a formatted string")
    ingest_timestamp: str = Field(default_factory=lambda: date.today().isoformat())


# ============================================================================
# Stage 2: Generate output (produced by LLM, structured by agent)
# ============================================================================

class SourceDocument(BaseModel):
    """
    A planned page identified by the LLM from the ingest result.
    The LLM fills this out after reading the IngestResult.
    """
    planned_page_type: Optional[str] = Field(None, description="Page type the LLM recommends")
    title: str = Field(..., description="Proposed page title")
    source_files: list[str] = Field(default_factory=list, description="Relative paths of files that inform this page")
    rationale: str = Field("", description="Why the LLM thinks this page should exist")


class DraftPage(BaseModel):
    """
    A generated knowledge page (markdown with frontmatter), not yet validated.
    Produced by the LLM in the Generate stage.
    """
    content: str = Field(..., description="Full markdown with YAML frontmatter")
    source_document: SourceDocument
    generation_notes: str = Field("", description="LLM's notes on what it did or was unsure about")


# ============================================================================
# Stage 3: Suggest + Validate output
# ============================================================================

class FieldIssue(BaseModel):
    """A field that needs user attention during review."""
    field: str
    reason: str
    suggestions: list[str] = Field(default_factory=list)
    action_required: str = Field("", description="pick_or_add | provide_value | fix_format | fix_constraint")


class ReviewablePage(BaseModel):
    """A draft page enriched with suggestion/validation results, ready for review."""
    content: str = Field(..., description="Markdown after merging suggestions")
    source_document: SourceDocument
    status: ReviewStatus
    validation_errors: list[dict] = Field(default_factory=list)
    validation_warnings: list[dict] = Field(default_factory=list)
    needs_input: list[FieldIssue] = Field(default_factory=list)
    suggestions_used: list[str] = Field(default_factory=list, description="Fields where suggestions were applied")


# ============================================================================
# Stage 5: Store output
# ============================================================================

class DuplicateCheckResult(BaseModel):
    """Per-page result from duplicate detection against existing KB content."""
    matched_page: str = Field(..., description="File path of the matching KB page")
    similarity_score: float = Field(..., ge=0.0, le=1.0, description="Normalised similarity score (0=no overlap, 1=identical)")
    overlapping_sections: list[str] = Field(default_factory=list, description="Section names where content overlaps")
    recommendation: DuplicateRecommendation = Field(..., description="Threshold-based: >=0.75 → create, <0.75 → merge")


class SynthesisResult(BaseModel):
    """Tracks the outcome of merging new source content into an existing KB page."""
    original_page: str = Field(..., description="File path of the existing page that was enriched")
    enriched_content: str = Field(..., description="Full markdown of the synthesised page")
    sections_added: list[str] = Field(default_factory=list, description="New sections introduced")
    sections_updated: list[str] = Field(default_factory=list, description="Existing sections that were modified")
    source_origin: str = Field(..., description="Origin of the new content (repo URL or path)")


class StoredPage(BaseModel):
    """A page that has been written to the knowledge repo."""
    file_path: str = Field(..., description="Path in knowledge repo where the page was written")
    title: str
    page_type: str
    source_origin: str = Field(..., description="Original source URL or file path")
    action: StoredPageAction = Field(StoredPageAction.CREATED, description="Whether this page was newly created, updated via synthesis, or skipped")


# ============================================================================
# Feedback Context (cross-batch, session-scoped)
# ============================================================================

class StructuralCorrection(BaseModel):
    """A field-level rule discovered during review."""
    field: str
    rule: str = Field(..., description="E.g. \"Use 'authorization' not 'auth'\"")


class FeedbackContext(BaseModel):
    """
    Session-scoped accumulator that improves generation quality across batches.
    Persists within a single bootstrap run, not across runs.
    """
    run_id: str = Field(..., description="Unique identifier for this bootstrap run")
    quality_corrections: list[str] = Field(
        default_factory=list,
        description="Natural language instructions that shape generation prompts",
    )
    structural_corrections: list[StructuralCorrection] = Field(
        default_factory=list,
        description="Field-level rules applied mechanically",
    )
    user_preferences: list[str] = Field(
        default_factory=list,
        description="Stylistic choices discovered during review",
    )
    pages_generated: int = Field(0)
    pages_approved: int = Field(0)
    registries_added: list[str] = Field(
        default_factory=list,
        description="Registry entries added during this run (for tracking)",
    )
