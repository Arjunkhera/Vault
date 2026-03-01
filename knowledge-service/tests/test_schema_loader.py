"""
Story 002: Verify SchemaLoader Initialization

Tests that SchemaLoader correctly loads the schema and registries from
the knowledge-base _schema/ directory, and that PageValidator works
correctly with the loaded schema.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from layer2.schema import SchemaLoader, PageValidator


def test_schema_loader_loads_page_types():
    """Verify SchemaLoader loads all 6 page types from schema.yaml."""
    schema_dir = '/sessions/jolly-cool-gauss/mnt/Repositories/knowledge-base/_schema'
    loader = SchemaLoader(schema_dir)
    loader.load()

    assert len(loader.page_types) == 6, f"Expected 6 page types, got {len(loader.page_types)}"
    
    expected_types = {'repo-profile', 'guide', 'concept', 'procedure', 'keystone', 'learning'}
    actual_types = set(loader.page_types.keys())
    assert actual_types == expected_types, f"Expected {expected_types}, got {actual_types}"


def test_schema_loader_loads_registries():
    """Verify SchemaLoader loads all 3 registries."""
    schema_dir = '/sessions/jolly-cool-gauss/mnt/Repositories/knowledge-base/_schema'
    loader = SchemaLoader(schema_dir)
    loader.load()

    assert 'tags' in loader.registries, "Missing tags registry"
    assert 'repos' in loader.registries, "Missing repos registry"
    assert 'programs' in loader.registries, "Missing programs registry"
    
    # Check they have entries
    assert len(loader.registries['tags']) > 0, "Tags registry is empty"
    assert len(loader.registries['repos']) > 0, "Repos registry is empty"
    assert len(loader.registries['programs']) > 0, "Programs registry is empty"


def test_schema_loader_converts_field_constraints():
    """Verify SchemaLoader converts field_constraints from list to dict format."""
    schema_dir = '/sessions/jolly-cool-gauss/mnt/Repositories/knowledge-base/_schema'
    loader = SchemaLoader(schema_dir)
    loader.load()

    # field_constraints should be a dict with field names as keys
    assert isinstance(loader.field_constraints, dict), \
        f"Expected field_constraints to be dict, got {type(loader.field_constraints)}"
    
    # Check expected constraints are present
    assert 'title' in loader.field_constraints
    assert 'description' in loader.field_constraints
    assert 'tags' in loader.field_constraints
    assert 'scope' in loader.field_constraints
    
    # Check constraint structure
    assert loader.field_constraints['title'].get('max_length') == 120
    assert loader.field_constraints['description'].get('max_length') == 300
    assert loader.field_constraints['tags'].get('min_items') == 1
    assert loader.field_constraints['scope'].get('min_fields') == 1


def test_schema_loader_get_schema():
    """Verify get_schema() returns properly formatted schema dict."""
    schema_dir = '/sessions/jolly-cool-gauss/mnt/Repositories/knowledge-base/_schema'
    loader = SchemaLoader(schema_dir)
    loader.load()

    schema = loader.get_schema()
    
    assert 'version' in schema
    assert 'page_types' in schema
    assert 'field_constraints' in schema
    assert 'registries' in schema
    
    assert len(schema['page_types']) == 6
    assert isinstance(schema['field_constraints'], dict)
    assert 'tags' in schema['registries']


def test_page_validator_validates_valid_page():
    """Verify PageValidator accepts valid pages."""
    schema_dir = '/sessions/jolly-cool-gauss/mnt/Repositories/knowledge-base/_schema'
    loader = SchemaLoader(schema_dir)
    loader.load()
    validator = PageValidator(loader)

    valid_metadata = {
        'title': 'Vault Knowledge Service',
        'description': 'FastAPI service for knowledge management',
        'type': 'repo-profile',
        'mode': 'reference',
        'scope': {'repo': 'vault'},
        'tags': ['python', 'fastapi']
    }
    
    result = validator.validate(valid_metadata)
    assert result.valid, f"Expected valid page, got errors: {result.errors}"


def test_page_validator_rejects_long_title():
    """Verify PageValidator enforces field_constraints (title max_length)."""
    schema_dir = '/sessions/jolly-cool-gauss/mnt/Repositories/knowledge-base/_schema'
    loader = SchemaLoader(schema_dir)
    loader.load()
    validator = PageValidator(loader)

    # Title exceeds max_length of 120
    metadata = {
        'title': 'x' * 200,
        'description': 'Test',
        'type': 'repo-profile',
        'mode': 'reference',
        'scope': {'repo': 'vault'},
        'tags': ['python']
    }
    
    result = validator.validate(metadata)
    assert not result.valid, "Expected invalid page for long title"
    assert any(e.field == 'title' for e in result.errors), \
        f"Expected title constraint error in {[e.field for e in result.errors]}"


def test_page_validator_requires_scope_fields():
    """Verify PageValidator enforces required_scope_fields."""
    schema_dir = '/sessions/jolly-cool-gauss/mnt/Repositories/knowledge-base/_schema'
    loader = SchemaLoader(schema_dir)
    loader.load()
    validator = PageValidator(loader)

    # repo-profile requires scope.repo
    metadata = {
        'title': 'Test',
        'description': 'Test',
        'type': 'repo-profile',
        'mode': 'reference',
        'scope': {},  # Missing required 'repo'
        'tags': ['python']
    }
    
    result = validator.validate(metadata)
    assert not result.valid, "Expected invalid page for missing scope.repo"
    assert any('scope.repo' in e.field for e in result.errors), \
        f"Expected scope.repo error in {[e.field for e in result.errors]}"


def test_page_validator_validates_registry_values():
    """Verify PageValidator validates tags against registries."""
    schema_dir = '/sessions/jolly-cool-gauss/mnt/Repositories/knowledge-base/_schema'
    loader = SchemaLoader(schema_dir)
    loader.load()
    validator = PageValidator(loader)

    # Valid tags that exist in registry
    valid_metadata = {
        'title': 'Test',
        'description': 'Test',
        'type': 'guide',
        'mode': 'reference',
        'tags': ['python', 'testing']
    }
    
    result = validator.validate(valid_metadata)
    # Should not have tag errors (may have other warnings)
    tag_errors = [e for e in result.errors if e.field == 'tags']
    assert len(tag_errors) == 0, f"Unexpected tag errors: {tag_errors}"
    
    # Invalid tag that doesn't exist
    invalid_metadata = {
        'title': 'Test',
        'description': 'Test',
        'type': 'guide',
        'mode': 'reference',
        'tags': ['invalid-tag-xyz']
    }
    
    result2 = validator.validate(invalid_metadata)
    tag_errors = [e for e in result2.errors if e.field == 'tags']
    assert len(tag_errors) > 0, "Expected tag validation error for invalid tag"


if __name__ == '__main__':
    # Run all tests
    test_schema_loader_loads_page_types()
    test_schema_loader_loads_registries()
    test_schema_loader_converts_field_constraints()
    test_schema_loader_get_schema()
    test_page_validator_validates_valid_page()
    test_page_validator_rejects_long_title()
    test_page_validator_requires_scope_fields()
    test_page_validator_validates_registry_values()
    print("All tests passed!")
