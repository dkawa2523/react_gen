from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from plasma_reactgen.preparation.cross_section_mapping_rules import (
    cross_section_fields,
    unresolved_mapping,
    validate_mapping_entry,
)
from plasma_reactgen.preparation.prepared_cross_sections import (
    apply_cross_section_to_reactions,
)


def apply_cross_section_mappings(
    prepared_registry: Path,
    mapping_file: Path,
) -> dict[str, Any]:
    prepared_registry = Path(prepared_registry)
    mapping_file = Path(mapping_file)
    mappings = _load_mappings(mapping_file)
    report = _empty_report(prepared_registry, mapping_file, len(mappings))

    for mapping_index, entry in enumerate(mappings):
        mapping, issue = validate_mapping_entry(prepared_registry, entry, mapping_index)
        if issue is not None:
            report["unresolved"].append(issue)
            continue

        mapping = cast(dict[str, Any], mapping)
        updated_files = apply_cross_section_to_reactions(
            prepared_registry,
            mapping["reaction_id"],
            cross_section_fields(mapping),
        )
        if not updated_files:
            report["unresolved"].append(unresolved_mapping(mapping, "reaction_id_not_found"))
            continue
        _record_updates(report, mapping, updated_files)

    _finalize_report(report)
    return report


def _load_mappings(mapping_file: Path) -> list[Any]:
    payload = yaml.safe_load(mapping_file.read_text(encoding="utf-8")) or {}
    mappings = payload.get("mappings", [])
    if not isinstance(mappings, list):
        raise ValueError("cross-section mapping file must contain a 'mappings' list")
    return mappings


def _empty_report(
    prepared_registry: Path,
    mapping_file: Path,
    mapping_count: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "mapping_file": str(mapping_file),
        "prepared_registry": str(prepared_registry),
        "updated": [],
        "unresolved": [],
        "summary": {
            "n_mappings": mapping_count,
            "n_updated": 0,
            "n_unresolved": 0,
        },
        "prepared_registry_mutated": False,
    }


def _record_updates(
    report: dict[str, Any],
    mapping: dict[str, Any],
    updated_files: list[Path],
) -> None:
    report["updated"].extend(
        {
            "reaction_id": mapping["reaction_id"],
            "asset_path": mapping["asset_path"],
            "file": str(path),
        }
        for path in updated_files
    )


def _finalize_report(report: dict[str, Any]) -> None:
    report["summary"]["n_updated"] = len(report["updated"])
    report["summary"]["n_unresolved"] = len(report["unresolved"])
    report["prepared_registry_mutated"] = bool(report["updated"])
