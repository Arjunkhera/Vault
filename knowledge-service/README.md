# Vault Knowledge Service

A centralized, agent-oriented knowledge layer for Intuit, exposing a comprehensive REST API with QMD-powered search, scope-chain resolution, and write-path validation. Deployed as a Docker container.

## Overview

Vault is a knowledge management service that serves two primary functions:

1. **Read Path** (5 endpoints): Retrieve operational pages, search, resolve context for repositories, navigate relationships
2. **Write Path** (5 endpoints): Validate pages against schema, suggest metadata, detect duplicates, manage registries

The service is designed for AI agents and developer tools to query organizational knowledge, understand scope hierarchies (program + repo), and ensure new pages meet validation standards.

## Architecture

```
knowledge-service/
├── src/
│   ├── api/
│   │   ├── routes.py          # 10 REST endpoints (read + write path)
│   │   └── models.py          # Pydantic request/response models
│   ├── config/
│   │   └── settings.py        # Configuration loader (file + env + CLI)
│   ├── layer1/
│   │   ├── interface.py       # Abstract SearchStore interface
│   │   └── qmd_adapter.py     # QMD search implementation
│   ├── layer2/
│   │   ├── frontmatter.py     # YAML frontmatter parsing
│   │   ├── scope.py           # Scope-chain resolution (program + repo)
│   │   ├── mode_filter.py     # Mode/type/scope/tag filtering
│   │   ├── link_navigator.py  # Related page traversal
│   │   ├── schema.py          # SchemaLoader + PageValidator
│   │   ├── suggester.py       # MetadataSuggester for frontmatter hints
│   │   └── dedup.py           # DuplicateChecker for content similarity
│   ├── sync/
│   │   └── daemon.py          # Git pull loop + workspace watcher
│   ├── errors.py              # VaultError hierarchy
│   └── main.py                # FastAPI app + lifespan
├── tests/                     # Unit tests
├── Dockerfile                 # Container image definition
├── docker-compose.yml         # Multi-container setup (service + tests)
└── entrypoint.sh              # Container startup script
```

## Configuration

Vault loads configuration with precedence: **CLI args > environment variables > config file > defaults**.

### Config File (~/.vault/config.yaml)

```yaml
knowledge_repo_path: "/path/to/knowledge-base"
workspace_path: "/path/to/workspace"
qmd_index_name: "knowledge"
sync_interval: 300
port: 8000
host: "0.0.0.0"
log_level: "info"
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `KNOWLEDGE_REPO_PATH` | `/data/knowledge-repo` | Path to cloned knowledge repository |
| `WORKSPACE_PATH` | `/workspace` | Path to Anvil workspace (read-only) |
| `QMD_INDEX_NAME` | `knowledge` | QMD index name |
| `SYNC_INTERVAL` | `300` | Git pull interval in seconds (5 min) |
| `VAULT_PORT` | `8000` | REST API port |
| `VAULT_HOST` | `0.0.0.0` | REST API host |
| `VAULT_LOG_LEVEL` | `info` | Logging level |

## API Endpoints

All endpoints accept JSON and return JSON. Errors are returned with structured format (see Error Format section).

### Read Path (5 endpoints)

#### 1. POST /resolve-context
Resolve the scope for a repository and return all applicable operational pages.

**Use case:** Get the entry point (repo-profile) and all procedures/guides that apply to a repo.

**Request:**
```json
{
  "repo": "anvil",
  "include_full": false
}
```

**Response:**
```json
{
  "entry_point": {
    "id": "repos/anvil.md",
    "title": "Anvil Repository",
    "description": "Main repository for Anvil ...",
    "type": "repo-profile",
    "mode": "operational",
    "scope": { "program": "anvil-forge-vault", "repo": "anvil" },
    "tags": ["core"]
  },
  "operational_pages": [
    {
      "id": "guides/deployment.md",
      "title": "Deployment Guide",
      "description": "How to deploy Anvil to production",
      "type": "guide",
      "mode": "operational",
      "scope": { "program": "anvil-forge-vault" },
      "tags": []
    }
  ],
  "scope": {
    "program": "anvil-forge-vault",
    "repo": "anvil"
  }
}
```

#### 2. POST /search
Full-text search with filtering by mode, type, and scope.

**Use case:** Exploratory queries when you don't know the exact page title.

**Request:**
```json
{
  "query": "how to deploy",
  "mode": "operational",
  "limit": 5
}
```

**Response:**
```json
{
  "results": [
    {
      "id": "guides/deployment.md",
      "title": "Deployment Guide",
      "description": "Step-by-step deployment procedures",
      "type": "guide",
      "mode": "operational",
      "scope": { "program": "anvil-forge-vault" },
      "tags": ["deployment"],
      "relevance_score": 0.95
    }
  ],
  "total": 1
}
```

#### 3. POST /get-page
Retrieve full page content by identifier (file path).

**Use case:** Get complete content after finding a page via search.

**Request:**
```json
{
  "id": "guides/deployment.md"
}
```

**Response:**
```json
{
  "id": "guides/deployment.md",
  "title": "Deployment Guide",
  "description": "Step-by-step deployment procedures",
  "type": "guide",
  "mode": "operational",
  "scope": { "program": "anvil-forge-vault" },
  "tags": ["deployment"],
  "body": "# Deployment Guide\n\n1. Prepare the environment\n2. Run deployment script...",
  "related": ["guides/rollback.md"],
  "depends_on": [],
  "consumed_by": ["services/api.md"],
  "applies_to": ["anvil", "forge"]
}
```

#### 4. POST /get-related
Follow links from a page to discover related pages.

**Use case:** Explore connected knowledge (dependencies, dependents, cross-cutting applicability).

**Request:**
```json
{
  "id": "guides/deployment.md"
}
```

**Response:**
```json
{
  "source": {
    "id": "guides/deployment.md",
    "title": "Deployment Guide",
    "description": "..."
  },
  "related": [
    {
      "id": "guides/rollback.md",
      "title": "Rollback Procedures"
    }
  ]
}
```

#### 5. POST /list-by-scope
List and filter pages by scope, mode, type, and tags.

**Use case:** Browse all procedures for a specific program or repo.

**Request:**
```json
{
  "scope": { "program": "anvil-forge-vault" },
  "mode": "operational",
  "limit": 20
}
```

**Response:**
```json
{
  "pages": [
    {
      "id": "guides/deployment.md",
      "title": "Deployment Guide",
      "description": "...",
      "type": "guide",
      "mode": "operational",
      "scope": { "program": "anvil-forge-vault" },
      "tags": ["deployment"]
    }
  ],
  "total": 1
}
```

### Write Path (5 endpoints)

#### 6. POST /validate-page
Validate a markdown page (with YAML frontmatter) against the schema and registries.

**Use case:** Ensure a new or modified page meets all schema requirements before committing.

**Request:**
```json
{
  "content": "---\ntitle: My Guide\ntype: guide\nmode: operational\nscope:\n  program: anvil-forge-vault\n---\n\n# My Guide\nContent here..."
}
```

**Response (valid):**
```json
{
  "valid": true,
  "errors": [],
  "warnings": []
}
```

**Response (invalid):**
```json
{
  "valid": false,
  "errors": [
    {
      "field": "type",
      "value": "invalid-type",
      "message": "Unknown page type",
      "suggestions": ["guide", "procedure", "concept"],
      "action_required": "pick_or_add"
    }
  ],
  "warnings": []
}
```

#### 7. POST /suggest-metadata
Suggest frontmatter metadata based on content analysis.

**Use case:** Auto-fill metadata when creating pages or converting documents.

**Request:**
```json
{
  "content": "# Deployment Procedure\n\nSteps to deploy to production:\n1. ...",
  "hints": { "scope.program": "anvil-forge-vault" }
}
```

**Response:**
```json
{
  "kb_status": "ready",
  "suggestions": {
    "type": {
      "value": "procedure",
      "confidence": 0.9,
      "reason": "Content describes step-by-step instructions"
    },
    "mode": {
      "value": "operational",
      "confidence": 0.85,
      "reason": "Practical guidance with actionable steps"
    },
    "tags": {
      "value": ["deployment", "ci-cd"],
      "confidence": 0.8
    }
  }
}
```

#### 8. POST /check-duplicates
Score content similarity against existing KB pages.

**Use case:** Detect potential overlap before committing a new page.

**Request:**
```json
{
  "title": "How to Deploy",
  "content": "Steps to deploy the application...",
  "threshold": 0.75
}
```

**Response:**
```json
{
  "matches": [
    {
      "page_path": "guides/deployment.md",
      "title": "Deployment Guide",
      "similarity_score": 0.82,
      "recommendation": "merge",
      "matched_snippets": ["Steps to deploy", "application"]
    }
  ],
  "has_conflicts": true
}
```

#### 9. GET /schema
Return the full schema definition and all registry contents.

**Use case:** Discover page types, field constraints, and valid registry values before generating pages.

**Request:**
```
GET /schema
```

**Response:**
```json
{
  "page_types": {
    "guide": {
      "description": "Practical how-to guide",
      "required_fields": ["title", "type", "mode"],
      "optional_fields": ["tags", "scope", "owner"]
    }
  },
  "registries": {
    "tags": [
      {
        "id": "deployment",
        "description": "Deployment-related content",
        "aliases": ["deploy"]
      }
    ],
    "programs": [
      {
        "id": "anvil-forge-vault",
        "description": "Anvil/Forge/Vault ecosystem"
      }
    ],
    "repos": [
      {
        "id": "anvil",
        "description": "Anvil repository"
      }
    ]
  }
}
```

#### 10. POST /registry/add
Add a new entry to a registry (tags, repos, programs).

**Use case:** Register a new tag or repo that doesn't exist in the schema.

**Request:**
```json
{
  "registry": "tags",
  "entry": {
    "id": "new-feature",
    "description": "Pages about new feature development",
    "aliases": ["feature"]
  }
}
```

**Response:**
```json
{
  "added": true,
  "registry": "tags",
  "entry": {
    "id": "new-feature",
    "description": "Pages about new feature development",
    "aliases": ["feature"]
  },
  "total_entries": 42
}
```

## Error Format

All errors are returned with a consistent structure:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": { "context": "here" },
    "request_id": "uuid"
  }
}
```

**Common error codes:**

| Code | Status | Meaning |
|------|--------|---------|
| `VALIDATION_FAILED` | 400 | Page validation failed (schema/registry errors) |
| `PARSE_ERROR` | 400 | YAML frontmatter parsing failed |
| `PAGE_NOT_FOUND` | 404 | Page identifier not found |
| `REGISTRY_NOT_FOUND` | 404 | Registry name does not exist |
| `DUPLICATE_ENTRY` | 409 | Entry already exists in registry |
| `SCHEMA_NOT_LOADED` | 503 | Schema directory not found or failed to load |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

## Schema Format

Knowledge pages use YAML frontmatter for metadata. See `_schema/schema.yaml` in the knowledge repository for the complete schema definition.

### Example page:

```markdown
---
title: Deployment Guide
type: guide
mode: operational
scope:
  program: anvil-forge-vault
  repo: anvil
tags:
  - deployment
  - ci-cd
owner: platform-team
last_verified: "2026-03-01"
---

# Deployment Guide

Steps to deploy the application...
```

### Scope Model

Pages use a **2-level scope**:
- **program** — ties related repositories (e.g., "anvil-forge-vault")
- **repo** — individual repository (e.g., "anvil")

Operational pages can be repo-specific or program-wide. The scope-chain resolver prioritizes repo-level pages first, then program-level, then global.

## Development Setup

### Local Development

```bash
# Set environment variables
export KNOWLEDGE_REPO_PATH=/path/to/knowledge-base
export WORKSPACE_PATH=/path/to/workspace

# Install dependencies
pip install -r requirements.txt

# Run the service
python -m uvicorn src.main:app --reload --port 8000
```

### Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/unit/test_errors.py -v

# Type checking
mypy src/ --ignore-missing-imports
```

## Docker

### Build and Run

```bash
# Build the image
docker build -t vault-knowledge-service .

# Run the container
docker run -d \
  -p 8000:8000 \
  -e KNOWLEDGE_REPO_PATH=/data/knowledge-repo \
  -e WORKSPACE_PATH=/workspace \
  -v ~/anvil-workspace:/workspace:ro \
  vault-knowledge-service

# Check logs
docker logs -f <container-id>

# Check health
curl http://localhost:8000/health
```

### Docker Compose

```bash
# Build and start all services
docker-compose up -d

# Check service status
docker-compose ps

# View logs
docker-compose logs -f knowledge-service

# Stop services
docker-compose down
```

## Scope Model and Operational Pages

The service implements a **2-level scope hierarchy**:

1. **Program-level** — organizational unit that ties multiple repos (e.g., "anvil-forge-vault")
2. **Repo-level** — individual repository (e.g., "anvil")

### Operational Pages

When resolving context for a repo, the service collects:
1. **Repo-profile page** — entry point, describes the repo
2. **Repo-specific operational pages** — procedures/guides at repo level
3. **Program-level operational pages** — procedures/guides at program level

Pages are sorted by specificity: repo-level first, then program-level.

## Dependencies

Core Python dependencies (see `requirements.txt`):
- **FastAPI 0.115.0** — REST API framework
- **Uvicorn 0.30.0** — ASGI server
- **PyYAML 6.0.2** — YAML parsing
- **python-frontmatter 1.1.0** — Markdown frontmatter
- **Pydantic 2.9.0** — Data validation and models
- **watchdog 4.0.0** — File system watching
- **httpx 0.27.0** — HTTP client

## Next Steps

- **Phase 7** (complete): MCP Thin Client (TypeScript)
- **Phase 8** (future): Integration tests and E2E testing
