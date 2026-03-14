"""
Fan-out helpers — broadcast a request to all (or a subset of) vault instances
and merge the results.

Used by the read endpoints that need results from all vaults:
  - POST /search
  - POST /resolve-context
  - POST /list-by-scope
  - POST /check-duplicates
  - POST /suggest-metadata
"""

import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Per-vault timeout for fan-out requests (seconds).
# One slow vault should not block the response — partial results are returned.
FAN_OUT_TIMEOUT = 10.0


async def fan_out(
    client,  # VaultClient
    vault_endpoints: dict[str, str],
    path: str,
    body: dict[str, Any],
    vault_filter: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Send a POST request to all (or filtered) vault instances concurrently.

    Args:
        client: VaultClient instance
        vault_endpoints: mapping of name → base URL
        path: REST path (e.g. "/search")
        body: JSON request body
        vault_filter: if set, only fan out to these vault names

    Returns:
        dict mapping vault_name → response JSON (or error dict on failure)

    Each vault gets at most FAN_OUT_TIMEOUT seconds. Timed-out or errored
    vaults return {"error": "...", "status": "failed"} in the result dict.
    """
    targets = {
        name: url for name, url in vault_endpoints.items()
        if vault_filter is None or name in vault_filter
    }

    async def _call_one(name: str, base_url: str) -> tuple[str, Any]:
        url = f"{base_url.rstrip('/')}{path}"
        try:
            response = await asyncio.wait_for(
                client.post(url, json=body),
                timeout=FAN_OUT_TIMEOUT,
            )
            response.raise_for_status()
            return name, response.json()
        except asyncio.TimeoutError:
            logger.warning("Fan-out timeout for vault '%s' at %s", name, path)
            return name, {"error": "timeout", "status": "failed"}
        except Exception as e:
            logger.warning("Fan-out error for vault '%s' at %s: %s", name, path, e)
            return name, {"error": str(e), "status": "failed"}

    tasks = [_call_one(name, url) for name, url in targets.items()]
    pairs = await asyncio.gather(*tasks)
    return dict(pairs)
