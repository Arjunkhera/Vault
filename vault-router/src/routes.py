"""
Vault Router routes — all HTTP endpoints.

Infrastructure (B1):  GET /health, GET /registry-status
Fan-out reads (B3):   POST /search, /resolve-context, /list-by-scope,
                      /check-duplicates, /suggest-metadata
Routed reads (B4):    POST /get-page, /get-related, /schema
Routed writes (B4):   POST /write-page, /validate-page, /registry/add
"""

import logging
import asyncio
from typing import Any, Annotated, Optional

from fastapi import APIRouter, Request, Depends, HTTPException

from .client import VaultClient
from .settings import VaultRouterSettings
from .uuid_registry import CrossVaultUUIDRegistry
from .fan_out import fan_out

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Dependency helpers ────────────────────────────────────────────────────────

def get_settings(request: Request) -> VaultRouterSettings:
    return request.app.state.settings


def get_vault_client(request: Request) -> VaultClient:
    return request.app.state.vault_client


def get_uuid_registry(request: Request) -> CrossVaultUUIDRegistry:
    return request.app.state.uuid_registry


SettingsDepends = Annotated[VaultRouterSettings, Depends(get_settings)]
ClientDepends = Annotated[VaultClient, Depends(get_vault_client)]
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


# ── Fan-out helper ────────────────────────────────────────────────────────────

def _parse_vault_filter(body: dict[str, Any]) -> Optional[list[str]]:
    """Extract optional vault filter from request body."""
    vault = body.get("vault")
    if vault is None:
        return None
    if isinstance(vault, str):
        return [vault]
    if isinstance(vault, list):
        return vault
    return None


def _resolve_vault_for_write(
    body: dict[str, Any],
    uuid_registry: CrossVaultUUIDRegistry,
    settings: VaultRouterSettings,
) -> str:
    """
    Determine which vault to route a write to.

    Priority:
      1. Explicit ?vault=name in body
      2. UUID lookup via registry (page_id field)
      3. Default vault
    """
    if "vault" in body and body["vault"]:
        return str(body["vault"])
    page_id = body.get("page_id") or body.get("id")
    if page_id:
        vault_name = uuid_registry.resolve(str(page_id))
        if vault_name:
            return vault_name
    return settings.vault_default


# ── Fan-out read endpoints (B3) ───────────────────────────────────────────────

@router.post("/search")
async def search(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
) -> dict[str, Any]:
    """
    Fan-out search to all (or filtered) vault instances.

    Merges results by relevance_score, deduplicates by UUID (highest score wins),
    and tags each result with source_vault.
    """
    body = await request.json()
    vault_filter = _parse_vault_filter(body)

    results = await fan_out(vault_client, settings.vault_endpoints, "/search", body, vault_filter)

    all_pages: list[dict[str, Any]] = []
    seen_uuids: set[str] = set()

    for vault_name, data in results.items():
        if "error" in data:
            continue
        for page in data.get("results", []):
            page_id = page.get("id")
            if page_id and page_id in seen_uuids:
                continue
            page["source_vault"] = vault_name
            all_pages.append(page)
            if page_id:
                seen_uuids.add(page_id)

    all_pages.sort(key=lambda p: p.get("relevance_score", 0.0), reverse=True)

    limit = body.get("limit", 10)
    return {"results": all_pages[:limit], "total": len(all_pages)}


@router.post("/resolve-context")
async def resolve_context(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
) -> dict[str, Any]:
    """
    Fan-out resolve-context to all (or filtered) vault instances.

    Picks the best entry_point by relevance_score and merges all operational_pages.
    """
    body = await request.json()
    vault_filter = _parse_vault_filter(body)

    results = await fan_out(vault_client, settings.vault_endpoints, "/resolve-context", body, vault_filter)

    best_entry: Optional[dict[str, Any]] = None
    best_score: float = -1.0
    all_operational: list[dict[str, Any]] = []
    merged_scope: dict[str, Any] = {}

    for vault_name, data in results.items():
        if "error" in data:
            continue
        entry = data.get("entry_point")
        if entry:
            score = entry.get("relevance_score", 0.0)
            if score > best_score:
                best_score = score
                best_entry = {**entry, "source_vault": vault_name}
        for page in data.get("operational_pages", []):
            all_operational.append({**page, "source_vault": vault_name})
        if data.get("scope"):
            merged_scope.update(data["scope"])

    return {
        "entry_point": best_entry,
        "operational_pages": all_operational,
        "scope": merged_scope,
    }


@router.post("/list-by-scope")
async def list_by_scope(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
) -> dict[str, Any]:
    """
    Fan-out list-by-scope to all (or filtered) vault instances.

    Merges all results, deduplicates by UUID, and applies router-level pagination.
    """
    body = await request.json()
    vault_filter = _parse_vault_filter(body)

    results = await fan_out(vault_client, settings.vault_endpoints, "/list-by-scope", body, vault_filter)

    seen_uuids: set[str] = set()
    all_pages: list[dict[str, Any]] = []

    for vault_name, data in results.items():
        if "error" in data:
            continue
        for page in data.get("results", []):
            page_id = page.get("id")
            if page_id and page_id in seen_uuids:
                continue
            page["source_vault"] = vault_name
            all_pages.append(page)
            if page_id:
                seen_uuids.add(page_id)

    limit = body.get("limit", 20)
    offset = body.get("offset", 0)
    paginated = all_pages[offset: offset + limit]
    return {"results": paginated, "total": len(all_pages)}


@router.post("/check-duplicates")
async def check_duplicates(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
) -> dict[str, Any]:
    """
    Fan-out check-duplicates to all (or filtered) vault instances.

    Merges all matches from all vaults and tags each with source_vault.
    If any vault recommends "merge", that recommendation is surfaced.
    """
    body = await request.json()
    vault_filter = _parse_vault_filter(body)

    results = await fan_out(vault_client, settings.vault_endpoints, "/check-duplicates", body, vault_filter)

    all_matches: list[dict[str, Any]] = []
    recommendation = "create"

    for vault_name, data in results.items():
        if "error" in data:
            continue
        for match in data.get("matches", []):
            all_matches.append({**match, "source_vault": vault_name})
        if data.get("recommendation") == "merge":
            recommendation = "merge"

    all_matches.sort(key=lambda m: m.get("similarity", 0.0), reverse=True)

    return {"matches": all_matches, "recommendation": recommendation}


@router.post("/suggest-metadata")
async def suggest_metadata(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
) -> dict[str, Any]:
    """
    Fan-out suggest-metadata to all (or filtered) vault instances.

    Merges suggestions — higher confidence wins for the same field.
    Each winning suggestion is tagged with source_vault.
    """
    body = await request.json()
    vault_filter = _parse_vault_filter(body)

    results = await fan_out(vault_client, settings.vault_endpoints, "/suggest-metadata", body, vault_filter)

    merged: dict[str, Any] = {}

    for vault_name, data in results.items():
        if "error" in data:
            continue
        for field_name, suggestion in data.items():
            if not isinstance(suggestion, dict):
                continue
            current_confidence = merged.get(field_name, {}).get("confidence", -1.0)
            new_confidence = suggestion.get("confidence", 0.0)
            if new_confidence > current_confidence:
                merged[field_name] = {**suggestion, "source_vault": vault_name}

    return merged


# ── Routed read endpoints (B4) ────────────────────────────────────────────────

@router.post("/get-page")
async def get_page(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
    uuid_registry: UUIDRegistryDepends,
) -> dict[str, Any]:
    """
    Route GET /get-page to the vault that owns the requested page UUID.

    If vault= is specified explicitly, route there. Otherwise look up the UUID
    in the registry. Falls back to default vault if UUID is not found.
    """
    body = await request.json()
    vault_name = _resolve_vault_for_write(body, uuid_registry, settings)
    base_url = settings.vault_endpoints.get(vault_name)
    if not base_url:
        raise HTTPException(status_code=404, detail=f"Vault '{vault_name}' not configured")

    url = f"{base_url.rstrip('/')}/get-page"
    try:
        response = await vault_client.post(url, json=body)
        response.raise_for_status()
        data = response.json()
        data["source_vault"] = vault_name
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream vault '{vault_name}' error: {e}")


@router.post("/get-related")
async def get_related(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
    uuid_registry: UUIDRegistryDepends,
) -> dict[str, Any]:
    """
    Route /get-related to the vault that owns the source page UUID.

    Cross-vault references are not supported in v1 — related pages resolve
    within the same vault only.
    """
    body = await request.json()
    vault_name = _resolve_vault_for_write(body, uuid_registry, settings)
    base_url = settings.vault_endpoints.get(vault_name)
    if not base_url:
        raise HTTPException(status_code=404, detail=f"Vault '{vault_name}' not configured")

    url = f"{base_url.rstrip('/')}/get-related"
    try:
        response = await vault_client.post(url, json=body)
        response.raise_for_status()
        data = response.json()
        data["source_vault"] = vault_name
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream vault '{vault_name}' error: {e}")


@router.post("/schema")
async def schema(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
) -> dict[str, Any]:
    """
    Route /schema to the default vault (schema is assumed uniform across vaults).

    If vault= is specified in the body, route to that vault instead.
    """
    body = await request.json()
    vault_name = body.get("vault") or settings.vault_default
    base_url = settings.vault_endpoints.get(vault_name)
    if not base_url:
        raise HTTPException(status_code=404, detail=f"Vault '{vault_name}' not configured")

    url = f"{base_url.rstrip('/')}/schema"
    try:
        response = await vault_client.post(url, json=body)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream vault '{vault_name}' error: {e}")


# ── Routed write endpoints (B4) ───────────────────────────────────────────────

@router.post("/write-page")
async def write_page(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
    uuid_registry: UUIDRegistryDepends,
) -> dict[str, Any]:
    """
    Route /write-page to the vault that owns the page (by UUID) or to default.

    After a successful write, the UUID registry will pick up the new page
    on its next refresh cycle (or immediately on a create, via the default vault).
    """
    body = await request.json()
    vault_name = _resolve_vault_for_write(body, uuid_registry, settings)
    base_url = settings.vault_endpoints.get(vault_name)
    if not base_url:
        raise HTTPException(status_code=404, detail=f"Vault '{vault_name}' not configured")

    url = f"{base_url.rstrip('/')}/write-page"
    try:
        response = await vault_client.post(url, json=body)
        response.raise_for_status()
        data = response.json()
        data["source_vault"] = vault_name
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream vault '{vault_name}' error: {e}")


@router.post("/validate-page")
async def validate_page(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
    uuid_registry: UUIDRegistryDepends,
) -> dict[str, Any]:
    """
    Route /validate-page to the owning vault (by UUID) or to default.
    """
    body = await request.json()
    vault_name = _resolve_vault_for_write(body, uuid_registry, settings)
    base_url = settings.vault_endpoints.get(vault_name)
    if not base_url:
        raise HTTPException(status_code=404, detail=f"Vault '{vault_name}' not configured")

    url = f"{base_url.rstrip('/')}/validate-page"
    try:
        response = await vault_client.post(url, json=body)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream vault '{vault_name}' error: {e}")


@router.post("/registry/add")
async def registry_add(
    request: Request,
    settings: SettingsDepends,
    vault_client: ClientDepends,
    uuid_registry: UUIDRegistryDepends,
) -> dict[str, Any]:
    """
    Route /registry/add to the vault that owns the page (by UUID) or to default.

    Used by vault-mcp after a successful write to register the page in the
    vault's internal registry.
    """
    body = await request.json()
    vault_name = _resolve_vault_for_write(body, uuid_registry, settings)
    base_url = settings.vault_endpoints.get(vault_name)
    if not base_url:
        raise HTTPException(status_code=404, detail=f"Vault '{vault_name}' not configured")

    url = f"{base_url.rstrip('/')}/registry/add"
    try:
        response = await vault_client.post(url, json=body)
        response.raise_for_status()
        data = response.json()
        data["source_vault"] = vault_name
        return data
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream vault '{vault_name}' error: {e}")
