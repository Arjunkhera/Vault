"""Tests for the errors module."""

from src.errors import (
    ErrorCode,
    VaultError,
    ValidationResult,
    ValidationError,
    validation_error,
    not_found,
    schema_not_loaded,
    internal_error,
    parse_error,
    registry_not_found,
    duplicate_entry,
    ERROR_STATUS_CODES,
)


class TestErrorCode:
    """Test ErrorCode enum."""
    
    def test_all_codes_have_string_values(self):
        for code in ErrorCode:
            assert isinstance(code.value, str)

    def test_key_codes_exist(self):
        assert ErrorCode.VALIDATION_FAILED
        assert ErrorCode.PAGE_NOT_FOUND
        assert ErrorCode.SEARCH_ERROR
        assert ErrorCode.INTERNAL_ERROR


class TestValidationError:
    """Test legacy ValidationError class."""
    
    def test_create_validation_error(self):
        err = ValidationError(
            field="description",
            code=ErrorCode.REQUIRED_FIELD_MISSING.value,
            message="description is required",
        )
        assert err.field == "description"
        assert err.code == ErrorCode.REQUIRED_FIELD_MISSING.value
        assert err.allowed_values == []

    def test_validation_error_with_allowed_values(self):
        err = ValidationError(
            field="mode",
            code=ErrorCode.INVALID_FIELD_VALUE.value,
            message="Invalid mode",
            allowed_values=["reference", "operational", "keystone"],
        )
        assert err.allowed_values == ["reference", "operational", "keystone"]


class TestValidationResult:
    """Test legacy ValidationResult class used by validator.py."""
    
    def test_ok_result(self):
        result = ValidationResult.ok()
        assert result.valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error_marks_invalid(self):
        result = ValidationResult.ok()
        result.add_error("title", ErrorCode.REQUIRED_FIELD_MISSING, "title is required")
        assert result.valid is False
        assert len(result.errors) == 1
        assert result.errors[0].field == "title"

    def test_add_warning_stays_valid(self):
        result = ValidationResult.ok()
        result.add_warning("description", ErrorCode.VALIDATION_ERROR, "description is short")
        assert result.valid is True
        assert len(result.warnings) == 1

    def test_multiple_errors(self):
        result = ValidationResult.ok()
        result.add_error("title", ErrorCode.REQUIRED_FIELD_MISSING, "missing")
        result.add_error("description", ErrorCode.REQUIRED_FIELD_MISSING, "missing")
        assert result.valid is False
        assert len(result.errors) == 2

    def test_errors_and_warnings(self):
        result = ValidationResult.ok()
        result.add_error("title", ErrorCode.REQUIRED_FIELD_MISSING, "missing")
        result.add_warning("tags", ErrorCode.VALIDATION_ERROR, "empty")
        assert result.valid is False
        assert len(result.errors) == 1
        assert len(result.warnings) == 1


class TestVaultError:
    """Test VaultError exception."""
    
    def test_create_vault_error(self):
        err = VaultError(ErrorCode.PAGE_NOT_FOUND, "Page not found: foo.md")
        assert err.code == ErrorCode.PAGE_NOT_FOUND
        assert err.message == "Page not found: foo.md"
        assert err.details is None

    def test_vault_error_with_details(self):
        details = {"resource": "page", "identifier": "foo.md"}
        err = VaultError(
            ErrorCode.PAGE_NOT_FOUND,
            "Page not found: foo.md",
            details=details,
        )
        assert err.details == details

    def test_vault_error_generates_request_id(self):
        err = VaultError(ErrorCode.INTERNAL_ERROR, "error")
        assert err.request_id is not None
        assert len(err.request_id) > 0

    def test_vault_error_custom_request_id(self):
        custom_id = "custom-request-id-123"
        err = VaultError(ErrorCode.INTERNAL_ERROR, "error", request_id=custom_id)
        assert err.request_id == custom_id

    def test_vault_error_status_code_mapping(self):
        # 404 errors
        err = VaultError(ErrorCode.PAGE_NOT_FOUND, "not found")
        assert err.status_code == 404

        # 400 errors
        err = VaultError(ErrorCode.VALIDATION_FAILED, "invalid")
        assert err.status_code == 400

        # 500 errors
        err = VaultError(ErrorCode.INTERNAL_ERROR, "error")
        assert err.status_code == 500

        # 503 errors
        err = VaultError(ErrorCode.SCHEMA_NOT_LOADED, "schema missing")
        assert err.status_code == 503

    def test_to_response(self):
        err = VaultError(
            ErrorCode.PAGE_NOT_FOUND,
            "not found",
            details={"id": "foo.md"},
        )
        response = err.to_response()
        
        assert response.error.code == "PAGE_NOT_FOUND"
        assert response.error.message == "not found"
        assert response.error.details == {"id": "foo.md"}
        assert response.error.request_id == err.request_id

    def test_to_response_no_details(self):
        err = VaultError(ErrorCode.INTERNAL_ERROR, "boom")
        response = err.to_response()
        
        assert response.error.code == "INTERNAL_ERROR"
        assert response.error.message == "boom"
        assert response.error.details is None


class TestConvenienceConstructors:
    """Test convenience constructor functions."""
    
    def test_validation_error_constructor(self):
        err = validation_error("Invalid input", {"field": "title"})
        assert err.code == ErrorCode.VALIDATION_FAILED
        assert err.message == "Invalid input"
        assert err.status_code == 400

    def test_not_found_constructor(self):
        err = not_found("page", "my-page.md")
        assert err.code == ErrorCode.PAGE_NOT_FOUND
        assert "my-page.md" in err.message
        assert err.details == {"resource": "page", "identifier": "my-page.md"}
        assert err.status_code == 404

    def test_schema_not_loaded_constructor(self):
        err = schema_not_loaded()
        assert err.code == ErrorCode.SCHEMA_NOT_LOADED
        assert err.message == "Schema directory not found or failed to load"
        assert err.status_code == 503

    def test_schema_not_loaded_custom_reason(self):
        err = schema_not_loaded("Custom failure reason")
        assert err.message == "Custom failure reason"

    def test_internal_error_constructor(self):
        err = internal_error()
        assert err.code == ErrorCode.INTERNAL_ERROR
        assert err.message == "An internal error occurred"
        assert err.status_code == 500

    def test_internal_error_custom_message(self):
        err = internal_error("Database connection failed")
        assert err.message == "Database connection failed"

    def test_parse_error_constructor(self):
        err = parse_error("Invalid YAML", {"line": 5})
        assert err.code == ErrorCode.PARSE_ERROR
        assert err.message == "Invalid YAML"
        assert err.details == {"line": 5}
        assert err.status_code == 400

    def test_registry_not_found_constructor(self):
        err = registry_not_found("tags")
        assert err.code == ErrorCode.REGISTRY_NOT_FOUND
        assert "tags" in err.message
        assert err.details == {"registry": "tags"}
        assert err.status_code == 404

    def test_duplicate_entry_constructor(self):
        err = duplicate_entry("tags", "python")
        assert err.code == ErrorCode.DUPLICATE_ENTRY
        assert "python" in err.message
        assert "tags" in err.message
        assert err.details == {"registry": "tags", "entry_id": "python"}
        assert err.status_code == 409


class TestErrorStatusCodeMapping:
    """Test ERROR_STATUS_CODES dictionary."""
    
    def test_all_error_codes_mapped(self):
        for code in ErrorCode:
            assert code in ERROR_STATUS_CODES
            status = ERROR_STATUS_CODES[code]
            assert isinstance(status, int)
            assert 400 <= status < 600

    def test_4xx_errors(self):
        """Test client errors are 4xx."""
        assert ERROR_STATUS_CODES[ErrorCode.VALIDATION_FAILED] == 400
        assert ERROR_STATUS_CODES[ErrorCode.PARSE_ERROR] == 400
        assert ERROR_STATUS_CODES[ErrorCode.PAGE_NOT_FOUND] == 404
        assert ERROR_STATUS_CODES[ErrorCode.REGISTRY_NOT_FOUND] == 404
        assert ERROR_STATUS_CODES[ErrorCode.DUPLICATE_ENTRY] == 409

    def test_5xx_errors(self):
        """Test server errors are 5xx."""
        assert ERROR_STATUS_CODES[ErrorCode.INTERNAL_ERROR] == 500
        assert ERROR_STATUS_CODES[ErrorCode.SEARCH_FAILED] == 500
        assert ERROR_STATUS_CODES[ErrorCode.SEARCH_ERROR] == 500
        assert ERROR_STATUS_CODES[ErrorCode.SCHEMA_NOT_LOADED] == 503
        assert ERROR_STATUS_CODES[ErrorCode.SERVICE_UNAVAILABLE] == 503
