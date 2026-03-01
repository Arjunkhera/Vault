"""Tests for the type registry."""

import os
import pytest

from src.config.type_registry import TypeRegistry, TypeDefinition, FieldDefinition


@pytest.fixture
def types_dir():
    """Path to the real types/ directory."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "types"
    )


class TestTypeRegistry:
    def test_load_from_directory(self, types_dir):
        registry = TypeRegistry()
        registry.load_from_directory(types_dir)
        assert len(registry.type_ids()) >= 6

    def test_expected_types_loaded(self, type_registry):
        expected = ["repo-profile", "guide", "concept", "procedure", "keystone", "learning"]
        for type_id in expected:
            assert type_registry.has_type(type_id), f"Missing type: {type_id}"

    def test_get_type_returns_definition(self, type_registry):
        td = type_registry.get_type("repo-profile")
        assert td is not None
        assert isinstance(td, TypeDefinition)
        assert td.id == "repo-profile"
        assert td.name is not None

    def test_get_type_unknown_returns_none(self, type_registry):
        assert type_registry.get_type("nonexistent") is None

    def test_has_type(self, type_registry):
        assert type_registry.has_type("guide") is True
        assert type_registry.has_type("fake-type") is False

    def test_list_types_returns_all(self, type_registry):
        types = type_registry.list_types()
        assert len(types) >= 6
        assert all(isinstance(t, TypeDefinition) for t in types)

    def test_repo_profile_requires_repo_scope(self, type_registry):
        td = type_registry.get_type("repo-profile")
        assert "repo" in td.required_scope

    def test_concept_has_no_required_scope(self, type_registry):
        td = type_registry.get_type("concept")
        assert td.required_scope == []

    def test_base_fields_merged(self, type_registry):
        """All types should have base fields like title, description, type."""
        for td in type_registry.list_types():
            assert "title" in td.fields, f"{td.id} missing 'title' field"
            assert "description" in td.fields, f"{td.id} missing 'description' field"

    def test_field_definition_structure(self, type_registry):
        td = type_registry.get_type("repo-profile")
        title_field = td.fields.get("title")
        assert title_field is not None
        assert isinstance(title_field, FieldDefinition)
        assert title_field.required is True

    def test_mode_field_has_valid_values(self, type_registry):
        td = type_registry.get_type("repo-profile")
        mode_field = td.fields.get("mode")
        assert mode_field is not None
        assert mode_field.values is not None
        assert "reference" in mode_field.values
        assert "operational" in mode_field.values
        assert "keystone" in mode_field.values

    def test_load_nonexistent_directory_logs_warning(self):
        """Loading from nonexistent dir should not crash but loads no types."""
        registry = TypeRegistry()
        registry.load_from_directory("/nonexistent/path")
        assert len(registry.type_ids()) == 0
