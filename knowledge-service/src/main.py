"""
FastAPI application entry point for Knowledge Service.

Sets up the REST API with:
- QMD adapter initialization
- Collection setup (shared + workspace)
- Health endpoint
- All 5 query operation endpoints
- Lifespan management for startup/shutdown
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .layer1.qmd_adapter import QMDAdapter
from .layer2.schema import SchemaLoader
from .api.routes import router, get_store, get_schema_loader
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
    
    Handles startup and shutdown:
    - Startup: Initialize QMD adapter, setup collections, start sync daemon
    - Shutdown: Cleanup resources
    """
    # ============================================================================
    # STARTUP
    # ============================================================================
    logger.info("Starting Knowledge Service...")
    
    # Read environment variables
    qmd_index_name = os.getenv("QMD_INDEX_NAME", "knowledge")
    knowledge_repo_path = os.getenv("KNOWLEDGE_REPO_PATH", "/data/knowledge-repo")
    workspace_path = os.getenv("WORKSPACE_PATH", "/workspace")
    sync_interval = int(os.getenv("SYNC_INTERVAL", "300"))  # 5 minutes default
    
    logger.info(f"Configuration:")
    logger.info(f"  QMD_INDEX_NAME: {qmd_index_name}")
    logger.info(f"  KNOWLEDGE_REPO_PATH: {knowledge_repo_path}")
    logger.info(f"  WORKSPACE_PATH: {workspace_path}")
    logger.info(f"  SYNC_INTERVAL: {sync_interval}s")
    
    # Initialize QMD adapter
    logger.info("Initializing QMD adapter...")
    adapter = QMDAdapter(index_name=qmd_index_name)
    
    # Setup collections (idempotent - safe to call multiple times)
    logger.info("Setting up QMD collections...")
    try:
        adapter.ensure_collections(
            shared_path=knowledge_repo_path,
            workspace_path=workspace_path
        )
        logger.info("Collections setup complete")
    except Exception as e:
        logger.error(f"Failed to setup collections: {e}")
        raise
    
    # Store adapter in app state for dependency injection
    app.state.store = adapter
    
    # Load schema + registries from _schema/ directory in knowledge repo
    schema_dir = os.path.join(knowledge_repo_path, "_schema")
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
        knowledge_repo_path=knowledge_repo_path,
        workspace_path=workspace_path,
        sync_interval=sync_interval,
        debounce_seconds=5.0
    )
    
    # Store sync daemon components in app state for cleanup
    app.state.git_pull_task = git_pull_task
    app.state.workspace_observer = workspace_observer
    
    logger.info("Knowledge Service started successfully")
    
    yield
    
    # ============================================================================
    # SHUTDOWN
    # ============================================================================
    logger.info("Shutting down Knowledge Service...")
    
    # Stop sync daemon gracefully
    await stop_sync_daemon(
        git_pull_task=app.state.git_pull_task,
        workspace_observer=app.state.workspace_observer
    )
    
    logger.info("Knowledge Service shutdown complete")


# Create FastAPI app with lifespan
app = FastAPI(
    title="Knowledge Service",
    description="Centralized, agent-oriented knowledge layer for Intuit",
    version="0.1.0",
    lifespan=lifespan
)


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
async def health_check(request: Request):
    """
    Health check endpoint.
    
    Returns service status and QMD index health information.
    
    Returns:
        JSON with status and index info
    """
    try:
        store = request.app.state.store
        index_status = store.status()
        
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
        logger.error(f"Health check failed: {e}")
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
    """
    Root endpoint with API information.
    
    Returns:
        JSON with service info and available endpoints
    """
    return {
        "service": "Knowledge Service",
        "version": "0.1.0",
        "description": "Centralized, agent-oriented knowledge layer for Intuit",
        "endpoints": {
            "health": "GET /health",
            "resolve_context": "POST /resolve-context",
            "search": "POST /search",
            "get_page": "POST /get-page",
            "get_related": "POST /get-related",
            "list_by_scope": "POST /list-by-scope",
            "validate_page": "POST /validate-page",
            "suggest_metadata": "POST /suggest-metadata",
            "schema": "GET /schema",
            "registry_add": "POST /registry/add",
        },
        "docs": "/docs"
    }


# Entry point for running with uvicorn directly
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
