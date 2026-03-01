"""
Frontmatter parser for Knowledge Service pages.

Parses YAML frontmatter from markdown files and converts to structured data.
Uses python-frontmatter library for robust YAML parsing.
"""

from dataclasses import dataclass, field
from typing import Optional
import frontmatter

from ..api.models import PageSummary, PageFull


@dataclass
class ParsedPage:
    """
    Structured representation of a knowledge page with parsed frontmatter.
    
    All fields have sensible defaults to handle incomplete or missing frontmatter gracefully.
    """
    # Required fields
    type: str = "concept"  # Default to generic concept if not specified
    title: str = "Untitled"
    description: str = ""
    
    # Scope hierarchy (all optional)
    scope: dict = field(default_factory=dict)
    
    # Mode and tags
    mode: str = "reference"  # Default to reference mode
    tags: list[str] = field(default_factory=list)
    
    # Relationship fields
    related: list = field(default_factory=list)
    depends_on: list = field(default_factory=list)
    consumed_by: list = field(default_factory=list)
    applies_to: list = field(default_factory=list)
    
    # Metadata
    owner: Optional[str] = None
    last_verified: Optional[str] = None

    # Content
    body: str = ""


def parse_page(content: str) -> ParsedPage:
    """
    Parse a markdown file with YAML frontmatter into a structured ParsedPage.
    
    Args:
        content: Raw markdown string with YAML frontmatter
        
    Returns:
        ParsedPage with all frontmatter fields extracted and body separated
        
    Example:
        >>> content = '''---
        ... type: repo-profile
        ... title: Anvil
        ... description: Personal task and note management system
        ... scope:
        ...   program: anvil-forge-vault
        ...   repo: anvil
        ... mode: reference
        ... tags: [core, backend]
        ... ---
        ... # Anvil
        ... This is the body content.
        ... '''
        >>> page = parse_page(content)
        >>> page.title
        'Anvil'
        >>> page.scope['program']
        'anvil-forge-vault'
    """
    # Parse frontmatter using python-frontmatter library
    post = frontmatter.loads(content)
    
    # Extract frontmatter metadata (post.metadata is a dict)
    metadata = post.metadata
    
    # Build ParsedPage with defaults for missing fields
    return ParsedPage(
        type=metadata.get("type", "concept"),
        title=metadata.get("title", "Untitled"),
        description=metadata.get("description", ""),
        scope=metadata.get("scope", {}),
        mode=metadata.get("mode", "reference"),
        tags=[str(t) for t in metadata.get("tags", [])],
        related=metadata.get("related", []),
        depends_on=metadata.get("depends-on", []),  # Note: YAML uses hyphens
        consumed_by=metadata.get("consumed-by", []),
        applies_to=metadata.get("applies-to", []),
        owner=metadata.get("owner"),
        last_verified=metadata.get("last-verified"),
        body=post.content  # Body content without frontmatter
    )


def to_page_summary(parsed: ParsedPage, file_path: str, score: float = 0.0) -> PageSummary:
    """
    Convert a ParsedPage to a PageSummary for progressive disclosure.
    
    PageSummary includes only the description, not the full body content.
    This allows agents to filter results before requesting full pages.
    
    Args:
        parsed: ParsedPage object with parsed frontmatter
        file_path: Path to the file (used as the page ID)
        score: Optional relevance score from search (0.0-1.0)
        
    Returns:
        PageSummary model suitable for API responses
    """
    return PageSummary(
        id=file_path,
        title=parsed.title,
        description=parsed.description,
        type=parsed.type,
        mode=parsed.mode,
        scope=parsed.scope,
        tags=parsed.tags,
        relevance_score=score if score > 0 else None
    )


def to_page_full(parsed: ParsedPage, file_path: str) -> PageFull:
    """
    Convert a ParsedPage to a PageFull with complete content.
    
    PageFull includes the full body content and all relationship fields.
    
    Args:
        parsed: ParsedPage object with parsed frontmatter
        file_path: Path to the file (used as the page ID)
        
    Returns:
        PageFull model suitable for API responses
    """
    # Convert last_verified to string if it's a date object
    last_verified_str = None
    if parsed.last_verified is not None:
        if isinstance(parsed.last_verified, str):
            last_verified_str = parsed.last_verified
        else:
            # Handle datetime.date or datetime.datetime objects
            last_verified_str = str(parsed.last_verified)
    
    return PageFull(
        id=file_path,
        title=parsed.title,
        description=parsed.description,
        type=parsed.type,
        mode=parsed.mode,
        scope=parsed.scope,
        tags=parsed.tags,
        relevance_score=None,
        body=parsed.body,
        related=parsed.related,
        depends_on=parsed.depends_on,
        consumed_by=parsed.consumed_by,
        applies_to=parsed.applies_to,
        owner=parsed.owner,
        last_verified=last_verified_str,
    )
