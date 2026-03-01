"""
Mode filtering and progressive disclosure utilities.

Provides filtering functions for pages based on mode, type, scope, and tags.
Also includes conversion utilities for progressive disclosure (summaries vs full pages).
"""

from typing import Optional

from ..api.models import PageSummary, ScopeFilter
from .frontmatter import ParsedPage, to_page_summary


def filter_by_mode(pages: list[tuple[ParsedPage, str]], mode: Optional[str]) -> list[tuple[ParsedPage, str]]:
    """Filter pages by mode (reference, operational, keystone)."""
    if mode is None:
        return pages
    return [(page, path) for page, path in pages if page.mode == mode]


def filter_by_type(pages: list[tuple[ParsedPage, str]], type_name: Optional[str]) -> list[tuple[ParsedPage, str]]:
    """Filter pages by type (repo-profile, guide, concept, procedure, keystone, learning)."""
    if type_name is None:
        return pages
    return [(page, path) for page, path in pages if page.type == type_name]


def filter_by_scope(pages: list[tuple[ParsedPage, str]], scope_filter: Optional[ScopeFilter]) -> list[tuple[ParsedPage, str]]:
    """
    Filter pages by scope (program, repo).

    A page matches if ALL non-None fields in the scope_filter match the page's scope.
    This is an AND operation — all specified filters must match.
    """
    if scope_filter is None:
        return pages

    filtered = []

    for page, path in pages:
        matches = True

        if scope_filter.program is not None:
            if page.scope.get("program") != scope_filter.program:
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

    A page matches if it has ALL specified tags (AND logic).
    """
    if tags is None or len(tags) == 0:
        return pages

    return [(page, path) for page, path in pages if all(tag in page.tags for tag in tags)]


def to_summaries(pages: list[tuple[ParsedPage, str]], scores: Optional[dict[str, float]] = None) -> list[PageSummary]:
    """
    Convert (ParsedPage, file_path) tuples to PageSummary objects.

    Implements progressive disclosure — descriptions only, no body.
    """
    summaries = []
    for page, path in pages:
        score = scores.get(path, 0.0) if scores else 0.0
        summary = to_page_summary(page, path, score)
        summaries.append(summary)
    return summaries
