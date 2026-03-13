"""
QMD adapter implementation of the SearchStore interface.

Supports two modes selected by the QMD_DAEMON_URL environment variable:

  HTTP daemon mode (QMD_DAEMON_URL set):
    Search calls (search, semantic_search, hybrid_search) are routed to the
    shared QMD daemon via its REST /query endpoint.  Models stay warm in memory
    across requests; no subprocess spawned per search.

  Subprocess mode (QMD_DAEMON_URL not set):
    Original behaviour — wraps the QMD CLI via subprocess for every call.
    All QMD commands use --index {index_name} to isolate the Knowledge Service
    index from the user's personal QMD index.

Collection management (ensure_collections, reindex) always uses subprocess so
that Vault writes to the shared SQLite database the daemon reads from. In daemon
mode the subprocess calls omit --index so they operate on the same default
database the daemon uses.
"""

import json
import logging
from typing import Any
import os
import subprocess
from pathlib import Path
from typing import Optional

import httpx

from .interface import SearchStore, SearchResult, Document
from ..errors import VaultError, ErrorCode


logger = logging.getLogger(__name__)


# ── REST client helper ────────────────────────────────────────────────────────

class _QMDRestClient:
    """Lightweight REST client for QMD daemon /query endpoint (v1.1.0+)."""

    # Match Anvil's 8-second timeout strategy: fail fast and let the
    # FallbackSearchStore degrade to FTS5 rather than hanging for 30s+
    # waiting for the reranker model to cold-start.
    TIMEOUT_SECONDS = 8.0

    def __init__(self, daemon_url: str) -> None:
        self._query_url = daemon_url.rstrip("/") + "/query"

    def search(self, query: str, search_type: str = "lex",
               collections: list[str] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        body: dict[str, Any] = {
            "searches": [{"type": search_type, "query": query}],
            "limit": limit,
        }
        if collections:
            body["collections"] = collections
        resp = httpx.post(self._query_url, json=body, timeout=self.TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def multi_search(self, searches: list[dict[str, str]],
                     collections: list[str] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Run multiple sub-searches (e.g. lex + vec for hybrid)."""
        body: dict[str, Any] = {
            "searches": searches,
            "limit": limit,
        }
        if collections:
            body["collections"] = collections
        resp = httpx.post(self._query_url, json=body, timeout=self.TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.json().get("results", [])


# ── QMDAdapter ────────────────────────────────────────────────────────────────

class QMDAdapter(SearchStore):
    """
    SearchStore implementation using QMD.

    Subprocess mode: qmd --index {index_name} <command> [args]
    HTTP daemon mode: POST {QMD_DAEMON_URL}/query via REST

    Config location: ~/.config/qmd/{index_name}.yml
    Database location: ~/.cache/qmd/{index_name}.sqlite
    """

    # Maps collection name → filesystem root (set during ensure_collections)
    _collection_paths: dict[str, str]

    def __init__(self, index_name: str = "knowledge") -> None:
        self.index_name = index_name
        self._collection_paths = {}

        daemon_url = os.environ.get("QMD_DAEMON_URL")
        self._rest: Optional[_QMDRestClient] = _QMDRestClient(daemon_url) if daemon_url else None

    # ── subprocess helpers ────────────────────────────────────────────────────

    def _run_qmd(self, args: list[str], check: bool = True) -> str:
        """
        Run a QMD CLI command and return stdout.

        In daemon mode the --index flag is omitted so subprocess calls operate
        on the same default database the daemon uses (shared via qmd-daemon-data
        volume). In subprocess-only mode --index {index_name} is included.
        """
        if self._rest:
            cmd = ["qmd"] + args
        else:
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

    # ── result parsing ────────────────────────────────────────────────────────

    def _parse_search_results(self, output: str, collection: Optional[str]) -> list[SearchResult]:
        """Parse QMD JSON subprocess output into SearchResult objects."""
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

    def _parse_rest_results(self, raw: list[dict[str, Any]], collection: Optional[str]) -> list[SearchResult]:
        """Parse QMD REST /query results into SearchResult objects."""
        results = []
        for item in raw:
            file_path = item.get("file", "")
            # file is displayPath format: "{collection}/{relative}" — extract collection
            coll = collection or ""
            if "/" in file_path and not coll:
                coll = file_path.split("/", 1)[0]
            results.append(SearchResult(
                file_path=file_path,
                score=item.get("score", 0.0),
                snippet=item.get("snippet", ""),
                collection=coll,
            ))
        return results

    # ── SearchStore interface ─────────────────────────────────────────────────

    def search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """Perform BM25 keyword search."""
        if self._rest:
            try:
                collections = [collection] if collection else ["shared", "workspace"]
                raw = self._rest.search(query, "lex", collections, limit)
                return self._parse_rest_results(raw, collection)
            except Exception as e:
                logger.warning("HTTP BM25 search failed for query '%s': %s", query, e)
                return []

        args_list = ["search", query, "--json", "-n", str(limit)]
        if collection:
            args_list.extend(["-c", collection])
        try:
            output = self._run_qmd(args_list)
            return self._parse_search_results(output, collection)
        except VaultError:
            logger.warning("BM25 search failed for query: %s", query)
            return []

    def semantic_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """Perform semantic vector search."""
        if self._rest:
            try:
                collections = [collection] if collection else ["shared", "workspace"]
                raw = self._rest.search(query, "vec", collections, limit)
                return self._parse_rest_results(raw, collection)
            except Exception as e:
                logger.warning("HTTP semantic search failed for query '%s': %s", query, e)
                return []

        args_list = ["vsearch", query, "--json", "-n", str(limit)]
        if collection:
            args_list.extend(["-c", collection])
        try:
            output = self._run_qmd(args_list)
            return self._parse_search_results(output, collection)
        except VaultError:
            logger.warning("Semantic search failed for query: %s", query)
            return []

    def hybrid_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """Perform hybrid search (BM25 + vector + reranking)."""
        if self._rest:
            try:
                collections = [collection] if collection else ["shared", "workspace"]
                raw = self._rest.multi_search(
                    [{"type": "lex", "query": query}, {"type": "vec", "query": query}],
                    collections, limit,
                )
                return self._parse_rest_results(raw, collection)
            except Exception as e:
                logger.warning("HTTP hybrid search failed for query '%s': %s", query, e)
                return []

        args_list = ["query", query, "--json", "-n", str(limit)]
        if collection:
            args_list.extend(["-c", collection])
        try:
            output = self._run_qmd(args_list)
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
        """
        Trigger re-index of Vault's collections (shared + workspace).

        Always uses subprocess. In daemon mode the subprocess operates on the
        shared SQLite database so the daemon picks up new documents automatically.
        Uses per-collection update to avoid touching the 'anvil' collection
        (Anvil is responsible for its own collection).

        The embed step runs in the background because it can take 10+ minutes
        on first boot (model download + embedding). Server startup should not
        be blocked by this — the QMD HTTP daemon handles searches independently.
        """
        for coll in ["shared", "workspace"]:
            try:
                self._run_qmd(["update", "-c", coll])
            except VaultError as e:
                logger.error("Re-index failed for collection '%s': %s", coll, e.message)
        # Run embed in background — it can take 10+ minutes on first boot
        # (GGUF model download + embedding generation). The QMD HTTP daemon
        # handles searches independently, so blocking startup is unnecessary.
        try:
            if self._rest:
                cmd = ["qmd", "embed"]
            else:
                cmd = ["qmd", "--index", self.index_name, "embed"]
            logger.info("Starting QMD embed in background (pid logged when started)...")
            proc = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
            )
            logger.info("QMD embed started in background (PID: %d)", proc.pid)
        except Exception as e:
            logger.warning("Failed to start background embed (non-fatal): %s", e)

    def status(self) -> dict[str, Any]:  # type: ignore[type-arg]
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
        In daemon mode the subprocess operates on the shared database (no --index flag).
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
