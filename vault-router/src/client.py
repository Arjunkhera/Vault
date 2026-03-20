"""
VaultClient — async HTTP client pool for upstream vault instances.

Each vault instance gets its own base URL. All requests are forwarded
with the original request body and headers stripped to essentials.
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Default timeout for upstream vault requests (seconds).
# Vault's own QMD fallback uses 8s; give the router a bit more headroom.
UPSTREAM_TIMEOUT = 12.0


class VaultClient:
    """
    Manages a shared httpx.AsyncClient for fan-out requests to N vault instances.

    One client shared across all vaults — httpx handles connection pooling per host.
    """

    def __init__(self, timeout: float = UPSTREAM_TIMEOUT) -> None:
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout

    async def start(self) -> None:
        """Initialize the async HTTP client. Call during app lifespan startup."""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        logger.info("VaultClient HTTP pool started (timeout=%.1fs)", self._timeout)

    async def stop(self) -> None:
        """Close the async HTTP client. Call during app lifespan shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("VaultClient HTTP pool closed")

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("VaultClient not started — call start() first")
        return self._client

    async def post(self, url: str, json: Any) -> httpx.Response:
        """POST JSON to an upstream vault endpoint."""
        return await self.client.post(url, json=json)

    async def get(self, url: str) -> httpx.Response:
        """GET from an upstream vault endpoint."""
        return await self.client.get(url)

    async def health_check(self, name: str, base_url: str) -> dict[str, Any]:
        """
        Check health of a single vault instance.

        Returns a dict with status ("healthy", "unhealthy", "unreachable") and latency.
        """
        import time

        url = f"{base_url.rstrip('/')}/health"
        start = time.monotonic()
        try:
            response = await self.client.get(url, timeout=3.0)
            latency_ms = int((time.monotonic() - start) * 1000)
            if response.status_code == 200:
                return {"status": "healthy", "latency_ms": latency_ms}
            else:
                return {
                    "status": "unhealthy",
                    "latency_ms": latency_ms,
                    "http_status": response.status_code,
                }
        except httpx.TimeoutException:
            return {"status": "unreachable", "error": "timeout"}
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}
