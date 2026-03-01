"""Tests for the errors module."""

from src.errors import ErrorCode, FieldError, ValidationResult, VaultError


class TestErrorCode:
    def test_all_codes_have_string_values(self):
        for code in ErrorCode:
            assert isinstance(code.value, str)

    def test_key_codes_exist(self):
        assert ErrorCode.VALIDATION_ERROR
        assert ErrorCode.PAGE_NOT_FOUND
        assert ErrorCode.TYPE_NOT_FOUND
        assert ErrorCode.SEARCH_ERROR


class TestFieldError:
    def test_create_field_error(self):
        err = FieldError(
            field="description",
            code=ErrorCode.REQUIRED_FIELD_MISSING,
            message="description is required",
        )
        assert err.field == "description"
        assert err.code == ErrorCode.REQUIRED_FIELD_MISSING
        assert err.allowed_values is None

    def test_field_error_with_allowed_values(self):
        err = FieldError(
            field="mode",
            code=ErrorCode.INVALID_FIELD_VALUE,
            message="Invalid mode",
            allowed_values=["reference", "operational", "keystone"],
        )
        assert err.allowed_values == ["reference", "operational", "keystone"]


class TestValidationResult:
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

    def test_add_warning_stays_valid(self):
        result = ValidationResult.ok()
        result.add_warning("description", ErrorCode.VALIDATION_ERROR, "description is short")
        assert result.valid is True
        assert len(result.warnings) == 1

    def test_to_dict_valid(self):
        result = ValidationResult.ok()
        d = result.to_dict()
        assert d == {"valid": True}

    def test_to_dict_with_errors(self):
        result = ValidationResult.ok()
        result.add_error("title", ErrorCode.REQUIRED_FIELD_MISSING, "missing")
        d = result.to_dict()
        assert d["valid"] is False
        assert len(d["errors"]) == 1
        assert d["errors"][0]["field"] == "title"

    def test_to_dict_with_warnings(self):
        result = ValidationResult.ok()
        result.add_warning("desc", ErrorCode.VALIDATION_ERROR, "short")
        d = result.to_dict()
        assert d["valid"] is True
        assert len(d["warnings"]) == 1


class TestVaultError:
    def test_create_vault_error(self):
        err = VaultError(ErrorCode.PAGE_NOT_FOUND, "Page not found: foo.md")
        assert err.code == ErrorCode.PAGE_NOT_FOUND
        assert err.message == "Page not found: foo.md"
        assert err.field is None

    def test_vault_error_with_field(self):
        err = VaultError(
            ErrorCode.REQUIRED_FIELD_MISSING,
            "description is required",
            field="description",
        )
        assert err.field == "description"

    def test_vault_error_str(self):
        err = VaultError(ErrorCode.SEARCH_ERROR, "QMD failed")
        assert "[search_error]" in str(err)

    def test_to_dict(self):
        err = VaultError(ErrorCode.PAGE_NOT_FOUND, "not found", field="id")
        d = err.to_dict()
        assert d["error"] is True
        assert d["code"] == "page_not_found"
        assert d["message"] == "not found"
        assert d["field"] == "id"

    def test_to_dict_no_optional_fields(self):
        err = VaultError(ErrorCode.INTERNAL_ERROR, "boom")
        d = err.to_dict()
        assert "field" not in d
        assert "details" not in d
