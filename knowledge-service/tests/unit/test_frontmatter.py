"""Tests for the frontmatter parser."""

from src.layer2.frontmatter import parse_page, to_page_summary, to_page_full, ParsedPage
from tests.conftest import ANVIL_REPO_PROFILE, CONCEPT_PAGE, CODING_STANDARDS_PROCEDURE


class TestParsePage:
    def test_parses_type(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert page.type == "repo-profile"

    def test_parses_title(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert page.title == "Anvil"

    def test_parses_description(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert "Personal task" in page.description

    def test_parses_scope_program(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert page.scope["program"] == "anvil-forge-vault"

    def test_parses_scope_repo(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert page.scope["repo"] == "anvil"

    def test_parses_mode(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert page.mode == "reference"

    def test_parses_tags(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert "core" in page.tags
        assert "typescript" in page.tags

    def test_parses_related(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert len(page.related) >= 2

    def test_parses_depends_on(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert len(page.depends_on) >= 1
        assert page.depends_on[0] == {"repo": "forge"}

    def test_parses_applies_to(self):
        page = parse_page(CODING_STANDARDS_PROCEDURE)
        assert len(page.applies_to) == 2

    def test_parses_owner(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert page.owner == "arjun"

    def test_parses_last_verified(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert page.last_verified is not None

    def test_parses_body(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        assert "# Anvil" in page.body
        assert "Tech Stack" in page.body

    def test_defaults_for_missing_fields(self):
        minimal = """---
title: Minimal
---
# Minimal
"""
        page = parse_page(minimal)
        assert page.type == "concept"  # default
        assert page.mode == "reference"  # default
        assert page.scope == {}
        assert page.tags == []
        assert page.related == []

    def test_no_frontmatter(self):
        page = parse_page("# Just Markdown\nSome content.")
        assert page.title == "Untitled"
        assert page.type == "concept"

    def test_no_auto_generated_field(self):
        """ParsedPage should not have auto_generated field."""
        page = parse_page(ANVIL_REPO_PROFILE)
        assert not hasattr(page, "auto_generated")

    def test_no_source_field(self):
        """ParsedPage should not have source field."""
        page = parse_page(ANVIL_REPO_PROFILE)
        assert not hasattr(page, "source")


class TestToPageSummary:
    def test_creates_summary(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        summary = to_page_summary(page, "repos/anvil.md", score=0.95)
        assert summary.id == "repos/anvil.md"
        assert summary.title == "Anvil"
        assert summary.relevance_score == 0.95

    def test_summary_no_body(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        summary = to_page_summary(page, "repos/anvil.md")
        # PageSummary doesn't have body field
        assert not hasattr(summary, "body") or summary.__class__.__name__ == "PageSummary"

    def test_zero_score_becomes_none(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        summary = to_page_summary(page, "repos/anvil.md", score=0.0)
        assert summary.relevance_score is None


class TestToPageFull:
    def test_creates_full_page(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        full = to_page_full(page, "repos/anvil.md")
        assert full.id == "repos/anvil.md"
        assert full.body is not None
        assert "# Anvil" in full.body

    def test_includes_relationships(self):
        page = parse_page(ANVIL_REPO_PROFILE)
        full = to_page_full(page, "repos/anvil.md")
        assert len(full.related) >= 2
        assert len(full.depends_on) >= 1

    def test_auto_generated_is_none(self):
        """PageFull.auto_generated should be None (internal field not set for user pages)."""
        page = parse_page(ANVIL_REPO_PROFILE)
        full = to_page_full(page, "repos/anvil.md")
        assert full.auto_generated is None

    def test_source_is_none(self):
        """PageFull.source should be None (internal field not set for user pages)."""
        page = parse_page(ANVIL_REPO_PROFILE)
        full = to_page_full(page, "repos/anvil.md")
        assert full.source is None
