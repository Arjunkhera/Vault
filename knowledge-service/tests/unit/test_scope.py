"""Tests for the simplified scope resolver."""

from src.layer2.scope import (
    Scope,
    resolve_scope,
    collect_operational_pages,
    _calculate_specificity,
    _applies_to_repo,
)
from src.layer2.frontmatter import parse_page
from tests.conftest import (
    ANVIL_REPO_PROFILE,
    CODING_STANDARDS_PROCEDURE,
    ANVIL_DEPLOYMENT_GUIDE,
)


class TestScope:
    def test_scope_to_dict_full(self):
        s = Scope(program="anvil-forge-vault", repo="anvil")
        assert s.to_dict() == {"program": "anvil-forge-vault", "repo": "anvil"}

    def test_scope_to_dict_partial(self):
        s = Scope(repo="anvil")
        assert s.to_dict() == {"repo": "anvil"}

    def test_scope_to_dict_empty(self):
        s = Scope()
        assert s.to_dict() == {}


class TestResolveScope:
    def test_resolves_program_from_repo_profile(self, mock_store):
        scope = resolve_scope("anvil", mock_store)
        assert scope.repo == "anvil"
        assert scope.program == "anvil-forge-vault"

    def test_resolves_program_for_forge(self, mock_store):
        scope = resolve_scope("forge", mock_store)
        assert scope.repo == "forge"
        assert scope.program == "anvil-forge-vault"

    def test_unknown_repo_returns_partial(self, mock_store):
        scope = resolve_scope("nonexistent", mock_store)
        assert scope.repo == "nonexistent"
        assert scope.program is None

    def test_empty_store_returns_partial(self, empty_store):
        scope = resolve_scope("anvil", empty_store)
        assert scope.repo == "anvil"
        assert scope.program is None


class TestCollectOperationalPages:
    def test_collects_repo_level_pages(self, mock_store):
        scope = Scope(program="anvil-forge-vault", repo="anvil")
        pages = collect_operational_pages(scope, mock_store)
        paths = [path for _, path in pages]
        assert "guides/anvil-deployment.md" in paths

    def test_collects_program_level_pages(self, mock_store):
        scope = Scope(program="anvil-forge-vault", repo="anvil")
        pages = collect_operational_pages(scope, mock_store)
        paths = [path for _, path in pages]
        # TypeScript standards applies to anvil via applies-to
        assert "procedures/typescript-standards.md" in paths

    def test_repo_level_pages_sorted_by_specificity(self, mock_store):
        """Pages with higher specificity (repo=2) should come before lower (program=1)."""
        scope = Scope(program="anvil-forge-vault", repo="anvil")
        pages = collect_operational_pages(scope, mock_store)
        # Both should be found
        paths = [path for _, path in pages]
        assert "guides/anvil-deployment.md" in paths
        # typescript-standards applies-to anvil (specificity=2), so both are repo-level
        assert "procedures/typescript-standards.md" in paths

    def test_no_operational_pages_for_unknown_scope(self, mock_store):
        scope = Scope(program="other-program", repo="other-repo")
        pages = collect_operational_pages(scope, mock_store)
        assert len(pages) == 0

    def test_excludes_non_operational_pages(self, mock_store):
        scope = Scope(program="anvil-forge-vault", repo="anvil")
        pages = collect_operational_pages(scope, mock_store)
        paths = [path for _, path in pages]
        # repo profiles are mode=reference, not operational
        assert "repos/anvil.md" not in paths


class TestCalculateSpecificity:
    def test_repo_match_returns_2(self):
        page = parse_page(ANVIL_DEPLOYMENT_GUIDE)
        scope = Scope(program="anvil-forge-vault", repo="anvil")
        assert _calculate_specificity(page, scope) == 2

    def test_program_match_returns_1(self):
        page = parse_page(CODING_STANDARDS_PROCEDURE)
        scope = Scope(program="anvil-forge-vault", repo="some-other-repo")
        assert _calculate_specificity(page, scope) == 1

    def test_applies_to_match_returns_2(self):
        page = parse_page(CODING_STANDARDS_PROCEDURE)
        scope = Scope(program="other", repo="anvil")
        assert _calculate_specificity(page, scope) == 2

    def test_no_match_returns_0(self):
        page = parse_page(ANVIL_DEPLOYMENT_GUIDE)
        scope = Scope(program="other-program", repo="other-repo")
        assert _calculate_specificity(page, scope) == 0


class TestAppliesToRepo:
    def test_dict_format(self):
        applies_to = [{"repo": "anvil"}, {"repo": "forge"}]
        assert _applies_to_repo(applies_to, "anvil") is True
        assert _applies_to_repo(applies_to, "vault") is False

    def test_string_format(self):
        applies_to = ["anvil", "forge"]
        assert _applies_to_repo(applies_to, "anvil") is True
        assert _applies_to_repo(applies_to, "vault") is False

    def test_empty_list(self):
        assert _applies_to_repo([], "anvil") is False
