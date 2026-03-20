"""
Document indexing for Typesense.

Maps Vault knowledge pages to the unified horus_documents schema and provides:
- Single page indexing (upsert/delete hooks for write-path)
- Full re-index on startup (batch reads all pages from all vaults)

The unified document schema is shared across Horus services (Vault, Anvil)
so that cross-service search works transparently.
"""

import logging
import time
from pathlib import Path
from typing import Any, Optional

from .typesense_client import TypesenseSearchClient
from ..layer2.frontmatter import parse_page, ParsedPage

logger = logging.getLogger(__name__)


def page_to_document(
    page: ParsedPage,
    file_path: str,
    vault_name: str = "shared",
) -> dict[str, Any]:
    """
    Map a Vault KnowledgePage (ParsedPage) to the unified document schema.

    Args:
        page: Parsed knowledge page with frontmatter and body
        file_path: The file path used as the page identifier
        vault_name: Name of the vault (e.g. "shared", "workspace")

    Returns:
        Document dict ready for Typesense upsert
    """
    # Use the file_path as the document ID — this is the unique identifier
    # already used throughout the codebase (e.g. "shared/repos/anvil.md")
    doc_id = file_path

    body = (page.body or "")[:20_000]  # 20K truncation

    return {
        "id": doc_id,
        "source": "vault",
        "source_type": page.type,
        "title": page.title or "Untitled",
        "body": body,
        "tags": page.tags or [],
        "mode": page.mode or "reference",
        "scope_repo": page.scope.get("repo") if page.scope else None,
        "scope_program": page.scope.get("program") if page.scope else None,
        "vault_name": vault_name,
        "created_at": 0,  # Vault pages don't track created_at in frontmatter
        "modified_at": 0,  # Vault pages don't track modified_at in frontmatter
    }


def index_page(
    client: TypesenseSearchClient,
    content: str,
    file_path: str,
    vault_name: str = "shared",
) -> None:
    """
    Index (upsert) a single page into Typesense.

    Called as a hook after page write/update operations.

    Args:
        client: TypesenseSearchClient instance
        content: Raw markdown content with frontmatter
        file_path: Page identifier / file path
        vault_name: Vault name for the page
    """
    try:
        parsed = parse_page(content)
        doc = page_to_document(parsed, file_path, vault_name)
        client.upsert_document(doc)
        logger.debug("Indexed page '%s' to Typesense", file_path)
    except Exception as e:
        logger.warning("Failed to index page '%s': %s", file_path, e)


def delete_page_index(
    client: TypesenseSearchClient,
    file_path: str,
) -> None:
    """
    Delete a page from the Typesense index.

    Called as a hook after page delete operations.

    Args:
        client: TypesenseSearchClient instance
        file_path: Page identifier / file path to remove
    """
    try:
        client.delete_document(file_path)
        logger.debug("Deleted page '%s' from Typesense index", file_path)
    except Exception as e:
        logger.warning("Failed to delete page '%s' from index: %s", file_path, e)


def full_reindex(
    client: TypesenseSearchClient,
    collection_paths: dict[str, str],
) -> int:
    """
    Full re-index: read all pages from all vaults, batch upsert to Typesense.

    This is called at startup. It:
    1. Ensures the Typesense collection exists
    2. Reads all .md files from each collection path
    3. Parses frontmatter and maps to the unified document schema
    4. Batch upserts to Typesense
    5. Logs: "Indexed {count} Vault pages in {duration}ms"

    Args:
        client: TypesenseSearchClient instance
        collection_paths: Maps collection name -> filesystem root
            e.g. {"shared": "/data/knowledge-repo", "workspace": "/workspace"}

    Returns:
        Number of pages successfully indexed
    """
    start = time.time()

    # Ensure collection exists
    client.ensure_collection()

    documents: list[dict[str, Any]] = []

    for coll_name, root_path in collection_paths.items():
        root = Path(root_path)
        if not root.exists():
            logger.warning("Collection path does not exist: %s", root_path)
            continue

        for md_file in root.rglob("*.md"):
            # Skip _schema directory files and hidden files
            if md_file.name.startswith("_") or "/_schema/" in str(md_file):
                continue
            # Skip common non-knowledge files
            if md_file.name in ("README.md", "CHANGELOG.md", "LICENSE.md"):
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
                parsed = parse_page(content)
                relative = str(md_file.relative_to(root))
                file_path = f"{coll_name}/{relative}"
                doc = page_to_document(parsed, file_path, vault_name=coll_name)
                documents.append(doc)
            except Exception as e:
                logger.warning("Failed to parse page %s: %s", md_file, e)

    # Batch upsert
    indexed_count = 0
    if documents:
        indexed_count = client.upsert_documents_batch(documents)

    duration_ms = int((time.time() - start) * 1000)
    logger.info("Indexed %d Vault pages in %dms", indexed_count, duration_ms)

    return indexed_count
