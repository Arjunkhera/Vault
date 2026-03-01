"""
Type definition registry for the Knowledge Service.

Loads page type definitions from YAML files and provides a registry
for looking up types by ID. Used by the validator to enforce required
fields and scope constraints per page type.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from ..errors import VaultError, ErrorCode


logger = logging.getLogger(__name__)


@dataclass
class FieldDefinition:
    """Schema for a single field in a type definition."""
    required: bool = False
    description: str = ""
    min_length: Optional[int] = None
    max_length: Optional[int] = None
    values: Optional[list[str]] = None  # enum constraint
    default: Optional[str] = None


@dataclass
class TypeDefinition:
    """A page type definition loaded from YAML."""
    id: str
    name: str
    description: str
    required_scope: list[str] = field(default_factory=list)
    fields: dict[str, FieldDefinition] = field(default_factory=dict)
    template: Optional[str] = None


class TypeRegistry:
    """
    Registry of page type definitions.

    Loads type definitions from a directory of YAML files at startup.
    Provides lookup by type ID and listing of all types.
    """

    def __init__(self):
        self._types: dict[str, TypeDefinition] = {}
        self._base_fields: dict[str, FieldDefinition] = {}

    def load_from_directory(self, types_dir: str) -> None:
        """
        Load all type definitions from a directory.

        Loads _base.yaml first (common fields), then all other .yaml files.
        """
        types_path = Path(types_dir)

        if not types_path.is_dir():
            logger.warning("Types directory not found: %s", types_dir)
            return

        # Load _base.yaml first for shared field definitions
        base_file = types_path / "_base.yaml"
        if base_file.exists():
            self._load_base(base_file)
            logger.info("Loaded base field definitions from _base.yaml")

        # Load all other type definitions
        loaded = 0
        for yaml_file in sorted(types_path.glob("*.yaml")):
            if yaml_file.name == "_base.yaml":
                continue
            try:
                type_def = self._load_type(yaml_file)
                self._types[type_def.id] = type_def
                loaded += 1
                logger.debug("Loaded type definition: %s", type_def.id)
            except Exception as e:
                logger.error("Failed to load type definition %s: %s", yaml_file.name, e)

        logger.info("Loaded %d type definitions from %s", loaded, types_dir)

    def _load_base(self, path: Path) -> None:
        """Load _base.yaml and extract shared field definitions."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        if not data or "fields" not in data:
            return

        for field_name, field_data in data["fields"].items():
            self._base_fields[field_name] = _parse_field(field_data)

    def _load_type(self, path: Path) -> TypeDefinition:
        """Load a single type definition from a YAML file."""
        with open(path, 'r') as f:
            data = yaml.safe_load(f)

        if not data or "id" not in data:
            raise ValueError(f"Type definition missing 'id' field: {path}")

        # Parse type-specific fields and merge with base fields
        type_fields = {}
        if data.get("fields"):
            for field_name, field_data in data["fields"].items():
                type_fields[field_name] = _parse_field(field_data)

        # Merge: base fields + type-specific fields (type overrides base)
        merged_fields = {**self._base_fields, **type_fields}

        return TypeDefinition(
            id=data["id"],
            name=data.get("name", data["id"]),
            description=data.get("description", ""),
            required_scope=data.get("required_scope", []),
            fields=merged_fields,
            template=data.get("template"),
        )

    def get_type(self, type_id: str) -> Optional[TypeDefinition]:
        """Look up a type definition by ID. Returns None if not found."""
        return self._types.get(type_id)

    def list_types(self) -> list[TypeDefinition]:
        """Return all registered type definitions."""
        return list(self._types.values())

    def type_ids(self) -> list[str]:
        """Return all registered type IDs."""
        return list(self._types.keys())

    def has_type(self, type_id: str) -> bool:
        """Check if a type ID is registered."""
        return type_id in self._types


def _parse_field(data: dict | str | None) -> FieldDefinition:
    """Parse a field definition from YAML data."""
    if data is None or isinstance(data, str):
        return FieldDefinition(description=data or "")

    return FieldDefinition(
        required=data.get("required", False),
        description=data.get("description", ""),
        min_length=data.get("min_length"),
        max_length=data.get("max_length"),
        values=data.get("values"),
        default=data.get("default"),
    )
