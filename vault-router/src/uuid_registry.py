"""
CrossVaultUUIDRegistry — maps page UUIDs to their source vault.

Built on startup by calling POST /list-by-scope on each configured vault instance.
Each PageSummary returned includes an `id` field (UUID) from Initiative A.

Rebuilt periodically (every REGISTRY_REFRESH_INTERVAL seconds) so the router
stays current as vaults index new pages.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

REGISTRY_REFRESH_INTERVAL = int(os.getenv("REGISTRY_REFRESH_INTERVAL", "300"))


@dataclass
class VaultPageCount:
    vault_name: str
    count: int
    last_refreshed_at: float  # unix timestamp


class CrossVaultUUIDRegistry:
    """
    Bidirectional UUID ↔ vault_name registry spanning all configured vaults.

    Thread-safe reads via lock-free swap (builds a new dict then atomically replaces).
    """

    def __init__(self) -> None:
        self._uuid_to_vault: dict[str, str] = {}   # UUID → vault name
        self._vault_counts: dict[str, VaultPageCount] = {}  # vault name → count + timestamp
        self._last_full_refresh: Optional[float] = None

    def resolve(self, page_uuid: str) -> Optional[str]:
        """Return vault name for a UUID, or None if not found."""
        return self._uuid_to_vault.get(page_uuid)

    def count(self) -> dict[str, int]:
        """Return per-vault page count."""
        return {name: vc.count for name, vc in self._vault_counts.items()}

    def status(self) -> dict:
        """Return registry status dict for the /registry-status endpoint."""
        return {
            "total_pages": len(self._uuid_to_vault),
            "last_full_refresh": self._last_full_refresh,
            "vaults": {
                name: {
                    "page_count": vc.count,
                    "last_refreshed_at": vc.last_refreshed_at,
                }
                for name, vc in self._vault_counts.items()
            },
        }

    async def build(self, vault_endpoints: dict[str, str], client) -> None:
        """
        Build/rebuild the registry by querying all vaults.

        Args:
            vault_endpoints: mapping of name → base URL
            client: VaultClient instance

        Fetches all pages from each vault via POST /list-by-scope with no filters.
        Handles failures per-vault (logs warning, keeps stale data for that vault).
        """
        tasks = [
            self._fetch_vault(name, url, client)
            for name, url in vault_endpoints.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge all results into a new dict (atomic swap)
        new_uuid_to_vault: dict[str, str] = {}
        new_vault_counts: dict[str, VaultPageCount] = {}

        for (name, url), result in zip(vault_endpoints.items(), results):
            if isinstance(result, Exception):
                logger.warning("Failed to fetch UUID registry from vault '%s': %s", name, result)
                # Keep stale data if we had it
                for uuid, vault_name in self._uuid_to_vault.items():
                    if vault_name == name:
                        new_uuid_to_vault[uuid] = name
                if name in self._vault_counts:
                    new_vault_counts[name] = self._vault_counts[name]
            else:
                uuids, count = result
                for uuid in uuids:
                    if uuid in new_uuid_to_vault:
                        logger.warning(
                            "Duplicate UUID '%s' found in vaults '%s' and '%s' — keeping first",
                            uuid, new_uuid_to_vault[uuid], name
                        )
                    else:
                        new_uuid_to_vault[uuid] = name
                new_vault_counts[name] = VaultPageCount(
                    vault_name=name,
                    count=count,
                    last_refreshed_at=time.time(),
                )
                logger.info("Registry: fetched %d pages from vault '%s'", count, name)

        # Atomic swap
        self._uuid_to_vault = new_uuid_to_vault
        self._vault_counts = new_vault_counts
        self._last_full_refresh = time.time()

        logger.info(
            "UUID registry rebuilt: %d total pages across %d vaults",
            len(self._uuid_to_vault),
            len(self._vault_counts),
        )

    async def _fetch_vault(
        self, name: str, base_url: str, client
    ) -> tuple[list[str], int]:
        """
        Fetch all page UUIDs from a single vault via POST /list-by-scope.

        Returns (list_of_uuids, total_count).
        Uses pagination to handle large vaults: fetches pages in batches of 100.
        """
        uuids: list[str] = []
        offset = 0
        limit = 100

        while True:
            url = f"{base_url.rstrip('/')}/list-by-scope"
            response = await client.post(url, json={"limit": limit, "offset": offset})
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            for page in results:
                page_id = page.get("id")
                if page_id:
                    uuids.append(str(page_id))

            total = data.get("total", len(results))
            offset += len(results)

            if offset >= total or not results:
                break

        return uuids, len(uuids)


async def start_registry_refresh_loop(
    registry: CrossVaultUUIDRegistry,
    vault_endpoints: dict[str, str],
    client,
    interval_seconds: int = REGISTRY_REFRESH_INTERVAL,
) -> asyncio.Task:
    """
    Start a background asyncio task that periodically rebuilds the UUID registry.

    Returns the task so the caller can cancel it on shutdown.
    """
    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                logger.debug("UUID registry refresh triggered (interval=%ds)", interval_seconds)
                await registry.build(vault_endpoints, client)
            except Exception as e:
                logger.warning("UUID registry refresh failed: %s", e)

    task = asyncio.create_task(_loop())
    logger.info("UUID registry refresh loop started (interval=%ds)", interval_seconds)
    return task
