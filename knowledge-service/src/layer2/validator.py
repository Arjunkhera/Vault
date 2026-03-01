"""
Page validation for the Knowledge Service.

Validates knowledge pages against their type definitions.
Validation is non-blocking: pages with errors are still indexed,
but errors/warnings are reported in API responses.
"""

import logging
from typing import Optional

from ..errors import ErrorCode, ValidationResult
from ..config.type_registry import TypeDefinition, TypeRegistry
from .frontmatter import ParsedPage


logger = logging.getLogger(__name__)


def validate_page(
    page: ParsedPage,
    registry: TypeRegistry,
) -> ValidationResult:
    """
    Validate a parsed page against its type definition.

    Checks:
    1. Type is registered
    2. Required fields are present and non-empty
    3. Required scope fields are present (e.g., repo-profile needs scope.repo)
    4. Enum fields have valid values
    5. String constraints (min_length, max_length)

    Returns ValidationResult with errors and warnings.
    Pages with errors are still indexable — validation is advisory.
    """
    result = ValidationResult.ok()

    # Step 1: Check type is registered
    type_def = registry.get_type(page.type)
    if type_def is None:
        result.add_warning(
            "type", ErrorCode.TYPE_NOT_FOUND,
            f"Unknown page type: '{page.type}'. Page will be indexed but not type-checked."
        )
        return result

    # Step 2: Check required scope fields
    _validate_required_scope(page, type_def, result)

    # Step 3: Check required fields
    _validate_required_fields(page, type_def, result)

    # Step 4: Check field constraints
    _validate_field_constraints(page, type_def, result)

    if not result.valid:
        logger.debug(
            "Validation failed for '%s' (%s): %d errors, %d warnings",
            page.title, page.type, len(result.errors), len(result.warnings)
        )

    return result


def _validate_required_scope(
    page: ParsedPage,
    type_def: TypeDefinition,
    result: ValidationResult,
) -> None:
    """Check that required scope fields are present."""
    for scope_field in type_def.required_scope:
        value = page.scope.get(scope_field)
        if not value or (isinstance(value, str) and not value.strip()):
            result.add_error(
                f"scope.{scope_field}",
                ErrorCode.REQUIRED_FIELD_MISSING,
                f"Page type '{type_def.id}' requires scope.{scope_field}"
            )


def _validate_required_fields(
    page: ParsedPage,
    type_def: TypeDefinition,
    result: ValidationResult,
) -> None:
    """Check that required fields are present and non-empty."""
    # Map field names to page attribute values
    field_values = _extract_field_values(page)

    for field_name, field_def in type_def.fields.items():
        if not field_def.required:
            continue

        # Skip scope — handled by _validate_required_scope
        if field_name == "scope":
            continue

        value = field_values.get(field_name)

        if value is None:
            result.add_error(
                field_name,
                ErrorCode.REQUIRED_FIELD_MISSING,
                f"Required field '{field_name}' is missing"
            )
        elif isinstance(value, str) and not value.strip():
            result.add_error(
                field_name,
                ErrorCode.REQUIRED_FIELD_MISSING,
                f"Required field '{field_name}' is empty"
            )


def _validate_field_constraints(
    page: ParsedPage,
    type_def: TypeDefinition,
    result: ValidationResult,
) -> None:
    """Check enum values and string length constraints."""
    field_values = _extract_field_values(page)

    for field_name, field_def in type_def.fields.items():
        value = field_values.get(field_name)
        if value is None:
            continue

        # Enum constraint
        if field_def.values and isinstance(value, str):
            if value not in field_def.values:
                result.add_error(
                    field_name,
                    ErrorCode.INVALID_FIELD_VALUE,
                    f"Invalid value '{value}' for '{field_name}' (allowed: {', '.join(field_def.values)})",
                    allowed_values=field_def.values
                )

        # String length constraints
        if isinstance(value, str):
            if field_def.min_length and len(value) < field_def.min_length:
                result.add_warning(
                    field_name,
                    ErrorCode.VALIDATION_ERROR,
                    f"Field '{field_name}' is shorter than recommended minimum ({field_def.min_length} chars)"
                )
            if field_def.max_length and len(value) > field_def.max_length:
                result.add_warning(
                    field_name,
                    ErrorCode.VALIDATION_ERROR,
                    f"Field '{field_name}' exceeds recommended maximum ({field_def.max_length} chars)"
                )


def _extract_field_values(page: ParsedPage) -> dict:
    """Extract a flat dict of field name → value from a ParsedPage."""
    return {
        "title": page.title,
        "description": page.description,
        "type": page.type,
        "mode": page.mode,
        "scope": page.scope if page.scope else None,
        "tags": page.tags if page.tags else None,
        "owner": page.owner,
        "last-verified": page.last_verified,
        "related": page.related if page.related else None,
        "depends-on": page.depends_on if page.depends_on else None,
        "consumed-by": page.consumed_by if page.consumed_by else None,
        "applies-to": page.applies_to if page.applies_to else None,
    }
