"""
Simplified scope resolution for the Knowledge Service.

Two-level scope: program + repo.
- program: ties related repos together (e.g., "anvil-forge-vault")
- repo: individual repository (e.g., "anvil")

Replaces the v1 five-level hierarchy (company/org/squad/service/repo).
"""

import logging
from dataclasses import dataclass
from typing import Optional

from ..layer1.interface import SearchStore
from .frontmatter import parse_page, ParsedPage


logger = logging.getLogger(__name__)


@dataclass
class Scope:
    """
    Resolved two-level scope for a repository.

    program: Top-level grouping (e.g., "anvil-forge-vault")
    repo: Individual repository name (e.g., "anvil")
    """
    program: Optional[str] = None
    repo: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for API responses, excluding None values."""
        return {k: v for k, v in {
            "program": self.program,
            "repo": self.repo,
        }.items() if v is not None}


def resolve_scope(repo: str, store: SearchStore) -> Scope:
    """
    Resolve the program for a repository.

    Strategy:
    1. Search for pages mentioning the repo name
    2. Find the repo-profile page (type == "repo-profile" AND scope.repo == repo)
    3. Extract scope.program from that page
    4. Return Scope(program=..., repo=repo)

    Returns partial Scope if repo-profile not found (program will be None).
    """
    scope = Scope(repo=repo)

    results = store.search(repo, limit=20)

    for result in results:
        content = store.get_document(result.file_path)
        if not content:
            continue

        parsed = parse_page(content)

        if parsed.type == "repo-profile" and parsed.scope.get("repo") == repo:
            scope.program = parsed.scope.get("program")
            logger.debug(
                "Resolved scope for '%s': program=%s",
                repo, scope.program
            )
            break

    if scope.program is None:
        logger.debug("No repo-profile found for '%s'; program unresolved", repo)

    return scope


def collect_operational_pages(
    scope: Scope,
    store: SearchStore,
) -> list[tuple[ParsedPage, str]]:
    """
    Collect all operational pages applicable to the scope.

    A page is applicable if:
    - scope.repo matches (specificity=2), OR
    - scope.program matches (specificity=1), OR
    - applies_to references scope.repo (specificity=2)

    Returns list of (ParsedPage, file_path) tuples sorted by
    specificity descending (repo-level first, program-level second).
    """
    all_paths = store.list_documents()
    applicable: list[tuple[ParsedPage, str, int]] = []

    for path in all_paths:
        content = store.get_document(path)
        if not content:
            continue

        parsed = parse_page(content)

        # Only consider operational pages
        if parsed.mode != "operational":
            continue

        specificity = _calculate_specificity(parsed, scope)
        if specificity > 0:
            applicable.append((parsed, path, specificity))

    # Sort by specificity descending (repo-level first)
    applicable.sort(key=lambda x: x[2], reverse=True)

    return [(page, path) for page, path, _ in applicable]


def _calculate_specificity(page: ParsedPage, scope: Scope) -> int:
    """
    Calculate how specifically a page applies to the scope.

    Returns:
        2 — page applies at repo level (direct match or applies-to)
        1 — page applies at program level
        0 — page does not apply
    """
    # Repo-level match (highest specificity)
    if scope.repo and page.scope.get("repo") == scope.repo:
        return 2

    # Cross-cutting applies-to match (treated as repo-level)
    if scope.repo and _applies_to_repo(page.applies_to, scope.repo):
        return 2

    # Program-level match
    if scope.program and page.scope.get("program") == scope.program:
        return 1

    return 0


def _applies_to_repo(applies_to: list, repo: str) -> bool:
    """Check if the applies_to field references the given repo."""
    for item in applies_to:
        if isinstance(item, dict):
            if item.get("repo") == repo:
                return True
        elif isinstance(item, str):
            if item == repo:
                return True
    return False
