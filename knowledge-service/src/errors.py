"""
Structured error handling for Vault Knowledge Service.

All endpoints return structured VaultError responses with consistent format:
{
    "error": {
        "code": "ERROR_CODE",
        "message": "Human-readable description",
        "details": { ... },
        "request_id": "uuid"
    }
}
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class ErrorCode(str, Enum):
    # Client errors (4xx)
    VALIDATION_FAILED = "VALIDATION_FAILED"
    PARSE_ERROR = "PARSE_ERROR"
    PAGE_NOT_FOUND = "PAGE_NOT_FOUND"
    REGISTRY_NOT_FOUND = "REGISTRY_NOT_FOUND"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    INVALID_REQUEST = "INVALID_REQUEST"
    
    # Service errors (5xx)
    SCHEMA_NOT_LOADED = "SCHEMA_NOT_LOADED"
    SEARCH_FAILED = "SEARCH_FAILED"
    SEARCH_ERROR = "SEARCH_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    
    # Validation errors (legacy, used by validator.py)
    TYPE_NOT_FOUND = "TYPE_NOT_FOUND"
    REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
    INVALID_FIELD_VALUE = "INVALID_FIELD_VALUE"
    VALIDATION_ERROR = "VALIDATION_ERROR"


# HTTP status codes for each error code
ERROR_STATUS_CODES: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_FAILED: 400,
    ErrorCode.PARSE_ERROR: 400,
    ErrorCode.INVALID_REQUEST: 400,
    ErrorCode.PAGE_NOT_FOUND: 404,
    ErrorCode.REGISTRY_NOT_FOUND: 404,
    ErrorCode.DUPLICATE_ENTRY: 409,
    ErrorCode.SCHEMA_NOT_LOADED: 503,
    ErrorCode.SEARCH_FAILED: 500,
    ErrorCode.SEARCH_ERROR: 500,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.TYPE_NOT_FOUND: 400,
    ErrorCode.REQUIRED_FIELD_MISSING: 400,
    ErrorCode.INVALID_FIELD_VALUE: 400,
    ErrorCode.VALIDATION_ERROR: 400,
}


class VaultErrorDetail(BaseModel):
    """Structured error response body."""
    code: str
    message: str
    details: Optional[dict[str, Any]] = None
    request_id: str


class VaultErrorResponse(BaseModel):
    """Top-level error response envelope."""
    error: VaultErrorDetail


class VaultError(Exception):
    """Base exception for all Vault service errors."""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details
        self.request_id = request_id or str(uuid.uuid4())
        self.status_code = ERROR_STATUS_CODES.get(code, 500)
    
    def to_response(self) -> VaultErrorResponse:
        return VaultErrorResponse(
            error=VaultErrorDetail(
                code=self.code.value,
                message=self.message,
                details=self.details,
                request_id=self.request_id,
            )
        )


# Convenience constructors

def validation_error(message: str, details: Optional[dict[str, Any]] = None) -> VaultError:
    return VaultError(ErrorCode.VALIDATION_FAILED, message, details)

def not_found(resource: str, identifier: str) -> VaultError:
    return VaultError(
        ErrorCode.PAGE_NOT_FOUND,
        f"{resource} not found: {identifier}",
        {"resource": resource, "identifier": identifier},
    )

def schema_not_loaded(reason: str = "Schema directory not found or failed to load") -> VaultError:
    return VaultError(ErrorCode.SCHEMA_NOT_LOADED, reason)

def internal_error(message: str = "An internal error occurred") -> VaultError:
    return VaultError(ErrorCode.INTERNAL_ERROR, message)

def parse_error(message: str, details: Optional[dict[str, Any]] = None) -> VaultError:
    return VaultError(ErrorCode.PARSE_ERROR, message, details)

def registry_not_found(name: str) -> VaultError:
    return VaultError(
        ErrorCode.REGISTRY_NOT_FOUND,
        f"Registry not found: {name}",
        {"registry": name},
    )

def duplicate_entry(registry: str, entry_id: str) -> VaultError:
    return VaultError(
        ErrorCode.DUPLICATE_ENTRY,
        f"Entry '{entry_id}' already exists in registry '{registry}'",
        {"registry": registry, "entry_id": entry_id},
    )


# --- Legacy compatibility (used by validator.py) ---

class ValidationError:
    """Legacy validation error class. Use VaultError for new code."""
    def __init__(self, field: str, code: str, message: str, allowed_values: Optional[list[str]] = None) -> None:
        self.field = field
        self.code = code
        self.message = message
        self.allowed_values = allowed_values or []


class ValidationResult:
    """Legacy validation result. Used by validator.py for type validation."""
    
    def __init__(self) -> None:
        self.errors: list[ValidationError] = []
        self.warnings: list[ValidationError] = []
    
    @property
    def valid(self) -> bool:
        return len(self.errors) == 0
    
    @classmethod
    def ok(cls) -> ValidationResult:
        return cls()
    
    def add_error(self, field: str, code: ErrorCode, message: str, allowed_values: Optional[list[str]] = None) -> None:
        self.errors.append(ValidationError(field, str(code), message, allowed_values))
    
    def add_warning(self, field: str, code: ErrorCode, message: str) -> None:
        self.warnings.append(ValidationError(field, str(code), message))
