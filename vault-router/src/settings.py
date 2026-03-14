"""
VaultRouterSettings — loads configuration from environment variables.

Environment variables:
  VAULT_ENDPOINTS  Comma-separated list of name=url pairs.
                   Format: "name1=http://host1:8000,name2=http://host2:8000"
                   Required — router cannot start without at least one vault.
  VAULT_DEFAULT    Name of the default vault for new-page writes.
                   Must match one of the names in VAULT_ENDPOINTS.
                   Required.
  VAULT_ROUTER_PORT  Port to bind to (default: 8400)
  VAULT_ROUTER_HOST  Host to bind to (default: 0.0.0.0)
  LOG_LEVEL          Logging level (default: info)
"""

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class VaultRouterSettings:
    """Configuration for the Vault Router service."""

    vault_endpoints: dict[str, str] = field(default_factory=dict)
    """Mapping of vault name → base URL (e.g. {"personal": "http://vault-personal:8000"})."""

    vault_default: str = ""
    """Name of the default vault for new-page writes."""

    port: int = 8400
    host: str = "0.0.0.0"
    log_level: str = "info"

    def validate(self) -> None:
        """Raise ValueError if required settings are missing or invalid."""
        if not self.vault_endpoints:
            raise ValueError(
                "VAULT_ENDPOINTS is required. "
                "Format: 'name1=http://host1:8000,name2=http://host2:8000'"
            )
        if not self.vault_default:
            raise ValueError(
                "VAULT_DEFAULT is required. "
                "Must be one of: " + ", ".join(self.vault_endpoints.keys())
            )
        if self.vault_default not in self.vault_endpoints:
            raise ValueError(
                f"VAULT_DEFAULT '{self.vault_default}' is not in VAULT_ENDPOINTS. "
                f"Available: {', '.join(self.vault_endpoints.keys())}"
            )


def load_settings() -> VaultRouterSettings:
    """
    Load settings from environment variables.

    Returns:
        Validated VaultRouterSettings instance.

    Raises:
        ValueError if required settings are missing or invalid.
    """
    # Parse VAULT_ENDPOINTS=name1=http://...,name2=http://...
    vault_endpoints: dict[str, str] = {}
    endpoints_raw = os.getenv("VAULT_ENDPOINTS", "").strip()
    if endpoints_raw:
        for part in endpoints_raw.split(","):
            part = part.strip()
            if "=" not in part:
                logger.warning("Skipping malformed VAULT_ENDPOINTS entry (no '='): %r", part)
                continue
            name, _, url = part.partition("=")
            name = name.strip()
            url = url.strip()
            if not name or not url:
                logger.warning("Skipping empty name or URL in VAULT_ENDPOINTS: %r", part)
                continue
            vault_endpoints[name] = url

    settings = VaultRouterSettings(
        vault_endpoints=vault_endpoints,
        vault_default=os.getenv("VAULT_DEFAULT", "").strip(),
        port=int(os.getenv("VAULT_ROUTER_PORT", "8400")),
        host=os.getenv("VAULT_ROUTER_HOST", "0.0.0.0"),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )

    settings.validate()

    logger.info("Vault Router settings loaded:")
    logger.info("  vaults: %s", list(settings.vault_endpoints.keys()))
    logger.info("  default: %s", settings.vault_default)
    logger.info("  port: %d", settings.port)

    return settings
