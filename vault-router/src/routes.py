"""
Vault Router routes — health check and registry status endpoints.

Full fan-out and routed endpoints are implemented in B2, B3, B4.
This module contains only the infrastructure endpoints for B1.
"""

import logging
import asyncio
from typing import Any, Annotated

from fastapi import APIRouter, Request, Depends

from .client import VaultClient
from .settings import VaultRouterSettings
from .uuid_registry import CrossVaultUUIDRegistry

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Dependency helpers ────────────────────────────────────────────────────────

def get_settings(request: Request) -> VaultRouterSettings:
    return request.app.state.settings


def get_vault_client(request: Request) -> VaultClient:
    return request.app.state.vault_client


SettingsDepends = Annotated[VaultRouterSettings, Depends(get_settings)]
ClientDepends = Annotated[VaultClient, Depends(get_vault_client)]


def get_uuid_registry(request: Request) -> CrossVaultUUIDRegistry:
    return request.app.state.uuid_registry

UUIDRegistryDepends = Annotated[CrossVaultUUIDRegistry, Depends(get_uuid_registry)]


# ── Health check ──────────────────────────────────────────────────────────────

@router.get("/health")
async def health(settings: SettingsDepends, vault_client: ClientDepends) -> dict[str, Any]:
    """
    Health check for the router and all upstream vault instances.

    Returns:
      - status: "healthy" if all vaults are reachable, "degraded" if some are down
      - vaults: per-vault health status with latency
    """
    health_tasks = [
        vault_client.health_check(name, url)
        for name, url in settings.vault_endpoints.items()
    ]
    health_results = await asyncio.gather(*health_tasks)

    vault_statuses: dict[str, Any] = {}
    for name, result in zip(settings.vault_endpoints.keys(), health_results):
        vault_statuses[name] = result

    overall = (
        "healthy"
        if all(v["status"] == "healthy" for v in vault_statuses.values())
        else "degraded"
    )

    return {
        "status": overall,
        "router": "healthy",
        "vaults": vault_statuses,
    }


# ── Registry status ───────────────────────────────────────────────────────────

@router.get("/registry-status")
async def registry_status(
    settings: SettingsDepends,
    uuid_registry: UUIDRegistryDepends,
) -> dict[str, Any]:
    """Show UUID registry status: per-vault page counts and last refresh time."""
    status = uuid_registry.status()
    status["default_vault"] = settings.vault_default
    return status
