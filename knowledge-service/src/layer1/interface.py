"""
Abstract SearchStore interface for the Knowledge Service.

This module defines the contract that any search/storage backend must implement.
Layer 2 (Knowledge Logic) depends only on this interface, not on specific implementations.

Current implementation: QMDAdapter (subprocess-based)
Future implementations: ElasticsearchAdapter, DocumentServiceAdapter
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SearchResult:
    """A single search result from the store."""
    file_path: str
    score: float
    snippet: str
    collection: str
    id: Optional[str] = field(default=None)  # UUIDv4 of the page; None if not yet resolved


@dataclass
class Document:
    """A full document retrieved from the store."""
    file_path: str
    content: str
    collection: str
    id: Optional[str] = field(default=None)  # UUIDv4 of the page; None if not yet resolved


class SearchStore(ABC):
    """
    Abstract base class for search/storage backends.
    
    All methods that query the store should return structured data (SearchResult, Document)
    rather than raw strings, to make Layer 2 logic independent of the storage implementation.
    """
    
    @abstractmethod
    def search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """
        Perform BM25 keyword search.
        
        Args:
            query: Search query string
            collection: Optional collection name to search within (e.g., "shared", "workspace")
            limit: Maximum number of results to return
            
        Returns:
            List of SearchResult objects, ranked by relevance score
        """
        pass
    
    @abstractmethod
    def semantic_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """
        Perform semantic vector search.
        
        Args:
            query: Natural language query
            collection: Optional collection name to search within
            limit: Maximum number of results to return
            
        Returns:
            List of SearchResult objects, ranked by semantic similarity
        """
        pass
    
    @abstractmethod
    def hybrid_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        """
        Perform hybrid search (BM25 + vector + reranking).
        
        This is the highest quality search mode, combining keyword and semantic search
        with LLM reranking. Use this for important queries where accuracy matters most.
        
        Args:
            query: Search query string
            collection: Optional collection name to search within
            limit: Maximum number of results to return
            
        Returns:
            List of SearchResult objects, ranked by combined relevance
        """
        pass
    
    @abstractmethod
    def get_document(self, file_path: str) -> Optional[str]:
        """
        Retrieve the full content of a document by its file path.
        
        Args:
            file_path: Path to the document (as returned in SearchResult.file_path)
            
        Returns:
            Raw document content as string, or None if not found
        """
        pass
    
    @abstractmethod
    def get_documents_by_glob(self, pattern: str) -> list[Document]:
        """
        Retrieve multiple documents matching a glob pattern.
        
        Args:
            pattern: Glob pattern (e.g., "services/**/*.md")
            
        Returns:
            List of Document objects matching the pattern
        """
        pass
    
    def get_all_documents(self) -> dict[str, str]:
        """
        Fetch every indexed document in a single call and return as a
        {file_path: content} lookup.  Default implementation calls
        get_documents_by_glob; backends may override with a cheaper path.
        """
        docs = self.get_documents_by_glob("**/*.md")
        return {d.file_path: d.content for d in docs}

    @abstractmethod
    def list_documents(self, collection: Optional[str] = None) -> list[str]:
        """
        List all indexed document paths.
        
        Args:
            collection: Optional collection name to filter by
            
        Returns:
            List of file paths (strings)
        """
        pass
    
    @abstractmethod
    def reindex(self) -> None:
        """
        Trigger a full re-index of all collections.
        
        This rebuilds the search index and vector embeddings.
        Called by the sync daemon when changes are detected.
        """
        pass
    
    @abstractmethod
    def status(self) -> dict:
        """
        Get the current status of the search index.
        
        Returns:
            Dictionary with index health information (implementation-specific)
        """
        pass
