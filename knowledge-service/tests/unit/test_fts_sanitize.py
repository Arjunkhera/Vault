"""
Tests for FtsSearchEngine._sanitize_query fixes.

Covers:
- Bug cbfbd31b: # causes FTS5 syntax error
- Bug 5ea2d6d8: colon in content (e.g. "Registry: add") causes "no such column: Registry"
"""

import sqlite3
import tempfile
import os
import pytest

from src.layer1.fts_engine import FtsSearchEngine


@pytest.fixture
def engine(tmp_path):
    db = str(tmp_path / "test_fts.db")
    e = FtsSearchEngine(db_path=db, collection_paths={"shared": str(tmp_path / "shared")})
    # Bootstrap schema
    e._ensure_db()
    return e


class TestSanitizeQuery:
    def test_hash_stripped(self, engine):
        result = engine._sanitize_query("#decision")
        assert "#" not in result
        assert "decision" in result

    def test_hash_tag_style(self, engine):
        result = engine._sanitize_query("#learning #gotcha")
        assert "#" not in result

    def test_colon_stripped(self, engine):
        result = engine._sanitize_query("Registry: add")
        assert ":" not in result

    def test_colon_prefix_stripped(self, engine):
        result = engine._sanitize_query("Registry:something")
        assert ":" not in result

    def test_existing_special_chars_still_stripped(self, engine):
        result = engine._sanitize_query('foo (bar) "baz"')
        assert "(" not in result
        assert ")" not in result
        assert '"' not in result

    def test_empty_after_stripping_returns_wildcard(self, engine):
        result = engine._sanitize_query("#")
        assert result == "*"

    def test_normal_query_unchanged(self, engine):
        result = engine._sanitize_query("vault knowledge service")
        assert result == "vault OR knowledge OR service"


class TestFtsSearchNoSyntaxError:
    """Integration: actual FTS5 queries must not raise sqlite3.OperationalError."""

    def test_hash_query_does_not_raise(self, engine):
        # Should return empty results, not raise
        results = engine.search("#decision")
        assert isinstance(results, list)

    def test_colon_query_does_not_raise(self, engine):
        # Body content like "Registry: add" passed as a query must not raise
        results = engine.search("Registry: add some entry")
        assert isinstance(results, list)

    def test_hash_and_colon_combined(self, engine):
        results = engine.search("#decision Registry: something")
        assert isinstance(results, list)

    def test_plain_keyword_returns_results(self, engine, tmp_path):
        """Sanity check: indexed content is searchable."""
        shared = tmp_path / "shared"
        shared.mkdir(exist_ok=True)
        (shared / "test.md").write_text("---\ntitle: Hello\n---\nThis is a vault document.")
        engine._collection_paths["shared"] = str(shared)
        engine.reindex()
        results = engine.search("vault")
        assert len(results) >= 1
