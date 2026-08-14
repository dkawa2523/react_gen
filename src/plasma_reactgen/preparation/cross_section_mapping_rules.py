from __future__ import annotations

from pathlib import Path
from typing import Any

from plasma_reactgen.infrastructure.registry_paths import (
    registry_asset_exists,
    resolve_registry_asset,
)


def validate_mapping_entry(
    prepared_registry: Path,
    entry: Any,
    mapping_index: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(entry, dict):
        return None, {
            "mapping_index": mapping_index,
            "reaction_id": None,
            "asset_path": None,
            "reason": "invalid_mapping_entry",
        }

    reason = _mapping_error(prepared_registry, entry)
    if reason is not None:
        return None, unresolved_mapping(entry, reason)
    return entry, None


def cross_section_fields(mapping: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "status": "local_file_registered",
        "path": mapping["asset_path"],
        "source": mapping.get("source"),
        "mapping_status": mapping.get("mapping_status"),
        "process_label_original": mapping.get("process_label_original"),
    }
    return {key: value for key, value in fields.items() if value is not None}


def unresolved_mapping(mapping: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "reaction_id": mapping.get("reaction_id"),
        "asset_path": mapping.get("asset_path"),
        "reason": reason,
    }


def _mapping_error(prepared_registry: Path, mapping: dict[str, Any]) -> str | None:
    reaction_id = mapping.get("reaction_id")
    if not isinstance(reaction_id, str) or not reaction_id.strip():
        return "missing_reaction_id"

    asset_path = mapping.get("asset_path")
    if not isinstance(asset_path, str) or not asset_path.strip():
        return "missing_asset_path"
    if resolve_registry_asset(prepared_registry, asset_path) is None:
        return "asset_path_outside_registry"
    if not registry_asset_exists(prepared_registry, asset_path):
        return "asset_not_found"
    return None
