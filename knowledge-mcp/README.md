# Vault Knowledge Service MCP Client

A Model Context Protocol (MCP) thin client that provides AI agents and developer tools access to the Vault Knowledge Service. Translates MCP tool calls into REST API calls.

## Overview

This package exposes **10 tools** wrapping the Vault Knowledge Service REST API. It is a **thin client** — it contains no knowledge logic itself, only translation between MCP protocol and HTTP requests. All intelligence (search, validation, scope resolution, etc.) lives in the Knowledge Service.

```
Claude / Cursor IDE
      │
      ▼
   MCP Protocol
      │
      ▼
@vault/knowledge-mcp (this package)
      │
      └──────► HTTP POST/GET
                    │
                    ▼
            Knowledge Service REST API (:8000)
                    │
                    ├── Layer 2: Knowledge Logic
                    ├── Layer 1: QMD Search
                    └── Git + File Sync
```

## Installation

```bash
npm install @vault/knowledge-mcp
npm run build
```

## Configuration

Configure the MCP server in your application's MCP settings (e.g., Cursor IDE):

```json
{
  "mcpServers": {
    "vault": {
      "command": "node",
      "args": [
        "/path/to/knowledge-mcp/dist/index.js",
        "--endpoint",
        "http://localhost:8000"
      ]
    }
  }
}
```

### Command-line Arguments

- `--endpoint <url>` — Knowledge Service REST API endpoint (default: `http://localhost:8000`)

## Tools

All 10 tools are organized into two groups: read-path and write-path.

### Read-Path Tools (5)

#### 1. vault_resolve_context

Resolve the scope for a repository and return all applicable operational pages.

**Use case:** Entry point for understanding context about a codebase. Discovers the repo-profile and all procedures/guides that apply.

**Input:**
```json
{
  "repo": "anvil",
  "include_full": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `repo` | string | yes | Repository name (e.g., "anvil", "forge") |
| `include_full` | boolean | no | Return full pages instead of summaries (default: false) |

**Example output:**
```json
{
  "entry_point": {
    "id": "repos/anvil.md",
    "title": "Anvil Repository",
    "description": "Main repository for Anvil...",
    "type": "repo-profile",
    "mode": "operational",
    "scope": { "program": "anvil-forge-vault", "repo": "anvil" }
  },
  "operational_pages": [ ... ],
  "scope": { "program": "anvil-forge-vault", "repo": "anvil" }
}
```

#### 2. vault_search

Search the knowledge base using hybrid search (keyword + semantic + reranking).

**Use case:** Exploratory queries or when you don't know the exact page title.

**Input:**
```json
{
  "query": "how to deploy",
  "mode": "operational",
  "type": "guide",
  "limit": 5
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | Natural language search query |
| `mode` | string | no | Filter: "reference", "operational", or "keystone" |
| `type` | string | no | Filter: "repo-profile", "guide", "concept", "procedure", "keystone", "learning" |
| `scope` | object | no | Scope filter (keys: "program", "repo") |
| `limit` | number | no | Max results (default: 10, max: 100) |

**Example output:**
```json
{
  "results": [
    {
      "id": "guides/deployment.md",
      "title": "Deployment Guide",
      "description": "Step-by-step deployment procedures",
      "type": "guide",
      "mode": "operational",
      "relevance_score": 0.95
    }
  ],
  "total": 1
}
```

#### 3. vault_get_page

Retrieve the full content of a specific page by its identifier (file path).

**Use case:** Get complete content after finding a page via search or resolve-context.

**Input:**
```json
{
  "id": "guides/deployment.md"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | File path or title identifier |

**Example output:**
```json
{
  "id": "guides/deployment.md",
  "title": "Deployment Guide",
  "description": "...",
  "type": "guide",
  "mode": "operational",
  "scope": { "program": "anvil-forge-vault" },
  "body": "# Deployment Guide\n\n1. Prepare environment\n2. Run deployment script...",
  "related": ["guides/rollback.md"],
  "depends_on": [],
  "consumed_by": ["services/api.md"]
}
```

#### 4. vault_get_related

Follow links from a page to find related pages (dependencies, dependents, cross-cutting applicability).

**Use case:** Explore connected knowledge or follow keystone navigation.

**Input:**
```json
{
  "id": "guides/deployment.md"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Source page identifier |

**Example output:**
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

#### 5. vault_list_by_scope

List and filter pages by scope, mode, type, and tags.

**Use case:** Browse all pages for a specific program or repo.

**Input:**
```json
{
  "scope": { "program": "anvil-forge-vault" },
  "mode": "operational",
  "limit": 20
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scope` | object | yes | Scope filter (keys: "program", "repo"; at least one required) |
| `mode` | string | no | Filter: "reference", "operational", "keystone" |
| `type` | string | no | Filter by page type |
| `tags` | array | no | Filter by tags (AND logic) |
| `limit` | number | no | Max results (default: 50, max: 100) |

**Example output:**
```json
{
  "pages": [
    {
      "id": "guides/deployment.md",
      "title": "Deployment Guide",
      "type": "guide",
      "mode": "operational",
      "scope": { "program": "anvil-forge-vault" }
    }
  ],
  "total": 1
}
```

### Write-Path Tools (5)

#### 6. vault_validate_page

Validate a markdown page (with YAML frontmatter) against schema and registries.

**Use case:** Ensure a new or modified page meets all requirements before committing.

**Input:**
```json
{
  "content": "---\ntitle: My Guide\ntype: guide\nmode: operational\nscope:\n  program: anvil-forge-vault\n---\n\n# My Guide\nContent here..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | yes | Full markdown with YAML frontmatter |

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

#### 7. vault_suggest_metadata

Suggest frontmatter metadata based on content analysis, registries, and KB search.

**Use case:** Auto-fill metadata when creating or converting pages.

**Input:**
```json
{
  "content": "# Deployment Procedure\n\nSteps to deploy to production:\n1. ...",
  "hints": { "scope.program": "anvil-forge-vault" }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | yes | Page markdown content (without frontmatter needed) |
| `hints` | object | no | Pre-filled metadata (e.g., scope, owner) |

**Example output:**
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
      "confidence": 0.8,
      "reason": "Keywords matched in registry"
    }
  }
}
```

#### 8. vault_check_duplicates

Score content similarity against existing KB pages.

**Use case:** Detect potential overlap before committing a new page.

**Input:**
```json
{
  "title": "How to Deploy",
  "content": "Steps to deploy the application...",
  "threshold": 0.75
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | yes | Page title |
| `content` | string | yes | Page content |
| `threshold` | number | no | Similarity threshold (0-1, default: 0.75) |

**Example output:**
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

#### 9. vault_get_schema

Retrieve the full schema definition and all registry contents.

**Use case:** Discover available page types, field constraints, and registry values before generating pages.

**Input:** (no arguments)

**Example output:**
```json
{
  "page_types": {
    "guide": {
      "description": "Practical how-to guide",
      "required_fields": ["title", "type", "mode"],
      "optional_fields": ["tags", "scope", "owner"]
    },
    "procedure": { ... }
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

#### 10. vault_registry_add

Add a new entry to a registry (tags, repos, programs).

**Use case:** Register a new tag, repo, or program that doesn't exist in the schema.

**Input:**
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

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `registry` | string | yes | Registry name: "tags", "repos", or "programs" |
| `entry` | object | yes | Entry with: `id` (required), `description`, `aliases` |

**Example output:**
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

## Write-Path Workflow Example

A typical workflow for creating a new knowledge page:

1. **Get the schema** — understand available page types and constraints
2. **Suggest metadata** — let the service analyze your content and propose frontmatter
3. **Validate the page** — check for errors before committing
4. **Check for duplicates** — ensure you're not overlapping with existing pages
5. **Add registry entries** — if validation rejected values that should be new registry entries
6. **Commit the page** — write to the knowledge repository

```bash
# Step 1: Fetch schema to understand structure
vault_get_schema
# → Learn available page types, registries, constraints

# Step 2: Analyze content and suggest metadata
vault_suggest_metadata
# → Returns suggestions for type, mode, tags based on content

# Step 3: Build frontmatter and validate
vault_validate_page
# → If errors: fix or use vault_registry_add to add new entries

# Step 4: Check for duplicates
vault_check_duplicates
# → If recommendation is "merge", consider merging with existing page

# Step 5: (Optional) Add any new registry entries
vault_registry_add
# → Add new tags, programs, or repos as needed

# Step 6: Commit to knowledge repo
# → Write validated .md file to knowledge-base repo
```

## Development

```bash
# Install dependencies
npm install

# Build
npm run build

# Watch mode (auto-rebuild on changes)
npm run dev
```

## Error Handling

If the Knowledge Service API is unavailable or returns an error, tools return error responses with `isError: true`:

```json
{
  "content": [
    {
      "type": "text",
      "text": "Error: HTTP 404: Page not found..."
    }
  ],
  "isError": true
}
```

## Dependencies

- `@modelcontextprotocol/sdk` — MCP protocol implementation
- `typescript` — TypeScript compiler
- `node-fetch` — Built-in (Node.js 18+)

## License

MIT
