"""Tests for the link navigator."""

from src.layer2.frontmatter import parse_page
from src.layer2.link_navigator import (
    get_related_pages,
    _extract_reference_text,
    _is_match,
)
from tests.conftest import ANVIL_REPO_PROFILE, ARCHITECTURE_KEYSTONE


class TestExtractReferenceText:
    def test_wiki_link(self):
        assert _extract_reference_text("[[Anvil]]") == "Anvil"

    def test_wiki_link_with_alias(self):
        assert _extract_reference_text("[[Anvil|The Anvil System]]") == "Anvil"

    def test_plain_string(self):
        assert _extract_reference_text("anvil") == "anvil"

    def test_dict_repo(self):
        assert _extract_reference_text({"repo": "anvil"}) == "anvil"

    def test_dict_program(self):
        assert _extract_reference_text({"program": "anvil-forge-vault"}) == "anvil-forge-vault"

    def test_dict_unknown_key(self):
        assert _extract_reference_text({"foo": "bar"}) is None

    def test_none_for_unsupported_type(self):
        assert _extract_reference_text(42) is None


class TestIsMatch:
    def test_title_match(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert _is_match(page, "Anvil") is True

    def test_title_match_case_insensitive(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert _is_match(page, "anvil") is True

    def test_scope_value_match(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert _is_match(page, "anvil-forge-vault") is True

    def test_no_match(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert _is_match(page, "nonexistent") is False


class TestGetRelatedPages:
    def test_finds_related_pages(self, mock_store):
        page = parse_page(ANVIL_REPO_PROFILE)
        related = get_related_pages(page, mock_store)
        # Should find Forge and Vault via [[Forge]] and [[Vault]] wiki-links
        related_titles = [p.title for p, _ in related]
        assert "Forge" in related_titles or "Vault" in related_titles

    def test_finds_depends_on(self, mock_store):
        page = parse_page(ANVIL_REPO_PROFILE)
        related = get_related_pages(page, mock_store)
        related_paths = [path for _, path in related]
        # depends-on: {repo: forge} should find forge's repo profile
        assert "repos/forge.md" in related_paths

    def test_deduplicates(self, mock_store):
        page = parse_page(ARCHITECTURE_KEYSTONE)
        related = get_related_pages(page, mock_store)
        paths = [path for _, path in related]
        assert len(paths) == len(set(paths))

    def test_empty_refs_returns_empty(self, mock_store):
        from src.layer2.frontmatter import ParsedPage
        page = ParsedPage(title="Empty")
        related = get_related_pages(page, mock_store)
        assert len(related) == 0
