"""
Shared test fixtures for the Knowledge Service test suite.

Provides:
- MockSearchStore: In-memory SearchStore implementation for unit tests
- Sample markdown pages with v2 frontmatter (program + repo scope)
- TypeRegistry loaded from the real types/ directory
"""

import os
import pytest
from typing import Optional

from src.layer1.interface import SearchStore, SearchResult, Document
from src.config.type_registry import TypeRegistry


# ============================================================================
# Sample Pages (markdown with YAML frontmatter)
# ============================================================================

ANVIL_REPO_PROFILE = """---
type: repo-profile
title: Anvil
description: Personal task and note management system with SDLC workflow automation
scope:
  program: anvil-forge-vault
  repo: anvil
mode: reference
tags: [core, backend, typescript]
owner: arjun
last-verified: "2026-02-20"
related:
  - "[[Forge]]"
  - "[[Vault]]"
depends-on:
  - {repo: forge}
---
# Anvil

Anvil is the personal task and note management system. It provides SDLC workflow
automation including stories, scratches, projects, and documentation management.

## Tech Stack
- TypeScript / Bun runtime
- MCP server interface
- File-based storage (markdown + YAML frontmatter)
"""

FORGE_REPO_PROFILE = """---
type: repo-profile
title: Forge
description: Agent workspace tooling and package manager for Claude Code sessions
scope:
  program: anvil-forge-vault
  repo: forge
mode: reference
tags: [core, tooling, typescript]
owner: arjun
related:
  - "[[Anvil]]"
  - "[[Vault]]"
---
# Forge

Forge is the agent workspace tooling layer. It manages repo discovery,
workspace bootstrapping, and serves as a package manager for Claude Code sessions.
"""

VAULT_REPO_PROFILE = """---
type: repo-profile
title: Vault
description: Shared curated knowledge base for team documentation and architecture
scope:
  program: anvil-forge-vault
  repo: vault
mode: reference
tags: [core, backend, python]
owner: arjun
related:
  - "[[Anvil]]"
  - "[[Forge]]"
---
# Vault

Vault is the shared knowledge service. It stores curated documentation,
repo profiles, architecture decisions, and conventions.
"""

CODING_STANDARDS_PROCEDURE = """---
type: procedure
title: TypeScript Coding Standards
description: Coding conventions and standards for all TypeScript repos in the program
scope:
  program: anvil-forge-vault
mode: operational
tags: [typescript, conventions]
applies-to:
  - {repo: anvil}
  - {repo: forge}
---
# TypeScript Coding Standards

All TypeScript projects in the anvil-forge-vault program follow these conventions...
"""

ANVIL_DEPLOYMENT_GUIDE = """---
type: guide
title: Anvil Deployment Guide
description: Step-by-step guide for deploying Anvil to production
scope:
  program: anvil-forge-vault
  repo: anvil
mode: operational
tags: [deployment, anvil]
---
# Deploying Anvil

This guide covers the deployment process for the Anvil service.
"""

ARCHITECTURE_KEYSTONE = """---
type: keystone
title: System Architecture Overview
description: High-level architecture of the Anvil-Forge-Vault system
scope:
  program: anvil-forge-vault
mode: keystone
tags: [architecture, overview]
related:
  - "[[Anvil]]"
  - "[[Forge]]"
  - "[[Vault]]"
---
# System Architecture

The Anvil-Forge-Vault system consists of three interconnected services...
"""

REPO_PROFILE_WITH_WORKFLOW = """---
type: repo-profile
title: Horus
description: Developer workspace orchestration platform for multi-repo engineering workflows
scope:
  program: anvil-forge-vault
  repo: horus
mode: reference
tags: [core, backend, typescript]
owner: arjun
last-verified: "2026-03-03"
related:
  - "[[Anvil]]"
  - "[[Forge]]"
hosting:
  hostname: github.com
  org: Arjunkhera
workflow:
  strategy: owner
  default-branch: main
  pr-target: main
  branch-convention: "feat/*"
---
# Horus

Horus is the developer workspace orchestration platform.

## Git Workflow

- **Strategy**: Owner — push directly to origin, PR on same repo
- **Default branch**: `main`
- **Branch naming**: `feat/`, `fix/`, `chore/` prefixes
"""

# Page missing required field (no description) — for validation testing
INVALID_PAGE = """---
type: repo-profile
title: Broken Repo
scope:
  repo: broken
mode: reference
---
# Broken Repo

This page is missing a description, which is required for repo-profile type.
"""

# Page with no scope — concept type doesn't require scope
CONCEPT_PAGE = """---
type: concept
title: Progressive Disclosure
description: A pattern where search returns summaries first, then full content on demand
mode: reference
tags: [patterns, api-design]
---
# Progressive Disclosure

Progressive disclosure is a design pattern...
"""


# ============================================================================
# Page Registry (path → content mapping)
# ============================================================================

SAMPLE_PAGES = {
    "repos/anvil.md": ANVIL_REPO_PROFILE,
    "repos/forge.md": FORGE_REPO_PROFILE,
    "repos/vault.md": VAULT_REPO_PROFILE,
    "procedures/typescript-standards.md": CODING_STANDARDS_PROCEDURE,
    "guides/anvil-deployment.md": ANVIL_DEPLOYMENT_GUIDE,
    "keystones/architecture.md": ARCHITECTURE_KEYSTONE,
    "repos/broken.md": INVALID_PAGE,
    "concepts/progressive-disclosure.md": CONCEPT_PAGE,
}


# ============================================================================
# Mock SearchStore
# ============================================================================

class MockSearchStore(SearchStore):
    """
    In-memory SearchStore implementation for testing.

    Stores documents as a dict of path → content.
    Search uses simple substring matching on content (good enough for tests).
    """

    def __init__(self, documents: Optional[dict[str, str]] = None):
        self._documents = documents or {}

    def search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """Simple substring search for testing."""
        results = []
        query_lower = query.lower()
        for path, content in self._documents.items():
            if query_lower in content.lower() or query_lower in path.lower():
                results.append(SearchResult(
                    file_path=path,
                    score=1.0 if query_lower in path.lower() else 0.5,
                    snippet=content[:200],
                    collection=collection or "shared",
                ))
        return sorted(results, key=lambda r: r.score, reverse=True)[:limit]

    def semantic_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        return self.search(query, collection, limit)

    def hybrid_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        return self.search(query, collection, limit)

    def get_document(self, file_path: str) -> Optional[str]:
        return self._documents.get(file_path)

    def get_documents_by_glob(self, pattern: str) -> list[Document]:
        # Simple prefix matching for tests
        prefix = pattern.replace("**/*.md", "").replace("*", "")
        return [
            Document(file_path=path, content=content, collection="shared")
            for path, content in self._documents.items()
            if path.startswith(prefix) or not prefix
        ]

    def list_documents(self, collection: Optional[str] = None) -> list[str]:
        return list(self._documents.keys())

    def reindex(self) -> None:
        pass

    def status(self) -> dict:
        return {"documents": len(self._documents), "status": "ok"}


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_store() -> MockSearchStore:
    """MockSearchStore loaded with all sample pages."""
    return MockSearchStore(documents=dict(SAMPLE_PAGES))


@pytest.fixture
def empty_store() -> MockSearchStore:
    """Empty MockSearchStore."""
    return MockSearchStore()


@pytest.fixture
def type_registry() -> TypeRegistry:
    """TypeRegistry loaded from the real types/ directory."""
    types_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "types"
    )
    registry = TypeRegistry()
    registry.load_from_directory(types_dir)
    return registry
