# Knowledge Service MCP Client

A Model Context Protocol (MCP) thin client for the Knowledge Service. This package provides MCP tools that translate to REST API calls to the Knowledge Service, enabling AI agents to query organizational knowledge.

## Overview

This is a **thin client** — it does not contain any knowledge logic itself. It simply translates MCP tool calls into HTTP POST requests to the Knowledge Service REST API. The Knowledge Service handles all the intelligence: scope-chain resolution, progressive disclosure, semantic search, and link navigation.

## Architecture

```
Cursor IDE
  └── MCP: @fdp-docmgmt/knowledge-mcp
        └── HTTP calls to localhost:8000
              │
              ▼
        Knowledge Service (Docker container)
          ├── REST API (:8000)
          ├── Layer 2: Knowledge Logic
          └── Layer 1: QMD Search
```

## Installation

```bash
npm install
npm run build
```

## Usage

### As an MCP Server

The package is designed to be configured in Cursor's MCP settings:

```json
{
  "mcpServers": {
    "knowledge": {
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

### Configuration

The server accepts the following command-line arguments:

- `--endpoint <url>` - Knowledge Service REST API endpoint (default: `http://localhost:8000`)

## Available Tools

### 1. `knowledge_resolve_context`

Resolve the full scope chain for a repository and return all applicable operational pages.

**Use case:** Get all relevant procedures, guides, and conventions for a codebase.

**Input:**
- `repo` (string, required) - Repository name (e.g., "document-service")
- `include_full` (boolean, optional) - Return full page content vs summaries (default: false)

**Example:**
```json
{
  "repo": "document-service",
  "include_full": false
}
```

### 2. `knowledge_search`

Search the knowledge base using hybrid search (keyword + semantic + reranking).

**Use case:** Exploratory queries or finding pages when you don't know the exact title.

**Input:**
- `query` (string, required) - Search query
- `mode` (string, optional) - Filter by "reference", "operational", or "keystone"
- `type` (string, optional) - Filter by page type
- `scope` (object, optional) - Filter by organizational scope
- `limit` (number, optional) - Max results (default: 10)

**Example:**
```json
{
  "query": "how to deploy to production",
  "mode": "operational",
  "limit": 5
}
```

### 3. `knowledge_get_page`

Retrieve the full content of a specific knowledge page by its ID.

**Use case:** Get complete page content after finding it via search.

**Input:**
- `id` (string, required) - Page identifier (file path)

**Example:**
```json
{
  "id": "services/document-service.md"
}
```

### 4. `knowledge_get_related`

Follow links from a page to find related pages.

**Use case:** Explore connected knowledge or follow keystone navigation paths.

**Input:**
- `id` (string, required) - Source page identifier

**Example:**
```json
{
  "id": "services/document-service.md"
}
```

### 5. `knowledge_list_by_scope`

List and filter knowledge pages by organizational scope and criteria.

**Use case:** Browse pages for a specific team, service, or organization.

**Input:**
- `scope` (object, required) - Scope filter (at least one field)
- `mode` (string, optional) - Filter by page mode
- `type` (string, optional) - Filter by page type
- `tags` (array, optional) - Filter by tags (AND logic)
- `limit` (number, optional) - Max results (default: 50)

**Example:**
```json
{
  "scope": {
    "org": "DME",
    "squad": "Backend"
  },
  "mode": "operational"
}
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

All tools return structured error messages if the Knowledge Service API is unavailable or returns an error. Errors are returned as text content with `isError: true`.

## Dependencies

- `@modelcontextprotocol/sdk` - MCP protocol implementation
- `typescript` - TypeScript compiler

## License

MIT
