"""
QMD adapter implementation of the SearchStore interface.

This module wraps the QMD CLI tool via subprocess calls. QMD is a TypeScript/Bun tool
with no Python library, so subprocess integration is the only option.

All QMD commands use --index {index_name} to isolate the Knowledge Service index
from the user's personal QMD index.
"""

import json
import subprocess
from typing import Optional

from .interface import SearchStore, SearchResult, Document


class QMDAdapter(SearchStore):
    """
    SearchStore implementation using QMD CLI via subprocess.
    
    QMD is invoked as: qmd --index {index_name} <command> [args]
    
    Config location: ~/.config/qmd/{index_name}.yml
    Database location: ~/.cache/qmd/{index_name}.sqlite
    """
    
    def __init__(self, index_name: str = "knowledge"):
        """
        Initialize the QMD adapter.
        
        Args:
            index_name: Name of the QMD index to use (default: "knowledge")
        """
        self.index_name = index_name
    
    def _run_qmd(self, args: list[str], check: bool = True) -> str:
        """
        Run a QMD CLI command and return stdout.
        
        Args:
            args: Command arguments (without 'qmd' and '--index')
            check: If True, raise exception on non-zero exit code
            
        Returns:
            Command stdout as string
            
        Raises:
            subprocess.CalledProcessError: If command fails and check=True
        """
        cmd = ["qmd", "--index", self.index_name] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check
        )
        return result.stdout
    
    def search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """
        Perform BM25 keyword search using 'qmd search'.
        
        Command: qmd --index {index} search "{query}" --json -n {limit} [-c {collection}]
        """
        args = ["search", query, "--json", "-n", str(limit)]
        if collection:
            args.extend(["-c", collection])
        
        try:
            output = self._run_qmd(args)
            results_data = json.loads(output)
            
            # Parse QMD JSON output into SearchResult objects
            results = []
            for item in results_data:
                results.append(SearchResult(
                    file_path=item.get("file", ""),
                    score=item.get("score", 0.0),
                    snippet=item.get("snippet", ""),
                    collection=item.get("collection", collection or "")
                ))
            return results
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            # Log error but return empty results rather than crashing
            print(f"QMD search error: {e}")
            return []
    
    def semantic_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """
        Perform semantic vector search using 'qmd vsearch'.
        
        Command: qmd --index {index} vsearch "{query}" --json -n {limit} [-c {collection}]
        """
        args = ["vsearch", query, "--json", "-n", str(limit)]
        if collection:
            args.extend(["-c", collection])
        
        try:
            output = self._run_qmd(args)
            results_data = json.loads(output)
            
            results = []
            for item in results_data:
                results.append(SearchResult(
                    file_path=item.get("file", ""),
                    score=item.get("score", 0.0),
                    snippet=item.get("snippet", ""),
                    collection=item.get("collection", collection or "")
                ))
            return results
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            print(f"QMD vsearch error: {e}")
            return []
    
    def hybrid_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """
        Perform hybrid search (BM25 + vector + reranking) using 'qmd query'.
        
        Command: qmd --index {index} query "{query}" --json -n {limit} [-c {collection}]
        """
        args = ["query", query, "--json", "-n", str(limit)]
        if collection:
            args.extend(["-c", collection])
        
        try:
            output = self._run_qmd(args)
            results_data = json.loads(output)
            
            results = []
            for item in results_data:
                results.append(SearchResult(
                    file_path=item.get("file", ""),
                    score=item.get("score", 0.0),
                    snippet=item.get("snippet", ""),
                    collection=item.get("collection", collection or "")
                ))
            return results
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            print(f"QMD query error: {e}")
            return []
    
    def get_document(self, file_path: str) -> Optional[str]:
        """
        Retrieve full document content using 'qmd get'.
        
        Command: qmd --index {index} get "{file_path}"
        """
        try:
            output = self._run_qmd(["get", file_path])
            return output if output else None
        except subprocess.CalledProcessError:
            return None
    
    def get_documents_by_glob(self, pattern: str) -> list[Document]:
        """
        Retrieve multiple documents by glob pattern using 'qmd multi-get'.
        
        Command: qmd --index {index} multi-get "{pattern}" --json
        """
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
        except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
            print(f"QMD multi-get error: {e}")
            return []
    
    def list_documents(self, collection: Optional[str] = None) -> list[str]:
        """
        List all indexed documents using 'qmd ls'.
        
        Command: qmd --index {index} ls [collection]
        
        If no collection is specified, lists documents from all collections.
        """
        if collection:
            # List specific collection
            args = ["ls", collection]
            try:
                output = self._run_qmd(args)
                # Parse output - each line has format: "size date qmd://collection/path"
                files = []
                for line in output.strip().split('\n'):
                    line = line.strip()
                    if line and line.startswith('qmd://'):
                        # Extract just the qmd:// path (last column)
                        parts = line.split()
                        if parts:
                            files.append(parts[-1])
                    elif 'qmd://' in line:
                        # Fallback: find qmd:// in the line
                        for part in line.split():
                            if part.startswith('qmd://'):
                                files.append(part)
                                break
                return files
            except subprocess.CalledProcessError as e:
                print(f"QMD ls error: {e}")
                return []
        else:
            # List all collections
            all_files = []
            for coll in ["shared", "workspace"]:
                all_files.extend(self.list_documents(coll))
            return all_files
    
    def reindex(self) -> None:
        """
        Trigger full re-index: update + embed.
        
        Commands:
            qmd --index {index} update
            qmd --index {index} embed
        """
        try:
            # Update: incremental re-index of all collections
            self._run_qmd(["update"])
            # Embed: rebuild vector embeddings for semantic search
            self._run_qmd(["embed"])
        except subprocess.CalledProcessError as e:
            print(f"QMD reindex error: {e}")
    
    def status(self) -> dict:
        """
        Get index status using 'qmd status'.
        
        Command: qmd --index {index} status
        """
        try:
            output = self._run_qmd(["status"])
            # QMD status returns human-readable text, not JSON
            # Parse it into a simple dict for now
            return {
                "status": "ok",
                "index_name": self.index_name,
                "raw_output": output
            }
        except subprocess.CalledProcessError as e:
            return {
                "status": "error",
                "index_name": self.index_name,
                "error": str(e)
            }
    
    def ensure_collections(
        self,
        shared_path: str = "/data/knowledge-repo",
        workspace_path: str = "/workspace"
    ) -> None:
        """
        Ensure both collections are registered and indexed.
        
        This is called once at startup to set up the dual-source indexing:
        - "shared" collection: knowledge repo (cloned inside container)
        - "workspace" collection: user's Anvil workspace (mounted from host)
        
        This method is idempotent - safe to call multiple times.
        
        Args:
            shared_path: Path to the shared knowledge repo
            workspace_path: Path to the mounted workspace
        """
        # Check existing collections
        try:
            output = self._run_qmd(["collection", "list"])
            existing_collections = output.lower()
        except subprocess.CalledProcessError:
            existing_collections = ""
        
        # Add "shared" collection if not exists
        if "shared" not in existing_collections:
            try:
                self._run_qmd([
                    "collection", "add", shared_path,
                    "--name", "shared",
                    "--mask", "**/*.md"
                ])
                print(f"Added 'shared' collection: {shared_path}")
            except subprocess.CalledProcessError as e:
                print(f"Error adding 'shared' collection: {e}")
        
        # Add "workspace" collection if not exists
        if "workspace" not in existing_collections:
            try:
                self._run_qmd([
                    "collection", "add", workspace_path,
                    "--name", "workspace",
                    "--mask", "**/*.md"
                ])
                print(f"Added 'workspace' collection: {workspace_path}")
            except subprocess.CalledProcessError as e:
                print(f"Error adding 'workspace' collection: {e}")
        
        # Run initial index and embed
        print("Running initial index...")
        self.reindex()
        print("Collections setup complete")
