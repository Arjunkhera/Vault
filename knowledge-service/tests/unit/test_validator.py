"""Tests for the page validator."""

from src.layer2.frontmatter import parse_page
from src.layer2.validator import validate_page
from tests.conftest import (
    ANVIL_REPO_PROFILE,
    CONCEPT_PAGE,
    INVALID_PAGE,
    CODING_STANDARDS_PROCEDURE,
)


class TestValidatePage:
    def test_valid_repo_profile(self, type_registry):
        page = parse_page(ANVIL_REPO_PROFILE)
        result = validate_page(page, type_registry)
        assert result.valid is True
        assert result.errors == []

    def test_valid_concept_no_scope(self, type_registry):
        """Concept type doesn't require scope — should pass."""
        page = parse_page(CONCEPT_PAGE)
        result = validate_page(page, type_registry)
        assert result.valid is True

    def test_valid_procedure(self, type_registry):
        page = parse_page(CODING_STANDARDS_PROCEDURE)
        result = validate_page(page, type_registry)
        assert result.valid is True

    def test_missing_description_on_repo_profile(self, type_registry):
        """repo-profile requires description — missing should produce error."""
        page = parse_page(INVALID_PAGE)
        result = validate_page(page, type_registry)
        # Description is empty string (default), which should fail min_length or required check
        has_desc_error = any(e.field == "description" for e in result.errors)
        assert has_desc_error or not result.valid

    def test_unknown_type_returns_warning(self, type_registry):
        """Pages with unknown type should get a warning, not crash."""
        content = """---
type: unknown-type
title: Mystery Page
description: This type doesn't exist
mode: reference
---
# Mystery
"""
        page = parse_page(content)
        result = validate_page(page, type_registry)
        # Unknown type — should have warning or error about type
        assert len(result.warnings) > 0 or len(result.errors) > 0

    def test_invalid_mode_value(self, type_registry):
        """Invalid mode value should produce error."""
        content = """---
type: concept
title: Bad Mode
description: This has an invalid mode value
mode: nonexistent
---
# Bad
"""
        page = parse_page(content)
        result = validate_page(page, type_registry)
        has_mode_error = any(e.field == "mode" for e in result.errors)
        assert has_mode_error

    def test_repo_profile_missing_repo_scope(self, type_registry):
        """repo-profile requires scope.repo — missing should produce error."""
        content = """---
type: repo-profile
title: No Repo Scope
description: This repo-profile is missing scope.repo
scope:
  program: some-program
mode: reference
---
# Missing scope.repo
"""
        page = parse_page(content)
        result = validate_page(page, type_registry)
        assert result.valid is False
        has_scope_error = any("scope" in e.field for e in result.errors)
        assert has_scope_error
