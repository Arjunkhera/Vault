"""
Scope-chain resolver for Knowledge Service.

Resolves the full organizational hierarchy (repo → service → squad → org → company)
from page metadata and collects all operational pages applicable to the scope chain.
"""

from dataclasses import dataclass
from typing import Optional

from ..layer1.interface import SearchStore
from .frontmatter import parse_page, ParsedPage


@dataclass
class ScopeChain:
    """
    Resolved organizational hierarchy for a repository.
    
    Represents the full scope chain from most specific (repo) to most general (company).
    All fields are optional since we may have incomplete metadata.
    """
    repo: Optional[str] = None
    service: Optional[str] = None
    squad: Optional[str] = None
    org: Optional[str] = None
    company: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dict for API responses, excluding None values."""
        return {k: v for k, v in {
            "repo": self.repo,
            "service": self.service,
            "squad": self.squad,
            "org": self.org,
            "company": self.company
        }.items() if v is not None}


def resolve_scope_chain(repo: str, store: SearchStore) -> ScopeChain:
    """
    Resolve the full organizational hierarchy for a repository.
    
    Strategy:
    1. Search for pages mentioning the repo name
    2. Find the repo-profile page (where scope.repo == repo)
    3. Extract the full scope hierarchy from that page's frontmatter
    4. Return a ScopeChain with all discovered values
    
    Args:
        repo: Repository name to resolve
        store: SearchStore instance for querying pages
        
    Returns:
        ScopeChain with resolved hierarchy (may be partial if metadata is incomplete)
        
    Example:
        >>> chain = resolve_scope_chain("document-service", store)
        >>> chain.service
        'Document Service'
        >>> chain.org
        'DME'
    """
    # Start with just the repo name
    chain = ScopeChain(repo=repo)
    
    # Search for pages mentioning this repo
    results = store.search(repo, limit=20)
    
    # Look for the repo-profile page
    for result in results:
        content = store.get_document(result.file_path)
        if not content:
            continue
            
        parsed = parse_page(content)
        
        # Check if this is the repo-profile page for our target repo
        if parsed.scope.get("repo") == repo:
            # Found it! Extract the full scope hierarchy
            chain.service = parsed.scope.get("service")
            chain.squad = parsed.scope.get("squad")
            chain.org = parsed.scope.get("org")
            chain.company = parsed.scope.get("company")
            break
    
    return chain


def collect_operational_pages(chain: ScopeChain, store: SearchStore) -> list[tuple[ParsedPage, str]]:
    """
    Collect all operational pages applicable to the scope chain.
    
    Strategy:
    1. Get all documents from the store
    2. Parse each document's frontmatter
    3. Filter to pages with mode == "operational"
    4. Check if each operational page applies to any level in the scope chain
    5. Assign specificity scores (repo=5, service=4, squad=3, org=2, company=1)
    6. Sort by specificity descending (most specific first)
    
    A page applies if:
    - Its scope.repo matches chain.repo, OR
    - Its scope.service matches chain.service, OR
    - Its scope.squad matches chain.squad, OR
    - Its scope.org matches chain.org, OR
    - Its scope.company matches chain.company, OR
    - Its applies_to field references the repo (as dict or string)
    
    Args:
        chain: Resolved ScopeChain
        store: SearchStore instance
        
    Returns:
        List of (ParsedPage, file_path) tuples, sorted by specificity (most specific first)
        
    Example:
        >>> chain = ScopeChain(repo="document-service", service="Document Service", org="DME")
        >>> pages = collect_operational_pages(chain, store)
        >>> # Returns repo-level pages first, then service-level, then org-level
    """
    all_paths = store.list_documents()
    applicable_pages = []
    
    for path in all_paths:
        content = store.get_document(path)
        if not content:
            continue
            
        parsed = parse_page(content)
        
        # Only consider operational pages
        if parsed.mode != "operational":
            continue
        
        # Check if this page applies to any level in the scope chain
        specificity = _calculate_specificity(parsed, chain)
        
        if specificity > 0:
            applicable_pages.append((parsed, path, specificity))
    
    # Sort by specificity descending (most specific first)
    applicable_pages.sort(key=lambda x: x[2], reverse=True)
    
    # Return without specificity scores (just parsed page and path)
    return [(page, path) for page, path, _ in applicable_pages]


def _calculate_specificity(page: ParsedPage, chain: ScopeChain) -> int:
    """
    Calculate how specifically a page applies to the scope chain.
    
    Returns:
        Specificity score:
        - 5 if page applies at repo level
        - 4 if page applies at service level
        - 3 if page applies at squad level
        - 2 if page applies at org level
        - 1 if page applies at company level
        - 0 if page does not apply
    """
    # Check direct scope matches (highest to lowest specificity)
    if chain.repo and page.scope.get("repo") == chain.repo:
        return 5
    
    if chain.service and page.scope.get("service") == chain.service:
        return 4
    
    if chain.squad and page.scope.get("squad") == chain.squad:
        return 3
    
    if chain.org and page.scope.get("org") == chain.org:
        return 2
    
    if chain.company and page.scope.get("company") == chain.company:
        return 1
    
    # Check applies_to field for cross-cutting pages
    if chain.repo and _applies_to_repo(page.applies_to, chain.repo):
        return 5  # Treat applies_to as repo-level specificity
    
    return 0


def _applies_to_repo(applies_to: list, repo: str) -> bool:
    """
    Check if the applies_to field references the given repo.
    
    Handles both dict form ({"repo": "name"}) and string form ("name").
    """
    for item in applies_to:
        if isinstance(item, dict):
            if item.get("repo") == repo:
                return True
        elif isinstance(item, str):
            if item == repo:
                return True
    
    return False
