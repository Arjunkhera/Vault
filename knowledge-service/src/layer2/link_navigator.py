"""
Link navigator for following relationships between knowledge pages.

Follows wiki-links and relationship fields (related, depends_on, consumed_by, applies_to)
to discover connected pages in the knowledge graph.
"""

import re
from typing import Optional

from ..layer1.interface import SearchStore
from .frontmatter import ParsedPage, parse_page


def get_related_pages(page: ParsedPage, store: SearchStore) -> list[tuple[ParsedPage, str]]:
    """
    Follow links from a page to find all related pages.
    
    Strategy:
    1. Collect all references from the page's relationship fields:
       - related: explicitly linked pages
       - depends_on: upstream dependencies
       - consumed_by: downstream consumers
       - applies_to: cross-cutting references
    2. Extract reference text from various formats:
       - Wiki-links: [[Page Title]] → "Page Title"
       - Dict refs: {"repo": "name"} → "name"
       - Plain strings: "name" → "name"
    3. Search for each reference in the store
    4. Parse and verify matches
    5. Return deduplicated list of (ParsedPage, file_path) tuples
    
    Args:
        page: Source ParsedPage to follow links from
        store: SearchStore instance for searching
        
    Returns:
        List of (ParsedPage, file_path) tuples for all related pages found
        Deduplicated by file_path.
        
    Example:
        >>> page = ParsedPage(
        ...     title="Document Service",
        ...     related=["[[Search Service]]", {"repo": "auth-service"}],
        ...     depends_on=["Redis", "PostgreSQL"]
        ... )
        >>> related = get_related_pages(page, store)
        >>> # Returns pages for Search Service, auth-service, Redis, PostgreSQL
    """
    # Collect all reference fields into a single list
    all_references = []
    all_references.extend(page.related)
    all_references.extend(page.depends_on)
    all_references.extend(page.consumed_by)
    all_references.extend(page.applies_to)
    
    # Extract reference text from each item
    reference_texts = []
    for ref in all_references:
        extracted = _extract_reference_text(ref)
        if extracted:
            reference_texts.append(extracted)
    
    # Search for each reference and collect matches
    found_pages = {}  # Use dict to deduplicate by file_path
    
    for ref_text in reference_texts:
        matches = _search_for_reference(ref_text, store)
        for parsed, path in matches:
            if path not in found_pages:
                found_pages[path] = (parsed, path)
    
    return list(found_pages.values())


def _extract_reference_text(ref) -> Optional[str]:
    """
    Extract searchable text from a reference in various formats.
    
    Handles:
    - Wiki-links: [[Page Title]] → "Page Title"
    - Wiki-links with aliases: [[Page Title|Alias]] → "Page Title"
    - Dict refs: {"repo": "name"} → "name"
    - Dict refs: {"service": "name"} → "name"
    - Plain strings: "name" → "name"
    
    Args:
        ref: Reference in any supported format
        
    Returns:
        Extracted text string, or None if format not recognized
    """
    if isinstance(ref, str):
        # Check for wiki-link format [[...]]
        wiki_match = re.match(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', ref)
        if wiki_match:
            return wiki_match.group(1).strip()
        
        # Plain string reference
        return ref.strip()
    
    elif isinstance(ref, dict):
        # Extract value from dict refs like {"repo": "name"} or {"service": "name"}
        for key in ["repo", "service", "squad", "org", "company"]:
            if key in ref:
                return ref[key]
    
    return None


def _search_for_reference(ref_text: str, store: SearchStore) -> list[tuple[ParsedPage, str]]:
    """
    Search for pages matching a reference text.
    
    Strategy:
    1. Search the store with the reference text (limit 5 for performance)
    2. For each result, get the document and parse frontmatter
    3. Verify the match by checking if:
       - Title matches the reference text (case-insensitive), OR
       - Any scope field value matches the reference text
    4. Return all verified matches
    
    Args:
        ref_text: Text to search for
        store: SearchStore instance
        
    Returns:
        List of (ParsedPage, file_path) tuples for verified matches
    """
    matches = []
    
    # Search for the reference text
    results = store.search(ref_text, limit=5)
    
    for result in results:
        content = store.get_document(result.file_path)
        if not content:
            continue
        
        parsed = parse_page(content)
        
        # Verify the match
        if _is_match(parsed, ref_text):
            matches.append((parsed, result.file_path))
    
    return matches


def _is_match(page: ParsedPage, ref_text: str) -> bool:
    """
    Check if a page matches a reference text.
    
    A page matches if:
    - Its title matches the reference text (case-insensitive), OR
    - Any of its scope field values match the reference text
    
    Args:
        page: ParsedPage to check
        ref_text: Reference text to match against
        
    Returns:
        True if the page matches the reference
    """
    ref_lower = ref_text.lower()
    
    # Check title match
    if page.title.lower() == ref_lower:
        return True
    
    # Check scope field values
    for value in page.scope.values():
        if isinstance(value, str) and value.lower() == ref_lower:
            return True
    
    return False
