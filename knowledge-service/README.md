# Knowledge Service v0

A centralized, agent-oriented knowledge layer for Intuit, packaged as a Docker container with QMD-powered search, exposed via REST API and consumed through a thin MCP client.

## Project Structure

```
knowledge-service/
├── README.md                  # This file
├── requirements.txt           # Python dependencies
├── Dockerfile                 # ✅ Docker image definition
├── docker-compose.yml         # ✅ Docker Compose configuration
├── entrypoint.sh              # ✅ Container startup script
├── config/                    # Configuration files (QMD index config, generated at runtime)
└── src/
    ├── __init__.py
    ├── main.py                # ✅ FastAPI app entry point
    ├── layer1/                # Search/Storage abstraction layer
    │   ├── __init__.py
    │   ├── interface.py       # ✅ Abstract SearchStore interface
    │   └── qmd_adapter.py     # ✅ QMD implementation
    ├── layer2/                # Knowledge logic layer
    │   ├── __init__.py
    │   ├── frontmatter.py     # ✅ YAML frontmatter parser
    │   ├── scope_chain.py     # ✅ Scope-chain resolver
    │   ├── mode_filter.py     # ✅ Mode filtering + progressive disclosure
    │   └── link_navigator.py  # ✅ Related page link traversal
    ├── api/
    │   ├── __init__.py
    │   ├── models.py          # ✅ Pydantic request/response models
    │   └── routes.py          # ✅ 5 REST endpoints
    └── sync/
        ├── __init__.py
        └── daemon.py          # ✅ Sync daemon (git pull + file watch)
```

## Status: Phases 1-6 ✅ COMPLETE

### Completed Phases

- ✅ **Phase 1**: Python project scaffold and Pydantic models
- ✅ **Phase 2**: Layer 1 (QMD Adapter with abstract interface)
- ✅ **Phase 3**: Layer 2 (Knowledge Logic: frontmatter, scope chain, filters, link navigator)
- ✅ **Phase 4**: REST API (5 endpoints + FastAPI app entry point)
- ✅ **Phase 5**: Sync Daemon (git pull loop + workspace watcher + entrypoint.sh)
- ✅ **Phase 6**: Docker Image (Dockerfile + docker-compose.yml)

### Quick Start with Docker

**Prerequisites:**
- Docker and Docker Compose installed
- GitHub token with access to `github.intuit.com`
- Anvil workspace directory at `~/anvil-workspace` (or customize the path)

**Build and Run:**

```bash
# Set your GitHub token
export GITHUB_TOKEN=<your-github-token>

# Build and start the service
docker-compose up -d

# Check logs
docker-compose logs -f

# Check health
curl http://localhost:8000/health

# Stop the service
docker-compose down
```

**Test the API:**

```bash
# Resolve context for a repo
curl -X POST http://localhost:8000/resolve-context \
  -H "Content-Type: application/json" \
  -d '{"repo": "document-service"}'

# Search for pages
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication", "limit": 5}'

# Get a specific page
curl -X POST http://localhost:8000/get-page \
  -H "Content-Type: application/json" \
  -d '{"id": "/workspace/path/to/page.md"}'
```

**Environment Variables:**

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | (required) | GitHub token for cloning knowledge repo |
| `KNOWLEDGE_REPO` | `fdp-docmgmt/knowledge-base` | GitHub repo path |
| `SYNC_INTERVAL` | `300` | Git pull interval in seconds (5 min) |
| `QMD_INDEX_NAME` | `knowledge` | QMD index name |

**Volume Mounts:**

- `/workspace` - Your Anvil workspace (read-only), mounted from `~/anvil-workspace`
- `/data/knowledge-repo` - Knowledge repo clone (managed by container)

## API Contract (5 Operations)

| Operation | Endpoint | Purpose |
|-----------|----------|---------|
| **resolve-context** | `POST /resolve-context` | Given a repo/service, return all operational pages for the scope chain |
| **search** | `POST /search` | Full-text + semantic search with progressive disclosure |
| **get-page** | `POST /get-page` | Retrieve full page by identifier |
| **get-related** | `POST /get-related` | Follow links from a page (enables keystone navigation) |
| **list-by-scope** | `POST /list-by-scope` | Browse/filter pages by scope, type, mode, tags |

## Next Steps (Future Phases)

- **Phase 7**: MCP Thin Client (npm package with 5 tool definitions)
- **Phase 8**: Validation (integration tests and end-to-end testing)

## Dependencies

All Python dependencies are specified in `requirements.txt`:
- FastAPI 0.115.0 - REST API framework
- Uvicorn 0.30.0 - ASGI server
- PyYAML 6.0.2 - YAML parsing
- python-frontmatter 1.1.0 - Markdown frontmatter parsing
- watchdog 4.0.0 - File system watching
- httpx 0.27.0 - HTTP client
- pydantic 2.9.0 - Data validation and models

## Architecture

The service uses a two-layer architecture:

**Layer 2: Knowledge Logic** (stable)
- Frontmatter parsing
- Scope-chain resolution
- Mode filtering and progressive disclosure
- Link navigation

**Layer 1: Search/Storage** (swappable)
- Abstract interface
- QMD implementation (v0)
- Future: Elasticsearch, Document Service

This separation allows the search backend to evolve independently from the knowledge logic.
