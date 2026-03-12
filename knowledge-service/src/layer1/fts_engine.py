"""
FTS5-based keyword search engine for Vault knowledge pages.

Provides a local fallback when the QMD daemon is unavailable.
Uses SQLite's FTS5 virtual table with BM25 ranking and Porter stemming.
"""

import logging
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .interface import SearchStore, SearchResult, Document

logger = logging.getLogger(__name__)


class FtsSearchEngine(SearchStore):

    def __init__(self, db_path: str, collection_paths: dict[str, str]) -> None:
        """
        Args:
            db_path: Path to SQLite database file (created if not exists)
            collection_paths: Maps collection name -> filesystem root
                e.g. {"shared": "/data/knowledge-repo", "workspace": "/data/workspace"}
        """
        self._db_path = db_path
        self._collection_paths = collection_paths
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        """Create a new connection safe for the current thread."""
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def _ensure_db(self) -> sqlite3.Connection:
        if self._conn:
            return self._conn
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
                file_path UNINDEXED,
                collection UNINDEXED,
                title,
                description,
                body,
                tags,
                tokenize='porter'
            )
        """)
        return self._conn

    def _sanitize_query(self, query: str) -> str:
        cleaned = re.sub(r'[()":^~{}#:]', '', query).strip()
        if not cleaned:
            return '*'
        words = cleaned.split()
        if len(words) == 1:
            return words[0]
        return ' OR '.join(words)

    def reindex(self) -> None:
        conn = self._ensure_db()
        conn.execute("DELETE FROM pages_fts")

        # Import here to avoid circular imports
        from ..layer2.frontmatter import parse_page

        count = 0
        for coll_name, root_path in self._collection_paths.items():
            root = Path(root_path)
            if not root.exists():
                continue
            for md_file in root.rglob("*.md"):
                if md_file.name.startswith("_"):
                    continue  # Skip _schema directory files
                try:
                    content = md_file.read_text(encoding="utf-8")
                    parsed = parse_page(content)
                    relative = str(md_file.relative_to(root))
                    file_path = f"{coll_name}/{relative}"
                    conn.execute(
                        "INSERT INTO pages_fts(file_path, collection, title, description, body, tags) VALUES (?, ?, ?, ?, ?, ?)",
                        (file_path, coll_name, parsed.title or "", parsed.description or "", parsed.body or content, ",".join(parsed.tags or []))
                    )
                    count += 1
                except Exception as e:
                    logger.warning("Failed to index %s: %s", md_file, e)

        conn.commit()
        logger.info("FTS5 index rebuilt: %d pages indexed", count)

    def search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        conn = self._ensure_db()
        sanitized = self._sanitize_query(query)

        if collection:
            rows = conn.execute(
                """SELECT file_path, collection,
                          bm25(pages_fts, 0, 0, 10.0, 5.0, 1.0, 2.0) as score,
                          snippet(pages_fts, 4, '<b>', '</b>', '...', 64) as snip
                   FROM pages_fts
                   WHERE pages_fts MATCH ? AND collection = ?
                   ORDER BY score
                   LIMIT ?""",
                (sanitized, collection, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT file_path, collection,
                          bm25(pages_fts, 0, 0, 10.0, 5.0, 1.0, 2.0) as score,
                          snippet(pages_fts, 4, '<b>', '</b>', '...', 64) as snip
                   FROM pages_fts
                   WHERE pages_fts MATCH ?
                   ORDER BY score
                   LIMIT ?""",
                (sanitized, limit)
            ).fetchall()

        results = []
        for file_path, coll, score, snippet in rows:
            raw = -(score or 0)  # BM25 returns negative; flip for positive
            normalized = raw / (1 + raw) if raw > 0 else 0.0
            results.append(SearchResult(
                file_path=file_path,
                score=normalized,
                snippet=snippet or "",
                collection=coll or "",
            ))

        # BM25 produces near-zero scores when a term appears in >50% of docs
        # (negative IDF). When this happens, fall back to rank-based scoring
        # so results are still meaningfully ordered.
        if results and max(r.score for r in results) < 0.01:
            for i, r in enumerate(results):
                r.score = max(0.5 - i * 0.03, 0.1)

        return results

    def semantic_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        # FTS5 has no vector support; degrade to keyword search
        return self.search(query, collection, limit)

    def hybrid_search(self, query: str, collection: Optional[str] = None, limit: int = 10) -> list[SearchResult]:
        # FTS5 has no semantic ranking; degrade to keyword search
        return self.search(query, collection, limit)

    def get_document(self, file_path: str) -> Optional[str]:
        parts = file_path.split("/", 1)
        if len(parts) != 2:
            return None
        collection, relative = parts
        root = self._collection_paths.get(collection)
        if not root:
            return None
        try:
            return (Path(root) / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def get_documents_by_glob(self, pattern: str) -> list[Document]:
        documents = []
        for coll_name, root_path in self._collection_paths.items():
            root = Path(root_path)
            if not root.exists():
                continue
            for match in root.glob(pattern):
                try:
                    relative = str(match.relative_to(root))
                    content = match.read_text(encoding="utf-8")
                    documents.append(Document(
                        file_path=f"{coll_name}/{relative}",
                        content=content,
                        collection=coll_name,
                    ))
                except (OSError, UnicodeDecodeError):
                    continue
        return documents

    def get_all_documents(self) -> dict[str, str]:
        docs = self.get_documents_by_glob("**/*.md")
        return {d.file_path: d.content for d in docs}

    def list_documents(self, collection: Optional[str] = None) -> list[str]:
        conn = self._ensure_db()
        if collection:
            rows = conn.execute(
                "SELECT file_path FROM pages_fts WHERE collection = ?", (collection,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT file_path FROM pages_fts").fetchall()
        return [r[0] for r in rows]

    def status(self) -> dict[str, Any]:
        conn = self._ensure_db()
        count = conn.execute("SELECT COUNT(*) FROM pages_fts").fetchone()[0]
        return {"status": "ok", "engine": "fts5", "indexed_documents": count}

    def ensure_collections(self, shared_path: str = "", workspace_path: str = "") -> None:
        """Update collection paths (called by main.py during startup)."""
        if shared_path:
            self._collection_paths["shared"] = shared_path
        if workspace_path:
            self._collection_paths["workspace"] = workspace_path
