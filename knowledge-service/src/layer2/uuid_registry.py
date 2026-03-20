"""
UUID Registry for Vault Knowledge Service.

Maintains an in-memory bidirectional map of UUID ↔ file_path for all
knowledge pages. Built on startup and rebuilt after every reindex so that
routes can resolve a UUID to its backing file path without scanning disk.

Usage:
    registry = UUIDRegistry()
    registry.build("/data/knowledge-repo")

    file_path = registry.resolve("a480952d-b41e-46bd-b514-00cb55a846cc")
    # → "repos/anvil.md"

    page_id = registry.lookup("repos/anvil.md")
    # → "a480952d-b41e-46bd-b514-00cb55a846cc"
"""

import logging
import re
from pathlib import Path
from typing import Optional

import frontmatter

logger = logging.getLogger(__name__)

# Matches a bare UUID (without braces) — used to validate id field values
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class UUIDRegistry:
    """
    Bidirectional UUID ↔ file_path index for all knowledge pages.

    Built by scanning a knowledge-base directory for .md files and reading
    the `id` field from each page's YAML frontmatter. Rebuilt on every
    reindex to stay in sync with the backing store.
    """

    def __init__(self) -> None:
        self._uuid_to_path: dict[str, str] = {}   # UUID → relative file_path
        self._path_to_uuid: dict[str, str] = {}   # relative file_path → UUID

    # -------------------------------------------------------------------------
    # Build
    # -------------------------------------------------------------------------

    def build(self, knowledge_repo_path: str) -> None:
        """
        Scan all .md files under knowledge_repo_path and populate the registry.

        Files without an `id` field are logged as warnings and skipped.
        Duplicate UUIDs (two files with the same id) are logged as errors;
        the second occurrence wins.

        Args:
            knowledge_repo_path: Absolute path to the knowledge-base git repo.
        """
        root = Path(knowledge_repo_path)
        if not root.is_dir():
            logger.warning("UUID registry: knowledge repo path not found: %s", root)
            return

        new_uuid_to_path: dict[str, str] = {}
        new_path_to_uuid: dict[str, str] = {}

        pages = list(root.rglob("*.md"))
        indexed = 0
        skipped = 0

        for page_path in sorted(pages):
            # Use POSIX-style relative path as the canonical file_path key
            rel = page_path.relative_to(root).as_posix()

            try:
                content = page_path.read_text(encoding="utf-8")
                post = frontmatter.loads(content)
                page_id = post.metadata.get("id")
            except Exception as exc:
                logger.warning("UUID registry: failed to parse %s: %s", rel, exc)
                skipped += 1
                continue

            if not page_id:
                logger.warning("UUID registry: no `id` field in %s — skipping", rel)
                skipped += 1
                continue

            page_id = str(page_id).strip()
            if not _UUID_RE.match(page_id):
                logger.warning(
                    "UUID registry: `id` in %s is not a valid UUID ('%s') — skipping",
                    rel, page_id,
                )
                skipped += 1
                continue

            if page_id in new_uuid_to_path:
                logger.error(
                    "UUID registry: duplicate UUID '%s' in %s (already registered to %s)",
                    page_id, rel, new_uuid_to_path[page_id],
                )

            new_uuid_to_path[page_id] = rel
            new_path_to_uuid[rel] = page_id
            indexed += 1

        self._uuid_to_path = new_uuid_to_path
        self._path_to_uuid = new_path_to_uuid

        logger.info(
            "UUID registry built: %d pages indexed, %d skipped",
            indexed, skipped,
        )

    # -------------------------------------------------------------------------
    # Lookup
    # -------------------------------------------------------------------------

    def resolve(self, page_id: str) -> Optional[str]:
        """
        Resolve a UUID to its relative file path.

        Args:
            page_id: UUIDv4 string (case-insensitive)

        Returns:
            Relative file path (e.g. "repos/anvil.md"), or None if not found.
        """
        return self._uuid_to_path.get(page_id.lower() if page_id else "")

    def lookup(self, file_path: str) -> Optional[str]:
        """
        Look up the UUID for a given relative file path.

        Args:
            file_path: Relative path as stored in the registry (POSIX, e.g. "repos/anvil.md")

        Returns:
            UUID string, or None if not found.
        """
        return self._path_to_uuid.get(file_path)

    def count(self) -> int:
        """Return the number of pages currently in the registry."""
        return len(self._uuid_to_path)
