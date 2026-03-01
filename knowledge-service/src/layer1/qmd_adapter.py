"""
QMD adapter implementation of the SearchStore interface.

Wraps the QMD CLI tool via subprocess calls. QMD is a TypeScript/Bun tool
with no Python library, so subprocess integration is the only option.

All QMD commands use --index {index_name} to isolate the Knowledge Service
index from the user's personal QMD index.
"""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from .interface import SearchStore, SearchResult, Document
from ..errors import VaultError, ErrorCode


logger = logging.getLogger(__name__)


class QMDAdapter(SearchStore):
    """
    SearchStore implementation using QMD CLI via subprocess.

    QMD is invoked as: qmd --index {index_name} <command> [args]

    Config location: ~/.config/qmd/{index_name}.yml
    Database location: ~/.cache/qmd/{index_name}.sqlite
    """

    # Maps collection name → filesystem root (set during ensure_collections)
    _collection_paths: dict[str, str]

    def __init__(self, index_name: str = "knowledge"):
        self.index_name = index_name
        self._collection_paths = {}

    def _run_qmd(self, args: list[str], check: bool = True) -> str:
        """
        Run a QMD CLI command and return stdout.

        Raises:
            VaultError: If command fails and check=True
        """
        cmd = ["qmd", "--index", self.index_name] + args
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=check
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(
                "QMD command failed: %s (exit %d)\nstderr: %s",
                " ".join(cmd), e.returncode, e.stderr
            )
            raise VaultError(
                ErrorCode.SEARCH_ERROR,
                f"QMD command failed: {' '.join(args[:2])}",
                details={"command": " ".join(cmd), "stderr": e.stderr}
            ) from e

    def _parse_search_results(self, output: str, collection: Optional[str]) -> list[SearchResult]:
        """Parse QMD JSON search output into SearchResult objects."""
        try:
            results_data = json.loads(output)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse QMD search output as JSON: %s", e)
            return []

        results = []
        for item in results_data:
            results.append(SearchResult(
                file_path=item.get("file", ""),
                score=item.get("score", 0.0),
                snippet=item.get("snippet", ""),
                collection=item.get("collection", collection or "")
            ))
        return results

    def search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """Perform BM25 keyword search using 'qmd search'."""
        args = ["search", query, "--json", "-n", str(limit)]
        if collection:
            args.extend(["-c", collection])

        try:
            output = self._run_qmd(args)
            return self._parse_search_results(output, collection)
        except VaultError:
            logger.warning("BM25 search failed for query: %s", query)
            return []

    def semantic_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """Perform semantic vector search using 'qmd vsearch'."""
        args = ["vsearch", query, "--json", "-n", str(limit)]
        if collection:
            args.extend(["-c", collection])

        try:
            output = self._run_qmd(args)
            return self._parse_search_results(output, collection)
        except VaultError:
            logger.warning("Semantic search failed for query: %s", query)
            return []

    def hybrid_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """Perform hybrid search (BM25 + vector + reranking) using 'qmd query'."""
        args = ["query", query, "--json", "-n", str(limit)]
        if collection:
            args.extend(["-c", collection])

        try:
            output = self._run_qmd(args)
            return self._parse_search_results(output, collection)
        except VaultError:
            logger.warning("Hybrid search failed for query: %s", query)
            return []

    def get_document(self, file_path: str) -> Optional[str]:
        """Retrieve full document content using 'qmd get'."""
        try:
            output = self._run_qmd(["get", file_path])
            return output if output else None
        except VaultError:
            logger.debug("Document not found: %s", file_path)
            return None

    def get_documents_by_glob(self, pattern: str) -> list[Document]:
        """Retrieve multiple documents by glob pattern using 'qmd multi-get'."""
        try:
            output = self._run_qmd(["multi-get", pattern, "--json"])
            docs_data = json.loads(output)

            documents = []
            for item in docs_data:
                documents.append(Document(
                    file_path=item.get("file", ""),
                    content=item.get("content", ""),
                    collection=item.get("collection", "")
                ))
            return documents
        except (VaultError, json.JSONDecodeError) as e:
            logger.warning("Multi-get failed for pattern %s: %s", pattern, e)
            return []

    def list_documents(self, collection: Optional[str] = None) -> list[str]:
        """List all indexed documents using 'qmd ls'."""
        if collection:
            try:
                output = self._run_qmd(["ls", collection])
                files = []
                for line in output.strip().split('\n'):
                    line = line.strip()
                    if line and line.startswith('qmd://'):
                        parts = line.split()
                        if parts:
                            files.append(parts[-1])
                    elif 'qmd://' in line:
                        for part in line.split():
                            if part.startswith('qmd://'):
                                files.append(part)
                                break
                return files
            except VaultError:
                logger.warning("Failed to list documents in collection: %s", collection)
                return []
        else:
            all_files = []
            for coll in ["shared", "workspace"]:
                all_files.extend(self.list_documents(coll))
            return all_files

    def get_all_documents(self) -> dict[str, str]:
        """
        Read every indexed document from disk (no QMD subprocess needed).

        Maps qmd:// URIs to filesystem paths using the collection root
        directories recorded during ensure_collections().  Falls back to
        the base-class implementation (get_documents_by_glob) if the
        collection paths aren't available.
        """
        if not self._collection_paths:
            return super().get_all_documents()

        all_paths = self.list_documents()
        cache: dict[str, str] = {}

        for qmd_path in all_paths:
            # qmd_path looks like "qmd://shared/some-file.md"
            if not qmd_path.startswith("qmd://"):
                continue
            rest = qmd_path[len("qmd://"):]          # "shared/some-file.md"
            slash = rest.find("/")
            if slash == -1:
                continue
            collection = rest[:slash]                 # "shared"
            relative = rest[slash + 1:]               # "some-file.md"
            root = self._collection_paths.get(collection)
            if not root:
                continue
            disk_path = os.path.join(root, relative)
            try:
                cache[qmd_path] = Path(disk_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass

        return cache

    def reindex(self) -> None:
        """Trigger full re-index: update + embed."""
        try:
            self._run_qmd(["update"])
            self._run_qmd(["embed"])
        except VaultError as e:
            logger.error("Re-index failed: %s", e.message)
            raise

    def status(self) -> dict:
        """Get index status using 'qmd status'."""
        try:
            output = self._run_qmd(["status"])
            return {
                "status": "ok",
                "index_name": self.index_name,
                "raw_output": output
            }
        except VaultError:
            return {
                "status": "error",
                "index_name": self.index_name,
            }

    def ensure_collections(
        self,
        shared_path: str = "/data/knowledge-repo",
        workspace_path: str = "/workspace"
    ) -> None:
        """
        Ensure both collections are registered and indexed.

        Sets up dual-source indexing:
        - "shared" collection: knowledge repo (cloned inside container)
        - "workspace" collection: user's workspace (mounted from host)

        Idempotent — safe to call multiple times.
        """
        self._collection_paths = {
            "shared": shared_path,
            "workspace": workspace_path,
        }

        try:
            output = self._run_qmd(["collection", "list"])
            existing_collections = output.lower()
        except VaultError:
            existing_collections = ""

        if "shared" not in existing_collections:
            try:
                self._run_qmd([
                    "collection", "add", shared_path,
                    "--name", "shared",
                    "--mask", "**/*.md"
                ])
                logger.info("Added 'shared' collection: %s", shared_path)
            except VaultError as e:
                logger.error("Failed to add 'shared' collection: %s", e.message)

        if "workspace" not in existing_collections:
            try:
                self._run_qmd([
                    "collection", "add", workspace_path,
                    "--name", "workspace",
                    "--mask", "**/*.md"
                ])
                logger.info("Added 'workspace' collection: %s", workspace_path)
            except VaultError as e:
                logger.error("Failed to add 'workspace' collection: %s", e.message)

        logger.info("Running initial index...")
        self.reindex()
        logger.info("Collections setup complete")
