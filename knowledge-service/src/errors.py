"""
Structured error handling for the Knowledge Service.

Provides error codes, field-level validation errors, validation results,
and a base exception class. All service functions should use these types
for consistent error reporting.

Pattern:
- Functions return results or raise VaultError
- Validation returns ValidationResult (non-blocking: warnings don't stop indexing)
- API layer catches VaultError and returns ErrorResponse
"""

import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """Error codes for the Knowledge Service."""
    VALIDATION_ERROR = "validation_error"
    TYPE_NOT_FOUND = "type_not_found"
    PAGE_NOT_FOUND = "page_not_found"
    SCOPE_INVALID = "scope_invalid"
    REQUIRED_FIELD_MISSING = "required_field_missing"
    INVALID_FIELD_VALUE = "invalid_field_value"
    SEARCH_ERROR = "search_error"
    SYNC_ERROR = "sync_error"
    INDEX_ERROR = "index_error"
    INTERNAL_ERROR = "internal_error"


@dataclass
class FieldError:
    """A single field-level validation error."""
    field: str
    code: ErrorCode
    message: str
    allowed_values: Optional[list[str]] = None


@dataclass
class ValidationResult:
    """
    Result of validating a knowledge page against its type definition.

    Validation is non-blocking: pages with errors are still indexed.
    Errors indicate required fields missing or invalid values.
    Warnings indicate optional issues (e.g., short description).
    """
    valid: bool
    errors: list[FieldError] = field(default_factory=list)
    warnings: list[FieldError] = field(default_factory=list)

    @staticmethod
    def ok() -> "ValidationResult":
        """Create a passing validation result."""
        return ValidationResult(valid=True)

    def add_error(self, field_name: str, code: ErrorCode, message: str,
                  allowed_values: Optional[list[str]] = None) -> None:
        """Add an error and mark result as invalid."""
        self.valid = False
        self.errors.append(FieldError(
            field=field_name, code=code, message=message,
            allowed_values=allowed_values
        ))

    def add_warning(self, field_name: str, code: ErrorCode, message: str,
                    allowed_values: Optional[list[str]] = None) -> None:
        """Add a warning without affecting validity."""
        self.warnings.append(FieldError(
            field=field_name, code=code, message=message,
            allowed_values=allowed_values
        ))

    def to_dict(self) -> dict:
        """Serialize for API responses."""
        result: dict = {"valid": self.valid}
        if self.errors:
            result["errors"] = [
                {"field": e.field, "code": e.code.value, "message": e.message}
                for e in self.errors
            ]
        if self.warnings:
            result["warnings"] = [
                {"field": w.field, "code": w.code.value, "message": w.message}
                for w in self.warnings
            ]
        return result


class VaultError(Exception):
    """
    Structured exception for the Knowledge Service.

    Raised by service functions, caught by the API layer and
    converted to ErrorResponse JSON.
    """
    def __init__(self, code: ErrorCode, message: str,
                 field: Optional[str] = None,
                 details: Optional[dict] = None):
        self.code = code
        self.message = message
        self.field = field
        self.details = details
        super().__init__(f"[{code.value}] {message}")

    def to_dict(self) -> dict:
        """Serialize for API responses."""
        result = {
            "error": True,
            "code": self.code.value,
            "message": self.message,
        }
        if self.field:
            result["field"] = self.field
        if self.details:
            result["details"] = self.details
        return result
