# automation

Knowledge Service platform for Intuit developer agents. Provides a centralized, searchable knowledge base that agents can query via MCP tools to get context about services, repos, teams, and patterns.

## Components

| Component | Path | Description |
|-----------|------|-------------|
| **Knowledge Service** | `knowledge-service/` | Python FastAPI server. Indexes knowledge pages via QMD search engine, serves them over REST API. Runs in a Docker/Podman container on port 8000. |
| **Knowledge MCP** | `knowledge-mcp/` | TypeScript MCP thin client. Connects Cursor agents to the Knowledge Service. Translates MCP tool calls into HTTP requests. |
| **Bootstrap Pipeline** | `bootstrap-pipeline/` | Python CLI for bulk-ingesting repos or local docs into knowledge pages. Used for seeding the knowledge base at scale. |

## Quick Setup

**Open this repo in Cursor and ask the agent: "Help me set up the Knowledge Service."**

The agent will walk you through:
1. Checking prerequisites (Podman/Docker, Node.js)
2. Configuring your GitHub token
3. Building and starting the Knowledge Service container
4. Building the MCP client
5. Configuring the MCP in Cursor

See `.cursor/rules/setup-guide.mdc` for the full setup flow.

## Manual Setup (if not using the agent)

```bash
# 1. Configure your GitHub token
cp knowledge-service/.env.example knowledge-service/.env
# Edit .env and add your github.intuit.com token

# 2. Build and start the Knowledge Service
cd knowledge-service
podman build -t knowledge-service .
podman run -d --name knowledge-service -p 8000:8000 \
  --env-file .env \
  -e KNOWLEDGE_REPO=akhera/knowledge-base \
  -e SYNC_INTERVAL=300 \
  knowledge-service

# 3. Wait for startup (~5-7 min for initial indexing)
podman logs -f knowledge-service
# Look for: "Application startup complete."

# 4. Verify
curl http://localhost:8000/health

# 5. Build the MCP client
cd ../knowledge-mcp
npm install && npm run build

# 6. Add to ~/.cursor/mcp.json under "mcpServers":
#   "knowledge": {
#     "command": "node",
#     "args": ["<path-to-repo>/knowledge-mcp/dist/index.js", "--endpoint", "http://localhost:8000"]
#   }

# 7. Restart Cursor to pick up the MCP config
```

## Architecture

```
Cursor IDE
  └── MCP: knowledge (knowledge-mcp)
        └── HTTP → localhost:8000
              │
   ┌──────────┼──────────────────────────────────────┐
   │ Container│                                      │
   │          ▼                                      │
   │  FastAPI REST API (:8000)                       │
   │    ├── Knowledge Logic (scope chain, filters)   │
   │    └── QMD Search Engine (BM25 + vectors)       │
   │          └── akhera/knowledge-base (git clone)  │
   │                                                 │
   │  Sync Daemon: git pull every 5 min              │
   └─────────────────────────────────────────────────┘
```

## Available MCP Tools

After setup, Cursor agents have access to:

- `knowledge_search` — Search the knowledge base by natural language query
- `knowledge_get_page` — Get full content of a specific page
- `knowledge_resolve_context` — Get all context for a repo (scope chain + operational pages)
- `knowledge_get_related` — Follow links from a page to find related pages
- `knowledge_list_by_scope` — Browse pages by org, squad, service, or repo
- `knowledge_validate_page` — Validate a page against the schema
- `knowledge_suggest_metadata` — Get metadata suggestions for a new page
- `knowledge_get_schema` — Get the full schema + registries
- `knowledge_registry_add` — Add a new entry to a registry

## Data

The knowledge base lives at [`akhera/knowledge-base`](https://github.intuit.com/akhera/knowledge-base) on GitHub Enterprise. It contains markdown pages with YAML frontmatter covering services, repos, procedures, guides, and concepts. The container clones this repo at startup and syncs changes every 5 minutes.
