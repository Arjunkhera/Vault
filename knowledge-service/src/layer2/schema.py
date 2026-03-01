"""
from __future__ import annotations
Schema loader and page validator for Knowledge Service write path.

SchemaLoader reads _schema/schema.yaml and _schema/registries/*.yaml from the
knowledge repo, holds them in memory, and exposes reload() for the sync daemon.

PageValidator validates parsed pages against the loaded schema and registries,
returning structured errors with fuzzy-match suggestions for unknown values.
"""

import logging
import re
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path
from typing import Any, Optional

import yaml  # type: ignore[import,import-untyped]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation result models
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A validation failure that must be fixed before a page is accepted."""
    field_name: str
    value: str | list[Any] | None = None
    message: str = ""
    suggestions: list[str] = field(default_factory=list)
    action_required: str = "provide_value"  # pick_or_add | provide_value | fix_format | fix_constraint


@dataclass
class ValidationWarning:
    """A non-blocking suggestion (e.g. recommended field missing)."""
    field_name: str
    message: str = ""


@dataclass
class ValidationResult:
    """Aggregate result of page validation."""
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    warnings: list[ValidationWarning] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------

@dataclass
class PageTypeDefinition:
    """In-memory representation of a page type from schema.yaml."""
    id: str
    description: str = ""
    required_fields: list[str] = field(default_factory=list)
    recommended_fields: list[str] = field(default_factory=list)
    required_scope_fields: list[str] = field(default_factory=list)
    allowed_modes: list[str] = field(default_factory=list)


@dataclass
class RegistryEntry:
    """A single entry in a registry (tag, program, or team)."""
    id: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    scope_program: Optional[str] = None  # optional program association


class SchemaLoader:
    """
    Loads schema.yaml + registry YAML files from a _schema/ directory.

    Typical usage:
        loader = SchemaLoader("/data/knowledge-repo/_schema")
        loader.load()
        schema = loader.get_schema()
        tags = loader.get_registry("tags")
    """

    def __init__(self, schema_dir: str | Path) -> None:
        self._schema_dir = Path(schema_dir)
        self._version: int = 0
        self._page_types: dict[str, PageTypeDefinition] = {}
        self._field_constraints: dict[str, Any] = {}
        self._registries: dict[str, list[RegistryEntry]] = {}

    # -- public API ----------------------------------------------------------

    def load(self) -> None:
        """Read all YAML files from disk into memory."""
        self._load_schema()
        self._load_registries()

    def reload(self) -> None:
        """Re-read everything (called by file-watcher / sync daemon)."""
        logger.info("Reloading schema and registries from %s", self._schema_dir)
        self.load()

    def get_schema(self) -> dict[str, Any]:
        """Return the full schema as a JSON-serialisable dict."""
        return {
            "version": self._version,
            "page_types": [
                {
                    "id": pt.id,
                    "description": pt.description,
                    "required_fields": pt.required_fields,
                    "recommended_fields": pt.recommended_fields,
                    "required_scope_fields": pt.required_scope_fields,
                    "allowed_modes": pt.allowed_modes,
                }
                for pt in self._page_types.values()
            ],
            "field_constraints": self._field_constraints,
            "registries": {
                name: [
                    {"id": e.id, "description": e.description, "aliases": e.aliases}
                    | ({"scope_program": e.scope_program} if e.scope_program else {})
                    for e in entries
                ]
                for name, entries in self._registries.items()
            },
        }

    def get_registry(self, name: str) -> list[RegistryEntry]:
        """Return entries for a named registry, or empty list."""
        return self._registries.get(name, [])

    def get_page_type(self, type_id: str) -> Optional[PageTypeDefinition]:
        return self._page_types.get(type_id)

    def known_page_type_ids(self) -> list[str]:
        return list(self._page_types.keys())

    @property
    def field_constraints(self) -> dict[str, Any]:
        return self._field_constraints

    @property
    def version(self) -> int:
        return self._version

    @property
    def page_types(self) -> dict[str, PageTypeDefinition]:
        return self._page_types

    @property
    def registries(self) -> dict[str, list[RegistryEntry]]:
        return self._registries

    # -- registry mutation (for /registry/add) --------------------------------

    def add_registry_entry(self, registry_name: str, entry: RegistryEntry) -> None:
        """
        Add an entry to a registry in memory and persist to YAML on disk.

        Raises ValueError if the registry doesn't exist or the id is a duplicate.
        """
        if registry_name not in self._registries:
            raise ValueError(f"Unknown registry: {registry_name}")

        existing_ids = {e.id for e in self._registries[registry_name]}
        if entry.id in existing_ids:
            raise ValueError(f"Duplicate entry '{entry.id}' in registry '{registry_name}'")

        self._registries[registry_name].append(entry)
        self._persist_registry(registry_name)

    # -- internal loading ----------------------------------------------------

    def _load_schema(self) -> None:
        schema_file = self._schema_dir / "schema.yaml"
        if not schema_file.exists():
            logger.warning("Schema file not found: %s", schema_file)
            return

        with open(schema_file) as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}

        self._version = raw.get("version", 0)
        
        # Convert field_constraints from list to dict format
        # YAML has: [{"field": "title", "max_length": 120}, ...]
        # We need: {"title": {"max_length": 120}, ...}
        constraints_list: list[dict[str, Any]] = raw.get("field_constraints", [])
        self._field_constraints = {}
        for constraint in constraints_list:
            constraint_copy = constraint.copy()
            field_name: str = constraint_copy.pop("field")
            self._field_constraints[field_name] = constraint_copy

        self._page_types = {}
        for pt_raw in raw.get("page_types", []):
            pt = PageTypeDefinition(
                id=pt_raw["id"],
                description=pt_raw.get("description", ""),
                required_fields=pt_raw.get("required_fields", []),
                recommended_fields=pt_raw.get("recommended_fields", []),
                required_scope_fields=pt_raw.get("required_scope_fields", []),
                allowed_modes=pt_raw.get("allowed_modes", []),
            )
            self._page_types[pt.id] = pt

        logger.info(
            "Schema loaded: version=%d, %d page types, %d field constraints",
            self._version, len(self._page_types), len(self._field_constraints),
        )

    def _load_registries(self) -> None:
        reg_dir = self._schema_dir / "registries"
        if not reg_dir.exists():
            logger.warning("Registries directory not found: %s", reg_dir)
            return

        self._registries = {}
        for reg_file in sorted(reg_dir.glob("*.yaml")):
            name = reg_file.stem  # e.g. "tags", "programs"
            with open(reg_file) as f:
                raw: dict[str, Any] = yaml.safe_load(f) or {}

            entries: list[RegistryEntry] = []
            for item in raw.get(name, []):
                entries.append(RegistryEntry(
                    id=item["id"],
                    description=item.get("description", ""),
                    aliases=item.get("aliases", []),
                    scope_program=item.get("scope_program"),
                ))
            self._registries[name] = entries
            logger.info("Registry '%s' loaded: %d entries", name, len(entries))

    def _persist_registry(self, name: str) -> None:
        """Write a registry back to its YAML file."""
        reg_file = self._schema_dir / "registries" / f"{name}.yaml"
        entries = self._registries.get(name, [])
        data: dict[str, Any] = {
            name: [
                {"id": e.id, "description": e.description}
                | ({"aliases": e.aliases} if e.aliases else {})
                | ({"scope_program": e.scope_program} if e.scope_program else {})
                for e in entries
            ]
        }
        with open(reg_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        logger.info("Registry '%s' persisted (%d entries)", name, len(entries))


# ---------------------------------------------------------------------------
# Fuzzy matching helpers
# ---------------------------------------------------------------------------

def _build_alias_map(entries: list[RegistryEntry]) -> dict[str, str]:
    """Build lowercase alias → canonical id mapping."""
    alias_map: dict[str, str] = {}
    for entry in entries:
        alias_map[entry.id.lower()] = entry.id
        for alias in entry.aliases:
            alias_map[alias.lower()] = entry.id
    return alias_map


def _fuzzy_match_registry(
    value: str,
    entries: list[RegistryEntry],
    cutoff: float = 0.6,
    n: int = 3,
) -> tuple[Optional[str], list[str]]:
    """
    Match a value against a registry.

    Returns:
        (canonical_id_or_None, list_of_suggestions)
        - If exact match: (canonical_id, [])
        - If alias match: (canonical_id, [])   (caller should warn)
        - If no match:    (None, [close_matches])
    """
    alias_map = _build_alias_map(entries)

    # Exact id match (case-insensitive)
    lower = value.lower()
    if lower in alias_map:
        canonical = alias_map[lower]
        is_exact = canonical.lower() == lower
        return canonical, [] if is_exact else [canonical]

    # Fuzzy match against all known ids + aliases
    all_candidates = list(alias_map.keys())
    close = get_close_matches(lower, all_candidates, n=n, cutoff=cutoff)
    suggestions = list(dict.fromkeys(alias_map[c] for c in close))  # dedupe, preserve order
    return None, suggestions


# ---------------------------------------------------------------------------
# Page validator
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PageValidator:
    """
    Validates a parsed page dict (frontmatter) against the loaded schema.

    Usage:
        validator = PageValidator(schema_loader)
        result = validator.validate(frontmatter_dict)
    """

    def __init__(self, loader: SchemaLoader) -> None:
        self._loader = loader

    def validate(self, metadata: dict[str, Any]) -> ValidationResult:
        """
        Run all validation checks on a frontmatter dict.

        Validation order (matches the design doc):
        1. type is known
        2. required fields present
        3. field constraint checks (length, min_items, date format)
        4. registry-backed field checks (tags, scope.program, scope.repo)
        5. mode in allowed_modes for the page type
        6. required_scope_fields present
        7. recommended fields → warnings
        """
        errors: list[ValidationError] = []
        warnings: list[ValidationWarning] = []

        # -- 1. type ----------------------------------------------------------
        page_type_id = metadata.get("type")
        if not page_type_id:
            errors.append(ValidationError(
                field_name="type",
                message="Required field 'type' is missing",
                action_required="provide_value",
            ))
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        pt = self._loader.get_page_type(page_type_id)
        if pt is None:
            known = self._loader.known_page_type_ids()
            suggestions = get_close_matches(page_type_id, known, n=3, cutoff=0.5)
            errors.append(ValidationError(
                field_name="type",
                value=page_type_id,
                message=f"Unknown page type '{page_type_id}'",
                suggestions=suggestions or known,
                action_required="pick_or_add",
            ))
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        # -- 2. required fields -----------------------------------------------
        for req_field in pt.required_fields:
            if req_field == "type":
                continue  # already checked
            val = metadata.get(req_field)
            if val is None or val == "" or val == []:
                errors.append(ValidationError(
                    field_name=req_field,
                    message=f"Required field '{req_field}' is missing",
                    action_required="provide_value",
                ))

        # -- 3. field constraints ---------------------------------------------
        constraints = self._loader.field_constraints

        # title length
        title = metadata.get("title")
        if title and "title" in constraints:
            max_len = constraints["title"].get("max_length", 999)
            if len(title) > max_len:
                errors.append(ValidationError(
                    field_name="title",
                    value=title,
                    message=f"Title exceeds {max_len} characters (got {len(title)})",
                    action_required="fix_constraint",
                ))

        # description length
        desc = metadata.get("description")
        if desc and "description" in constraints:
            max_len = constraints["description"].get("max_length", 999)
            if len(desc) > max_len:
                errors.append(ValidationError(
                    field_name="description",
                    value=desc,
                    message=f"Description exceeds {max_len} characters (got {len(desc)})",
                    action_required="fix_constraint",
                ))

        # tags min_items
        tags = metadata.get("tags")
        if isinstance(tags, list) and "tags" in constraints:
            min_items = constraints["tags"].get("min_items", 0)
            if len(tags) < min_items:
                errors.append(ValidationError(
                    field_name="tags",
                    value=tags,
                    message=f"'tags' requires at least {min_items} item(s), got {len(tags)}",
                    action_required="fix_constraint",
                ))

        # scope min_fields
        scope = metadata.get("scope")
        if isinstance(scope, dict) and "scope" in constraints:
            min_fields = constraints["scope"].get("min_fields", 0)
            filled = {k: v for k, v in scope.items() if v}
            if len(filled) < min_fields:
                errors.append(ValidationError(
                    field_name="scope",
                    message=f"'scope' requires at least {min_fields} field(s), got {len(filled)}",
                    action_required="fix_constraint",
                ))

        # last-verified date format
        last_verified = metadata.get("last-verified")
        if last_verified is not None:
            lv_str = str(last_verified)
            if not _DATE_RE.match(lv_str):
                errors.append(ValidationError(
                    field_name="last-verified",
                    value=lv_str,
                    message="'last-verified' must be in YYYY-MM-DD format",
                    action_required="fix_format",
                ))

        # auto-generated boolean
        auto_gen = metadata.get("auto-generated")
        if auto_gen is not None and not isinstance(auto_gen, bool):
            errors.append(ValidationError(
                field_name="auto-generated",
                value=str(auto_gen),
                message="'auto-generated' must be a boolean (true/false)",
                action_required="fix_format",
            ))

        # -- 4. registry-backed checks ---------------------------------------
        self._check_registry_list(metadata, "tags", "tags", errors, warnings)
        if isinstance(scope, dict):
            self._check_registry_scalar(scope, "program", "programs", "scope.program", errors, warnings)
            self._check_registry_scalar(scope, "repo", "repos", "scope.repo", errors, warnings)

        # -- 5. mode in allowed_modes -----------------------------------------
        mode = metadata.get("mode")
        if mode and pt.allowed_modes and mode not in pt.allowed_modes:
            errors.append(ValidationError(
                field_name="mode",
                value=mode,
                message=f"Mode '{mode}' is not allowed for type '{pt.id}'. Allowed: {pt.allowed_modes}",
                suggestions=pt.allowed_modes,
                action_required="pick_or_add",
            ))

        # -- 6. required scope fields -----------------------------------------
        if pt.required_scope_fields and isinstance(scope, dict):
            for rsf in pt.required_scope_fields:
                if not scope.get(rsf):
                    errors.append(ValidationError(
                        field_name=f"scope.{rsf}",
                        message=f"Page type '{pt.id}' requires scope field '{rsf}'",
                        action_required="provide_value",
                    ))

        # -- 7. recommended fields → warnings --------------------------------
        for rec_field in pt.recommended_fields:
            val = metadata.get(rec_field)
            if val is None or val == "" or val == []:
                warnings.append(ValidationWarning(
                    field_name=rec_field,
                    message=f"Recommended field '{rec_field}' is not set",
                ))

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # -- registry helpers ---------------------------------------------------

    def _check_registry_list(
        self,
        metadata: dict[str, Any],
        field_name: str,
        registry_name: str,
        errors: list[ValidationError],
        warnings: list[ValidationWarning],
    ) -> None:
        """Validate each item in a list field against a registry."""
        values = metadata.get(field_name)
        if not isinstance(values, list):
            return

        entries = self._loader.get_registry(registry_name)
        if not entries:
            return  # registry empty (cold start) — skip

        for val in values:
            canonical, suggestions = _fuzzy_match_registry(str(val), entries)
            if canonical is None:
                errors.append(ValidationError(
                    field_name=field_name,
                    value=val,
                    message=f"Unknown {field_name[:-1] if field_name.endswith('s') else field_name} '{val}'",
                    suggestions=suggestions,
                    action_required="pick_or_add",
                ))
            elif suggestions:
                # alias match — warn with canonical form
                warnings.append(ValidationWarning(
                    field_name=field_name,
                    message=f"'{val}' is an alias for '{canonical}'. Consider using the canonical form.",
                ))

    def _check_registry_scalar(
        self,
        container: dict[str, Any],
        field_name: str,
        registry_name: str,
        display_field: str,
        errors: list[ValidationError],
        warnings: list[ValidationWarning],
    ) -> None:
        """Validate a single scalar field against a registry."""
        value = container.get(field_name)
        if not value:
            return

        entries = self._loader.get_registry(registry_name)
        if not entries:
            return  # cold start — skip

        canonical, suggestions = _fuzzy_match_registry(str(value), entries)
        if canonical is None:
            errors.append(ValidationError(
                field_name=display_field,
                value=value,
                message=f"Unknown {display_field} value '{value}'",
                suggestions=suggestions,
                action_required="pick_or_add",
            ))
        elif suggestions:
            warnings.append(ValidationWarning(
                field_name=display_field,
                message=f"'{value}' is an alias for '{canonical}'. Consider using the canonical form.",
            ))
