"""
FastAPI application entry point for Vault Knowledge Service.

Sets up the REST API with:
- QMD adapter initialization
- Collection setup (shared + workspace)
- Schema loader initialization
- Health and status endpoints
- All query and write operation endpoints
- Lifespan management for startup/shutdown
- Structured error handling with VaultError
- Request ID tracking
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config.settings import load_settings
from .layer1.qmd_adapter import QMDAdapter
from .layer2.schema import SchemaLoader
from .api.routes import router, get_store, get_schema_loader
from .sync.daemon import start_sync_daemon, stop_sync_daemon
from .errors import VaultError, VaultErrorResponse, VaultErrorDetail, ErrorCode


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

    Handles startup and shutdown:
    - Startup: Initialize QMD adapter, setup collections, start sync daemon
    - Shutdown: Cleanup resources
    """
    # ============================================================================
    # STARTUP
    # ============================================================================
    logger.info("Starting Vault Knowledge Service...")

    # Load configuration (CLI > env > config file > defaults)
    settings, sources = load_settings()

    logger.info("Vault configuration resolved:")
    settings.log_sources(sources)

    # Initialize QMD adapter
    logger.info("Initializing QMD adapter...")
    adapter = QMDAdapter(index_name=settings.qmd_index_name)

    # Setup collections (idempotent)
    logger.info("Setting up QMD collections...")
    try:
        adapter.ensure_collections(
            shared_path=settings.knowledge_repo_path,
            workspace_path=settings.workspace_path
        )
        logger.info("Collections setup complete")
    except Exception as e:
        logger.error("Failed to setup collections: %s", e)
        raise

    # Store adapter in app state for dependency injection
    app.state.store = adapter

    # Load schema + registries from _schema/ directory in knowledge repo
    schema_dir = f"{settings.knowledge_repo_path}/_schema"
    logger.info("Loading schema from %s ...", schema_dir)
    schema_loader = SchemaLoader(schema_dir)
    try:
        schema_loader.load()
        logger.info("Schema loaded successfully")
    except Exception as e:
        logger.warning("Schema load failed (write-path will be degraded): %s", e)
        # Non-fatal — read path still works without schema

    app.state.schema_loader = schema_loader

    # Start sync daemon (git pull loop + workspace watcher)
    logger.info("Starting sync daemon...")
    git_pull_task, workspace_observer = await start_sync_daemon(
        store=adapter,
        knowledge_repo_path=settings.knowledge_repo_path,
        workspace_path=settings.workspace_path,
        sync_interval=settings.sync_interval,
        debounce_seconds=5.0
    )

    app.state.git_pull_task = git_pull_task
    app.state.workspace_observer = workspace_observer

    logger.info("Vault Knowledge Service started successfully")

    yield

    # ============================================================================
    # SHUTDOWN
    # ============================================================================
    logger.info("Shutting down Vault Knowledge Service...")
    await stop_sync_daemon(
        git_pull_task=app.state.git_pull_task,
        workspace_observer=app.state.workspace_observer
    )
    logger.info("Vault Knowledge Service shutdown complete")


# Create FastAPI app with lifespan
app = FastAPI(
    title="Vault Knowledge Service",
    description="Shared knowledge layer — curated documentation, repo profiles, architecture, conventions",
    version="0.2.0",
    lifespan=lifespan
)


# ============================================================================
# Exception Handlers
# ============================================================================

@app.exception_handler(VaultError)
async def vault_error_handler(request: Request, exc: VaultError) -> JSONResponse:
    """Handle VaultError exceptions with structured error response."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response().model_dump(),
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with generic error response."""
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    request_id = str(uuid.uuid4())
    return JSONResponse(
        status_code=500,
        content=VaultErrorResponse(
            error=VaultErrorDetail(
                code=ErrorCode.INTERNAL_ERROR.value,
                message="An internal error occurred",
                request_id=request_id,
            )
        ).model_dump(),
    )


# ============================================================================
# Middleware
# ============================================================================

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add a unique request ID to each request."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Override the get_store dependency to use app.state.store
def get_store_override(request: Request):
    """Dependency override to inject SearchStore from app state."""
    return request.app.state.store


app.dependency_overrides[get_store] = get_store_override


def get_schema_loader_override(request: Request):
    """Dependency override to inject SchemaLoader from app state."""
    return request.app.state.schema_loader


app.dependency_overrides[get_schema_loader] = get_schema_loader_override

# Include API routes
app.include_router(router, prefix="", tags=["knowledge"])


@app.get("/health")
async def health_check():
    """
    Lightweight health check — no QMD subprocess, no I/O.
    Use GET /status for full QMD index diagnostics.
    """
    return {"status": "ok", "service": "knowledge-service", "version": "0.1.0"}


@app.get("/status")
async def full_status(request: Request):
    """
    Full QMD index status (slow — spawns qmd subprocess).
    Separated from /health so liveness probes stay fast.
    """
    try:
        store = request.app.state.store
        index_status = await asyncio.to_thread(store.status)
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "service": "knowledge-service",
                "version": "0.1.0",
                "index": index_status
            }
        )
    except Exception as e:
        logger.error("Status check failed: %s", e)
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "service": "knowledge-service",
                "version": "0.1.0",
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
            "status": "GET /status",
            "resolve_context": "POST /resolve-context",
            "search": "POST /search",
            "get_page": "POST /get-page",
            "get_related": "POST /get-related",
            "list_by_scope": "POST /list-by-scope",
            "validate_page": "POST /validate-page",
            "suggest_metadata": "POST /suggest-metadata",
            "check_duplicates": "POST /check-duplicates",
            "schema": "GET /schema",
            "registry_add": "POST /registry/add"
        },
        "docs": "/docs"
    }


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Vault Knowledge Service")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Server port (default: 8000)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--knowledge-repo",
        type=str,
        default=None,
        help="Path to knowledge repository"
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default=None,
        help="Path to workspace directory"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config file"
    )
    args = parser.parse_args()

    host = args.host or "0.0.0.0"
    port = args.port or 8000

    uvicorn.run(app, host=host, port=port, log_level="info")
