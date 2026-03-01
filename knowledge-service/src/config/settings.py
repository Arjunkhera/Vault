"""
VaultSettings — loads configuration from config file, env vars, and CLI args.

Precedence (highest to lowest):
  CLI args > environment variables > config file > defaults
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging
import os

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".vault" / "config.yaml"


@dataclass
class VaultSettings:
    """Configuration settings for Vault Knowledge Service."""

    knowledge_repo_path: str = "/data/knowledge-repo"
    workspace_path: str = "/workspace"
    qmd_index_name: str = "knowledge"
    sync_interval: int = 300
    port: int = 8000
    host: str = "0.0.0.0"
    log_level: str = "info"

    def log_sources(self, sources: dict[str, str]) -> None:
        """Log which source each value came from."""
        for field_name in [
            "knowledge_repo_path",
            "workspace_path",
            "qmd_index_name",
            "sync_interval",
            "port",
            "host",
            "log_level",
        ]:
            value = getattr(self, field_name)
            source = sources.get(field_name, "unknown")
            logger.info("  %s: %s (from %s)", field_name, value, source)


def load_settings(
    config_path: Optional[Path] = None,
    cli_overrides: Optional[dict] = None,
) -> tuple[VaultSettings, dict[str, str]]:
    """
    Load settings with full precedence chain.

    Args:
        config_path: Override path to config file (for testing)
        cli_overrides: Dict of CLI overrides (field_name -> value)

    Returns:
        Tuple of (settings, sources) where sources maps field names to their source.
    """
    settings = VaultSettings()
    sources: dict[str, str] = {
        "knowledge_repo_path": "default",
        "workspace_path": "default",
        "qmd_index_name": "default",
        "sync_interval": "default",
        "port": "default",
        "host": "default",
        "log_level": "default",
    }

    # Layer 1: Config file
    effective_config_path = config_path or Path(
        os.getenv("VAULT_CONFIG_PATH", str(DEFAULT_CONFIG_PATH))
    )

    if effective_config_path.exists():
        if yaml is None:
            logger.warning(
                "YAML library not available — skipping config file at %s",
                effective_config_path,
            )
        else:
            try:
                with open(effective_config_path) as f:
                    file_config = yaml.safe_load(f) or {}

                field_map = {
                    "knowledge_repo_path": str,
                    "workspace_path": str,
                    "qmd_index_name": str,
                    "sync_interval": int,
                    "port": int,
                    "host": str,
                    "log_level": str,
                }
                for field_name, type_fn in field_map.items():
                    if field_name in file_config:
                        try:
                            setattr(
                                settings,
                                field_name,
                                type_fn(file_config[field_name]),
                            )
                            sources[field_name] = f"config:{effective_config_path}"
                        except (ValueError, TypeError) as e:
                            logger.warning(
                                "Invalid value for %s in config: %r: %s",
                                field_name,
                                file_config[field_name],
                                e,
                            )

                logger.info("Loaded config from %s", effective_config_path)
            except Exception as e:
                logger.warning(
                    "Failed to load config from %s: %s — using env vars and defaults",
                    effective_config_path,
                    e,
                )
    else:
        logger.debug(
            "No config file at %s — using env vars and defaults", effective_config_path
        )

    # Layer 2: Environment variables
    env_map = {
        "KNOWLEDGE_REPO_PATH": ("knowledge_repo_path", str),
        "WORKSPACE_PATH": ("workspace_path", str),
        "QMD_INDEX_NAME": ("qmd_index_name", str),
        "SYNC_INTERVAL": ("sync_interval", int),
        "VAULT_PORT": ("port", int),
        "VAULT_HOST": ("host", str),
        "VAULT_LOG_LEVEL": ("log_level", str),
    }
    for env_key, (field_name, type_fn) in env_map.items():
        val = os.getenv(env_key)
        if val is not None:
            try:
                setattr(settings, field_name, type_fn(val))
                sources[field_name] = f"env:{env_key}"
            except (ValueError, TypeError) as e:
                logger.warning("Invalid value for %s=%r: %s", env_key, val, e)

    # Layer 3: CLI overrides (highest priority)
    if cli_overrides:
        for field_name, value in cli_overrides.items():
            if value is not None and hasattr(settings, field_name):
                setattr(settings, field_name, value)
                sources[field_name] = "cli"

    return settings, sources
