"""Tests for mode filtering and progressive disclosure."""

from src.layer2.frontmatter import parse_page
from src.layer2.mode_filter import (
    filter_by_mode,
    filter_by_type,
    filter_by_scope,
    filter_by_tags,
    to_summaries,
)
from src.api.models import ScopeFilter
from tests.conftest import SAMPLE_PAGES


def _load_all_pages():
    """Parse all sample pages into (ParsedPage, path) tuples."""
    return [(parse_page(content), path) for path, content in SAMPLE_PAGES.items()]


class TestFilterByMode:
    def test_filter_reference(self):
        pages = _load_all_pages()
        filtered = filter_by_mode(pages, "reference")
        assert all(p.mode == "reference" for p, _ in filtered)
        assert len(filtered) > 0

    def test_filter_operational(self):
        pages = _load_all_pages()
        filtered = filter_by_mode(pages, "operational")
        assert all(p.mode == "operational" for p, _ in filtered)
        assert len(filtered) >= 2  # standards + deployment

    def test_filter_keystone(self):
        pages = _load_all_pages()
        filtered = filter_by_mode(pages, "keystone")
        assert all(p.mode == "keystone" for p, _ in filtered)

    def test_none_mode_returns_all(self):
        pages = _load_all_pages()
        filtered = filter_by_mode(pages, None)
        assert len(filtered) == len(pages)


class TestFilterByType:
    def test_filter_repo_profile(self):
        pages = _load_all_pages()
        filtered = filter_by_type(pages, "repo-profile")
        assert all(p.type == "repo-profile" for p, _ in filtered)
        assert len(filtered) >= 3  # anvil, forge, vault, broken

    def test_filter_guide(self):
        pages = _load_all_pages()
        filtered = filter_by_type(pages, "guide")
        assert len(filtered) >= 1

    def test_none_type_returns_all(self):
        pages = _load_all_pages()
        filtered = filter_by_type(pages, None)
        assert len(filtered) == len(pages)


class TestFilterByScope:
    def test_filter_by_program(self):
        pages = _load_all_pages()
        scope = ScopeFilter(program="anvil-forge-vault")
        filtered = filter_by_scope(pages, scope)
        assert len(filtered) > 0
        assert all(p.scope.get("program") == "anvil-forge-vault" for p, _ in filtered)

    def test_filter_by_repo(self):
        pages = _load_all_pages()
        scope = ScopeFilter(repo="anvil")
        filtered = filter_by_scope(pages, scope)
        assert len(filtered) >= 1
        assert all(p.scope.get("repo") == "anvil" for p, _ in filtered)

    def test_filter_by_program_and_repo(self):
        pages = _load_all_pages()
        scope = ScopeFilter(program="anvil-forge-vault", repo="anvil")
        filtered = filter_by_scope(pages, scope)
        assert len(filtered) >= 1
        for p, _ in filtered:
            assert p.scope.get("program") == "anvil-forge-vault"
            assert p.scope.get("repo") == "anvil"

    def test_none_scope_returns_all(self):
        pages = _load_all_pages()
        filtered = filter_by_scope(pages, None)
        assert len(filtered) == len(pages)


class TestFilterByTags:
    def test_filter_single_tag(self):
        pages = _load_all_pages()
        filtered = filter_by_tags(pages, ["core"])
        assert len(filtered) > 0
        assert all("core" in p.tags for p, _ in filtered)

    def test_filter_multiple_tags_and_logic(self):
        pages = _load_all_pages()
        filtered = filter_by_tags(pages, ["core", "typescript"])
        assert len(filtered) >= 1
        for p, _ in filtered:
            assert "core" in p.tags
            assert "typescript" in p.tags

    def test_none_tags_returns_all(self):
        pages = _load_all_pages()
        filtered = filter_by_tags(pages, None)
        assert len(filtered) == len(pages)

    def test_empty_tags_returns_all(self):
        pages = _load_all_pages()
        filtered = filter_by_tags(pages, [])
        assert len(filtered) == len(pages)


class TestToSummaries:
    def test_converts_to_summaries(self):
        pages = _load_all_pages()[:3]
        summaries = to_summaries(pages)
        assert len(summaries) == 3
        for s in summaries:
            assert s.id is not None
            assert s.title is not None

    def test_summaries_with_scores(self):
        pages = _load_all_pages()[:2]
        scores = {path: 0.8 for _, path in pages}
        summaries = to_summaries(pages, scores)
        assert all(s.relevance_score == 0.8 for s in summaries)
