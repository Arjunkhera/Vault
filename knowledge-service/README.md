# Knowledge Service

A centralized, agent-oriented knowledge layer for Intuit. Indexes markdown knowledge pages via QMD search, serves them over a REST API, and syncs with a GitHub-hosted knowledge base.

## Quick Start

```bash
# 1. Set up your GitHub token
cp .env.example .env
# Edit .env with your github.intuit.com token

# 2. Build the container image
podman build -t knowledge-service .
# (or: docker build -t knowledge-service .)

# 3. Start the container
podman run -d --name knowledge-service -p 8000:8000 \
  --env-file .env \
  -e KNOWLEDGE_REPO=akhera/knowledge-base \
  -e SYNC_INTERVAL=300 \
  knowledge-service

# 4. Wait for startup (~5-7 min for initial indexing)
podman logs -f knowledge-service
# Look for: "Application startup complete."

# 5. Verify
curl http://localhost:8000/health
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_TOKEN` | (required) | GitHub Enterprise token for cloning the knowledge repo |
| `KNOWLEDGE_REPO` | `akhera/knowledge-base` | GitHub repo path (org/repo format) |
| `SYNC_INTERVAL` | `300` | Git pull interval in seconds |
| `QMD_INDEX_NAME` | `knowledge` | QMD index name (isolates from other QMD indexes) |

## API Endpoints

### Read Path

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service status and QMD index health |
| `/resolve-context` | POST | Resolve scope chain + operational pages for a repo |
| `/search` | POST | Full-text search with progressive disclosure |
| `/get-page` | POST | Retrieve full page by ID |
| `/get-related` | POST | Follow links from a page to related pages |
| `/list-by-scope` | POST | Browse/filter pages by scope, mode, type, tags |

### Write Path

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/validate-page` | POST | Validate page content against schema + registries |
| `/suggest-metadata` | POST | Suggest frontmatter values from content analysis |
| `/check-duplicates` | POST | Check content similarity against existing KB pages |
| `/schema` | GET | Return full schema definition + all registries |
| `/registry/add` | POST | Add a new entry to a registry |

## Project Structure

```
knowledge-service/
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── requirements.txt
├── .env.example
└── src/
    ├── main.py                  # FastAPI app entry point
    ├── layer1/                  # Search/Storage (swappable)
    │   ├── interface.py         # Abstract SearchStore interface
    │   └── qmd_adapter.py      # QMD CLI implementation
    ├── layer2/                  # Knowledge Logic (stable)
    │   ├── frontmatter.py       # YAML frontmatter parser
    │   ├── scope_chain.py       # Scope-chain resolver
    │   ├── mode_filter.py       # Mode filtering + progressive disclosure
    │   ├── link_navigator.py    # Related page link traversal
    │   ├── schema.py            # SchemaLoader + PageValidator
    │   ├── suggester.py         # MetadataSuggester
    │   └── dedup.py             # DuplicateChecker
    ├── api/
    │   ├── models.py            # Pydantic request/response models
    │   └── routes.py            # All REST endpoints
    └── sync/
        └── daemon.py            # Git pull loop + file watcher
```

## Architecture

**Two-layer design:**

- **Layer 2 (Knowledge Logic)** — Stable. Scope-chain resolution, mode filtering, progressive disclosure, link navigation, schema validation, metadata suggestion.
- **Layer 1 (Search/Storage)** — Swappable. Currently QMD via subprocess. Future: Elasticsearch, Document Service.

**Container internals:**

```
┌─ Container ────────────────────────────────────────┐
│  Python 3.12 + Node.js 22 + QMD 1.0.8             │
│                                                    │
│  FastAPI REST API (:8000)                          │
│    ├── Layer 2: Knowledge Logic                    │
│    └── Layer 1: QMD Adapter                        │
│          └── Collection: "shared"                   │
│                └── /data/knowledge-repo/            │
│                                                    │
│  Sync Daemon                                       │
│    ├── git pull every SYNC_INTERVAL seconds         │
│    └── Triggers QMD re-index on new commits         │
└────────────────────────────────────────────────────┘
```

## Container Management

```bash
podman stop knowledge-service       # Stop
podman start knowledge-service      # Start (preserves state)
podman restart knowledge-service    # Restart
podman rm -f knowledge-service      # Remove (next run re-clones)
podman logs -f knowledge-service    # Follow logs
podman logs --tail 50 knowledge-service  # Recent logs
```
