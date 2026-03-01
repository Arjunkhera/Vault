"""
FastAPI application entry point for Vault Knowledge Service.

Sets up the REST API with:
- QMD adapter initialization
- Collection setup (shared + workspace)
- VaultError exception handler
- Health endpoint
- All 5 query operation endpoints
- Lifespan management for startup/shutdown
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .errors import VaultError
from .layer1.qmd_adapter import QMDAdapter
from .config.type_registry import TypeRegistry
from .api.routes import router, get_store
from .sync.daemon import start_sync_daemon, stop_sync_daemon


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI app.

    Startup: Initialize QMD adapter, setup collections, start sync daemon
    Shutdown: Cleanup resources
    """
    logger.info("Starting Vault Knowledge Service...")

    # Read environment variables
    qmd_index_name = os.getenv("QMD_INDEX_NAME", "knowledge")
    knowledge_repo_path = os.getenv("KNOWLEDGE_REPO_PATH", "/data/knowledge-repo")
    workspace_path = os.getenv("WORKSPACE_PATH", "/workspace")
    sync_interval = int(os.getenv("SYNC_INTERVAL", "300"))
    types_path = os.getenv("VAULT_TYPES_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "types"))

    logger.info(
        "Configuration: QMD_INDEX=%s, KNOWLEDGE_REPO=%s, WORKSPACE=%s, SYNC_INTERVAL=%ds, TYPES=%s",
        qmd_index_name, knowledge_repo_path, workspace_path, sync_interval, types_path
    )

    # Initialize QMD adapter
    logger.info("Initializing QMD adapter...")
    adapter = QMDAdapter(index_name=qmd_index_name)

    # Setup collections (idempotent)
    logger.info("Setting up QMD collections...")
    try:
        adapter.ensure_collections(
            shared_path=knowledge_repo_path,
            workspace_path=workspace_path
        )
        logger.info("Collections setup complete")
    except Exception as e:
        logger.error("Failed to setup collections: %s", e)
        raise

    # Load type registry
    logger.info("Loading type definitions...")
    type_registry = TypeRegistry()
    try:
        type_registry.load_from_directory(types_path)
        logger.info(
            "Type registry loaded: %d types (%s)",
            len(type_registry.type_ids()),
            ", ".join(type_registry.type_ids())
        )
    except Exception as e:
        logger.error("Failed to load type definitions: %s", e)
        raise

    # Store adapter and type registry in app state for dependency injection
    app.state.store = adapter
    app.state.type_registry = type_registry

    # Start sync daemon (git pull loop + workspace watcher)
    logger.info("Starting sync daemon...")
    git_pull_task, workspace_observer = await start_sync_daemon(
        store=adapter,
        knowledge_repo_path=knowledge_repo_path,
        workspace_path=workspace_path,
        sync_interval=sync_interval,
        debounce_seconds=5.0
    )

    app.state.git_pull_task = git_pull_task
    app.state.workspace_observer = workspace_observer

    logger.info("Vault Knowledge Service started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Vault Knowledge Service...")
    await stop_sync_daemon(
        git_pull_task=app.state.git_pull_task,
        workspace_observer=app.state.workspace_observer
    )
    logger.info("Vault Knowledge Service shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Vault Knowledge Service",
    description="Shared knowledge layer — curated documentation, repo profiles, architecture, conventions",
    version="0.2.0",
    lifespan=lifespan
)


# Global exception handler for VaultError
@app.exception_handler(VaultError)
async def vault_error_handler(request: Request, exc: VaultError):
    """Convert VaultError to structured JSON response."""
    logger.warning("VaultError [%s]: %s", exc.code.value, exc.message)
    return JSONResponse(
        status_code=_error_status_code(exc),
        content=exc.to_dict()
    )


def _error_status_code(exc: VaultError) -> int:
    """Map error codes to HTTP status codes."""
    from .errors import ErrorCode
    mapping = {
        ErrorCode.PAGE_NOT_FOUND: 404,
        ErrorCode.TYPE_NOT_FOUND: 404,
        ErrorCode.VALIDATION_ERROR: 422,
        ErrorCode.REQUIRED_FIELD_MISSING: 422,
        ErrorCode.INVALID_FIELD_VALUE: 422,
        ErrorCode.SCOPE_INVALID: 422,
        ErrorCode.SEARCH_ERROR: 502,
        ErrorCode.SYNC_ERROR: 502,
        ErrorCode.INDEX_ERROR: 502,
    }
    return mapping.get(exc.code, 500)


# Override get_store dependency to use app.state.store
def get_store_override(request: Request):
    """Dependency override to inject SearchStore from app state."""
    return request.app.state.store


app.dependency_overrides[get_store] = get_store_override

# Include API routes
app.include_router(router, prefix="", tags=["knowledge"])


@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint."""
    try:
        store = request.app.state.store
        index_status = store.status()
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "service": "vault-knowledge-service",
                "version": "0.2.0",
                "index": index_status
            }
        )
    except Exception as e:
        logger.error("Health check failed: %s", e)
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "service": "vault-knowledge-service",
                "version": "0.2.0",
                "error": str(e)
            }
        )


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "service": "Vault Knowledge Service",
        "version": "0.2.0",
        "description": "Shared knowledge layer — curated documentation, repo profiles, architecture, conventions",
        "endpoints": {
            "health": "GET /health",
            "resolve_context": "POST /resolve-context",
            "search": "POST /search",
            "get_page": "POST /get-page",
            "get_related": "POST /get-related",
            "list_by_scope": "POST /list-by-scope"
        },
        "docs": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
