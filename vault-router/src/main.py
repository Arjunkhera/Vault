"""
Vault Router — FastAPI service that routes requests to N vault instances.

Sits between vault-mcp and N knowledge-service instances.
Implements the same REST API as knowledge-service:
  - Fan-out endpoints: search, resolve-context, list-by-scope, check-duplicates, suggest-metadata
  - Routed endpoints: get-page, get-related, schema, validate-page, write-page, registry/add
    (routed by UUID lookup → vault name, or explicit ?vault= parameter)

Startup sequence:
  1. Load settings from environment variables
  2. Initialize httpx.AsyncClient pool
  3. Verify each configured vault is reachable (non-fatal — logs warnings)
  4. Serve requests
"""

import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .client import VaultClient
from .settings import VaultRouterSettings, load_settings

logger = logging.getLogger(__name__)


def configure_logging(log_level: str) -> None:
    """Configure structured logging."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """App lifespan: initialize resources on startup, clean up on shutdown."""

    # Load and validate settings
    settings = load_settings()
    configure_logging(settings.log_level)
    logger.info("Starting Vault Router with %d vault(s): %s",
                len(settings.vault_endpoints), list(settings.vault_endpoints.keys()))

    # Initialize HTTP client pool
    vault_client = VaultClient()
    await vault_client.start()

    # Store in app.state for dependency injection
    app.state.settings = settings
    app.state.vault_client = vault_client

    # Non-fatal startup health check — log warnings for unreachable vaults
    logger.info("Checking upstream vault health...")
    health_tasks = [
        vault_client.health_check(name, url)
        for name, url in settings.vault_endpoints.items()
    ]
    health_results = await asyncio.gather(*health_tasks)
    for name, result in zip(settings.vault_endpoints.keys(), health_results):
        if result["status"] == "healthy":
            logger.info("  ✓ %s — healthy (%dms)", name, result.get("latency_ms", 0))
        else:
            logger.warning("  ✗ %s — %s (%s)", name, result["status"], result.get("error", ""))

    logger.info("Vault Router ready")

    yield

    # Shutdown
    logger.info("Shutting down Vault Router...")
    await vault_client.stop()
    logger.info("Vault Router stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Vault Router",
        description=(
            "Multi-vault orchestration layer. Routes MCP tool calls to N vault instances "
            "with fan-out reads and UUID-based write routing."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register routes
    from .routes import router
    app.include_router(router)

    return app


app = create_app()
