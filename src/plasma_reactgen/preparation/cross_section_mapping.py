from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.infrastructure.registry_paths import (
    registry_asset_exists,
    resolve_registry_asset,
)


def apply_cross_section_mappings(prepared_registry: Path, mapping_file: Path) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    mapping_file = Path(mapping_file)
    payload = yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
    mappings = payload.get("mappings", [])
    if not isinstance(mappings, list):
        raise ValueError("cross-section mapping file must contain a 'mappings' list")

    report: dict[str, Any] = {
        "schema_version": 1,
        "mapping_file": str(mapping_file),
        "prepared_registry": str(prepared_registry),
        "updated": [],
        "unresolved": [],
        "summary": {
            "n_mappings": len(mappings),
            "n_updated": 0,
            "n_unresolved": 0,
        },
        "registry_mutated": False,
        "prepared_registry_mutated": False,
    }

    for mapping_index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            report["unresolved"].append(
                {
                    "mapping_index": mapping_index,
                    "reaction_id": None,
                    "asset_path": None,
                    "reason": "invalid_mapping_entry",
                }
            )
            continue
        reaction_id = mapping.get("reaction_id")
        asset_path = mapping.get("asset_path")
        if not isinstance(reaction_id, str) or not reaction_id.strip():
            _add_unresolved(report, mapping, "missing_reaction_id")
            continue
        if not isinstance(asset_path, str) or not asset_path.strip():
            _add_unresolved(report, mapping, "missing_asset_path")
            continue
        if resolve_registry_asset(prepared_registry, asset_path) is None:
            _add_unresolved(report, mapping, "asset_path_outside_registry")
            continue
        if not registry_asset_exists(prepared_registry, asset_path):
            _add_unresolved(report, mapping, "asset_not_found")
            continue

        updated_files = _apply_one_mapping(prepared_registry, mapping)
        if not updated_files:
            _add_unresolved(report, mapping, "reaction_id_not_found")
            continue

        for path in updated_files:
            report["updated"].append(
                {
                    "reaction_id": reaction_id,
                    "asset_path": asset_path,
                    "file": str(path),
                }
            )
        report["summary"]["n_updated"] += len(updated_files)

    report["summary"]["n_unresolved"] = len(report["unresolved"])
    report["prepared_registry_mutated"] = bool(report["updated"])
    return report


def _apply_one_mapping(prepared_registry: Path, mapping: dict[str, Any]) -> list[Path]:
    reaction_id = mapping["reaction_id"]
    updated: list[Path] = []
    reaction_root = prepared_registry / "reactions" / "electron"
    if not reaction_root.exists():
        return []

    for path in sorted(reaction_root.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        changed = False
        for channel in payload.get("channels", []):
            if not isinstance(channel, dict) or channel.get("id") != reaction_id:
                continue
            cross_section = channel.setdefault("data", {}).setdefault("cross_section", {})
            if not isinstance(cross_section, dict):
                channel["data"]["cross_section"] = {}
                cross_section = channel["data"]["cross_section"]
            cross_section.update(_cross_section_fields(mapping))
            changed = True
        if changed:
            path.write_text(
                yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            updated.append(path)
    return updated


def _cross_section_fields(mapping: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "status": "local_file_registered",
        "path": mapping["asset_path"],
        "source": mapping.get("source"),
        "mapping_status": mapping.get("mapping_status"),
        "process_label_original": mapping.get("process_label_original"),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _add_unresolved(report: dict[str, Any], mapping: dict[str, Any], reason: str) -> None:
    report["unresolved"].append(
        {
            "reaction_id": mapping.get("reaction_id"),
            "asset_path": mapping.get("asset_path"),
            "reason": reason,
        }
    )
