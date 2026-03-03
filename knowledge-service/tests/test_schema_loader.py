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

SCHEMA_DIR = str(Path(__file__).parent.parent.parent.parent / "knowledge-base" / "_schema")


def _make_loader() -> SchemaLoader:
    loader = SchemaLoader(SCHEMA_DIR)
    loader.load()
    return loader


def test_schema_loader_loads_page_types():
    """Verify SchemaLoader loads all 6 page types from schema.yaml."""
    loader = _make_loader()
    assert len(loader.page_types) == 6, f"Expected 6 page types, got {len(loader.page_types)}"
    expected_types = {'repo-profile', 'guide', 'concept', 'procedure', 'keystone', 'learning'}
    assert set(loader.page_types.keys()) == expected_types


def test_schema_loader_loads_registries():
    """Verify SchemaLoader loads all 3 registries."""
    loader = _make_loader()
    assert 'tags' in loader.registries
    assert 'repos' in loader.registries
    assert 'programs' in loader.registries
    assert len(loader.registries['tags']) > 0
    assert len(loader.registries['repos']) > 0
    assert len(loader.registries['programs']) > 0


def test_schema_loader_converts_field_constraints():
    """Verify SchemaLoader converts field_constraints from list to dict format."""
    loader = _make_loader()
    assert isinstance(loader.field_constraints, dict)
    assert loader.field_constraints['title'].get('max_length') == 120
    assert loader.field_constraints['description'].get('max_length') == 300
    assert loader.field_constraints['tags'].get('min_items') == 1
    assert loader.field_constraints['scope'].get('min_fields') == 1


def test_schema_loader_loads_workflow_strategy_constraint():
    """Verify workflow.strategy allowed_values constraint is loaded."""
    loader = _make_loader()
    assert 'workflow.strategy' in loader.field_constraints
    allowed = loader.field_constraints['workflow.strategy'].get('allowed_values')
    assert set(allowed) == {'owner', 'fork', 'direct'}


def test_schema_loader_get_schema():
    """Verify get_schema() returns properly formatted schema dict."""
    loader = _make_loader()
    schema = loader.get_schema()
    assert 'version' in schema
    assert len(schema['page_types']) == 6
    assert isinstance(schema['field_constraints'], dict)
    assert 'tags' in schema['registries']


def test_page_validator_validates_valid_page():
    """Verify PageValidator accepts valid pages."""
    validator = PageValidator(_make_loader())
    result = validator.validate({
        'title': 'Vault Knowledge Service',
        'description': 'FastAPI service for knowledge management',
        'type': 'repo-profile',
        'mode': 'reference',
        'scope': {'repo': 'vault'},
        'tags': ['python', 'fastapi'],
    })
    assert result.valid, f"Expected valid page, got errors: {result.errors}"


def test_page_validator_accepts_valid_workflow_strategy():
    """All three valid workflow strategies should pass."""
    validator = PageValidator(_make_loader())
    for strategy in ('owner', 'fork', 'direct'):
        result = validator.validate({
            'title': 'Test',
            'description': 'Test repo',
            'type': 'repo-profile',
            'mode': 'reference',
            'scope': {'repo': 'vault'},
            'tags': ['python'],
            'workflow': {'strategy': strategy, 'default-branch': 'main'},
        })
        strategy_errors = [e for e in result.errors if e.field_name == 'workflow.strategy']
        assert not strategy_errors, f"Strategy '{strategy}' should be valid, got: {strategy_errors}"


def test_page_validator_rejects_invalid_workflow_strategy():
    """workflow.strategy with an invalid value should produce a validation error."""
    validator = PageValidator(_make_loader())
    result = validator.validate({
        'title': 'Test',
        'description': 'Test repo',
        'type': 'repo-profile',
        'mode': 'reference',
        'scope': {'repo': 'vault'},
        'tags': ['python'],
        'workflow': {'strategy': 'invalid-value'},
    })
    assert not result.valid
    strategy_errors = [e for e in result.errors if e.field_name == 'workflow.strategy']
    assert strategy_errors, f"Expected workflow.strategy error, got: {result.errors}"
    assert 'invalid-value' in strategy_errors[0].value
    assert set(strategy_errors[0].suggestions) == {'owner', 'fork', 'direct'}


def test_page_validator_allows_missing_workflow():
    """workflow field is optional — omitting it should not produce an error."""
    validator = PageValidator(_make_loader())
    result = validator.validate({
        'title': 'Test',
        'description': 'Test repo',
        'type': 'repo-profile',
        'mode': 'reference',
        'scope': {'repo': 'vault'},
        'tags': ['python'],
    })
    strategy_errors = [e for e in result.errors if e.field_name == 'workflow.strategy']
    assert not strategy_errors, "workflow.strategy should not be required"


def test_page_validator_rejects_long_title():
    """Verify PageValidator enforces field_constraints (title max_length)."""
    validator = PageValidator(_make_loader())
    result = validator.validate({
        'title': 'x' * 200,
        'description': 'Test',
        'type': 'repo-profile',
        'mode': 'reference',
        'scope': {'repo': 'vault'},
        'tags': ['python'],
    })
    assert not result.valid
    assert any(e.field_name == 'title' for e in result.errors)


def test_page_validator_requires_scope_fields():
    """Verify PageValidator enforces required_scope_fields."""
    validator = PageValidator(_make_loader())
    result = validator.validate({
        'title': 'Test',
        'description': 'Test',
        'type': 'repo-profile',
        'mode': 'reference',
        'scope': {},
        'tags': ['python'],
    })
    assert not result.valid
    assert any('scope.repo' in e.field_name for e in result.errors)


def test_page_validator_validates_registry_values():
    """Verify PageValidator validates tags against registries."""
    validator = PageValidator(_make_loader())
    # Valid tags
    result = validator.validate({
        'title': 'Test', 'description': 'Test',
        'type': 'guide', 'mode': 'reference', 'tags': ['python', 'testing'],
    })
    assert not any(e.field_name == 'tags' for e in result.errors)
    # Invalid tag
    result2 = validator.validate({
        'title': 'Test', 'description': 'Test',
        'type': 'guide', 'mode': 'reference', 'tags': ['invalid-tag-xyz'],
    })
    assert any(e.field_name == 'tags' for e in result2.errors)


if __name__ == '__main__':
    test_schema_loader_loads_page_types()
    test_schema_loader_loads_registries()
    test_schema_loader_converts_field_constraints()
    test_schema_loader_loads_workflow_strategy_constraint()
    test_schema_loader_get_schema()
    test_page_validator_validates_valid_page()
    test_page_validator_accepts_valid_workflow_strategy()
    test_page_validator_rejects_invalid_workflow_strategy()
    test_page_validator_allows_missing_workflow()
    test_page_validator_rejects_long_title()
    test_page_validator_requires_scope_fields()
    test_page_validator_validates_registry_values()
    print("All tests passed!")
