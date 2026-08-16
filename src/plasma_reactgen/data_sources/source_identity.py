"""Translate source metadata into the names used by source profiles."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_INTERNAL_SOURCE_BY_CATEGORY = {
    "species_identity": "internal_species_db",
    "properties": "internal_property_db",
    "electron_cross_sections": "internal_cross_section_db",
    "ion_neutral_reactions": "internal_reaction_db",
    "electron_reactions": "internal_reaction_db",
}


def source_name_from_record(
    source_record: dict[str, Any],
    category: str,
) -> str | None:
    """Return a profile source name for one provenance record."""

    explicit_name = _explicit_source_name(source_record)
    if explicit_name:
        return explicit_name

    source_type = str(source_record.get("source_type") or "")
    resolver = _SOURCE_NAME_RESOLVERS.get(source_type)
    mapped_name = resolver(source_record, category) if resolver else None
    return mapped_name or source_type or None


def _explicit_source_name(source_record: dict[str, Any]) -> str | None:
    for key in ("source_name", "provider", "name"):
        value = source_record.get(key)
        if value:
            return str(value)
    return None


def _internal_source_name(
    source_record: dict[str, Any],
    category: str,
) -> str:
    _ = source_record
    return _INTERNAL_SOURCE_BY_CATEGORY.get(category, "internal_file")


def _snapshot_source_name(
    source_record: dict[str, Any],
    category: str,
) -> str | None:
    _ = category
    database = str(source_record.get("database") or "")
    lowered = database.lower()
    if "nist" in lowered:
        return "nist_snapshot"
    if "lxcat" in lowered:
        return "lxcat_offline"
    return None


def _chemicals_source_name(
    source_record: dict[str, Any],
    category: str,
) -> str | None:
    _ = category
    database = str(source_record.get("database") or "")
    return "chemicals_optional" if database == "chemicals" else None


def _ion_snapshot_source_name(
    source_record: dict[str, Any],
    category: str,
) -> str | None:
    _ = category
    database = str(source_record.get("database") or "")
    return "ion_reaction_table" if "ion" in database.lower() else None


SourceNameResolver = Callable[[dict[str, Any], str], str | None]
_SOURCE_NAME_RESOLVERS: dict[str, SourceNameResolver] = {
    "internal_file_db": _internal_source_name,
    "public_database_snapshot": _snapshot_source_name,
    "python_package": _chemicals_source_name,
    "local_snapshot": _ion_snapshot_source_name,
}


__all__ = ["source_name_from_record"]
