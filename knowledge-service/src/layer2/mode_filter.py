"""
Mode filtering and progressive disclosure utilities.

Provides filtering functions for pages based on mode, type, scope, and tags.
Also includes conversion utilities for progressive disclosure (summaries vs full pages).
"""

from typing import Optional

from ..api.models import PageSummary, ScopeFilter
from .frontmatter import ParsedPage, to_page_summary


def filter_by_mode(pages: list[tuple[ParsedPage, str]], mode: Optional[str]) -> list[tuple[ParsedPage, str]]:
    """
    Filter pages by mode (reference, operational, keystone).
    
    Args:
        pages: List of (ParsedPage, file_path) tuples
        mode: Mode to filter by, or None to return all pages
        
    Returns:
        Filtered list of (ParsedPage, file_path) tuples
        
    Example:
        >>> pages = [(page1, "path1"), (page2, "path2")]
        >>> operational = filter_by_mode(pages, "operational")
    """
    if mode is None:
        return pages
    
    return [(page, path) for page, path in pages if page.mode == mode]


def filter_by_type(pages: list[tuple[ParsedPage, str]], type_name: Optional[str]) -> list[tuple[ParsedPage, str]]:
    """
    Filter pages by type (service-overview, repo-profile, procedure, guide, etc.).
    
    Args:
        pages: List of (ParsedPage, file_path) tuples
        type_name: Type to filter by, or None to return all pages
        
    Returns:
        Filtered list of (ParsedPage, file_path) tuples
        
    Example:
        >>> pages = [(page1, "path1"), (page2, "path2")]
        >>> guides = filter_by_type(pages, "guide")
    """
    if type_name is None:
        return pages
    
    return [(page, path) for page, path in pages if page.type == type_name]


def filter_by_scope(pages: list[tuple[ParsedPage, str]], scope_filter: Optional[ScopeFilter]) -> list[tuple[ParsedPage, str]]:
    """
    Filter pages by scope (company, org, squad, service, repo).
    
    A page matches if ALL non-None fields in the scope_filter match the page's scope.
    This is an AND operation - all specified filters must match.
    
    Args:
        pages: List of (ParsedPage, file_path) tuples
        scope_filter: ScopeFilter with optional fields, or None to return all pages
        
    Returns:
        Filtered list of (ParsedPage, file_path) tuples
        
    Example:
        >>> scope_filter = ScopeFilter(org="DME", squad="Backend")
        >>> pages = [(page1, "path1"), (page2, "path2")]
        >>> dme_backend = filter_by_scope(pages, scope_filter)
        >>> # Returns only pages with BOTH org="DME" AND squad="Backend"
    """
    if scope_filter is None:
        return pages
    
    filtered = []
    
    for page, path in pages:
        # Check if page matches ALL non-None fields in the filter
        matches = True
        
        if scope_filter.company is not None:
            if page.scope.get("company") != scope_filter.company:
                matches = False
        
        if scope_filter.org is not None:
            if page.scope.get("org") != scope_filter.org:
                matches = False
        
        if scope_filter.squad is not None:
            if page.scope.get("squad") != scope_filter.squad:
                matches = False
        
        if scope_filter.service is not None:
            if page.scope.get("service") != scope_filter.service:
                matches = False
        
        if scope_filter.repo is not None:
            if page.scope.get("repo") != scope_filter.repo:
                matches = False
        
        if matches:
            filtered.append((page, path))
    
    return filtered


def filter_by_tags(pages: list[tuple[ParsedPage, str]], tags: Optional[list[str]]) -> list[tuple[ParsedPage, str]]:
    """
    Filter pages by tags.
    
    A page matches if it has ALL specified tags in its tags list.
    This is an AND operation - all specified tags must be present.
    
    Args:
        pages: List of (ParsedPage, file_path) tuples
        tags: List of tags to filter by, or None to return all pages
        
    Returns:
        Filtered list of (ParsedPage, file_path) tuples
        
    Example:
        >>> pages = [(page1, "path1"), (page2, "path2")]
        >>> core_backend = filter_by_tags(pages, ["core", "backend"])
        >>> # Returns only pages that have BOTH "core" AND "backend" tags
    """
    if tags is None or len(tags) == 0:
        return pages
    
    filtered = []
    
    for page, path in pages:
        # Check if page has ALL specified tags
        if all(tag in page.tags for tag in tags):
            filtered.append((page, path))
    
    return filtered


def to_summaries(pages: list[tuple[ParsedPage, str]], scores: Optional[dict[str, float]] = None) -> list[PageSummary]:
    """
    Convert a list of (ParsedPage, file_path) tuples to PageSummary objects.
    
    This implements progressive disclosure - only descriptions are included,
    not the full body content. Agents can filter these summaries before
    requesting full pages.
    
    Args:
        pages: List of (ParsedPage, file_path) tuples
        scores: Optional dict mapping file_path to relevance score (0.0-1.0)
        
    Returns:
        List of PageSummary objects suitable for API responses
        
    Example:
        >>> pages = [(page1, "path1"), (page2, "path2")]
        >>> scores = {"path1": 0.95, "path2": 0.78}
        >>> summaries = to_summaries(pages, scores)
    """
    summaries = []
    
    for page, path in pages:
        score = scores.get(path, 0.0) if scores else 0.0
        summary = to_page_summary(page, path, score)
        summaries.append(summary)
    
    return summaries
