from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.lxcat_assets import (
    asset_locations,
    asset_record,
    write_asset,
)
from external_data_tools.lxcat_manifest import (
    find_lxcat_mapping,
    load_lxcat_mappings,
    update_prepared_electron_channel,
)
from external_data_tools.lxcat_parser import ParsedCrossSection, parse_lxcat_raw_file


def import_lxcat_raw_file(
    raw_file: Path,
    *,
    workspace: Path,
    target: str,
    source: str = "lxcat_manual",
    mapping_file: Path = Path("external_data/lxcat/mappings.yaml"),
    reaction_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    raw_file = Path(raw_file)
    workspace = Path(workspace)
    report = _new_report(raw_file, workspace, dry_run)
    parsed = _parse(raw_file, report)
    if parsed is None:
        return _finalize(report)

    parsed_target = parsed.target or target
    if parsed.target and parsed.target != target:
        report["unresolved"].append(
            {
                "file": str(raw_file),
                "reason": "target_mismatch",
                "target": target,
                "parsed_target": parsed.target,
            }
        )
        return _finalize(report)

    mapping = find_lxcat_mapping(
        load_lxcat_mappings(mapping_file),
        target=parsed_target,
        process_label=parsed.process_label_original,
    )
    resolved_id = reaction_id or (mapping or {}).get("reaction_id") or parsed.reaction_id
    relative_path, asset_path, metadata_path = asset_locations(
        workspace / "prepared_registry",
        raw_file,
        parsed,
        parsed_target,
        resolved_id,
    )
    report["assets"].append(asset_record(relative_path, parsed, resolved_id, dry_run=dry_run))
    if not dry_run:
        write_asset(
            asset_path,
            metadata_path,
            raw_file=raw_file,
            parsed=parsed,
            source=source,
            target=parsed_target,
            reaction_id=resolved_id,
        )
    _record_mapping(
        report,
        workspace=workspace,
        target=parsed_target,
        parsed=parsed,
        relative_path=relative_path,
        reaction_id=resolved_id,
        mapping=mapping,
        explicit_reaction_id=reaction_id,
        source=source,
        dry_run=dry_run,
    )
    return _finalize(report)


def _parse(raw_file: Path, report: dict[str, Any]) -> ParsedCrossSection | None:
    try:
        return parse_lxcat_raw_file(raw_file)
    except ValueError as exc:
        report["unresolved"].append(
            {
                "file": str(raw_file),
                "reason": "ambiguous_or_unsupported_format",
                "message": str(exc),
            }
        )
        return None


def _record_mapping(
    report: dict[str, Any],
    *,
    workspace: Path,
    target: str,
    parsed: ParsedCrossSection,
    relative_path: str,
    reaction_id: str | None,
    mapping: dict[str, Any] | None,
    explicit_reaction_id: str | None,
    source: str,
    dry_run: bool,
) -> None:
    if reaction_id is None:
        report["unmapped"].append(
            {
                "target": target,
                "process_label_original": parsed.process_label_original,
                "asset_path": relative_path,
                "reason": "no_mapping_matched",
            }
        )
        return

    mapping_status = (mapping or {}).get("mapping_status") or (
        "provided" if explicit_reaction_id or parsed.reaction_id else None
    )
    if dry_run:
        report["mapped"].append(
            {
                "reaction_id": reaction_id,
                "asset_path": relative_path,
                "mapping_status": mapping_status,
                "dry_run": True,
            }
        )
        return
    updated = update_prepared_electron_channel(
        workspace / "prepared_registry",
        reaction_id=reaction_id,
        asset_path=relative_path,
        source=source,
        process_label_original=parsed.process_label_original,
        mapping_status=mapping_status,
    )
    if not updated:
        report["unresolved"].append(
            {
                "reaction_id": reaction_id,
                "asset_path": relative_path,
                "reason": "reaction_id_not_found",
            }
        )
        return
    report["mapped"].extend(
        {
            "reaction_id": reaction_id,
            "asset_path": relative_path,
            "file": str(path),
            "mapping_status": mapping_status,
        }
        for path in updated
    )


def _new_report(raw_file: Path, workspace: Path, dry_run: bool) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "input_file": str(raw_file),
        "workspace": str(workspace),
        "dry_run": dry_run,
        "assets": [],
        "mapped": [],
        "unmapped": [],
        "unresolved": [],
        "summary": {
            "n_assets_imported": 0,
            "n_mapped": 0,
            "n_unmapped": 0,
            "n_unresolved": 0,
        },
    }


def _finalize(report: dict[str, Any]) -> dict[str, Any]:
    report["summary"] = {
        "n_assets_imported": 0 if report["dry_run"] else len(report["assets"]),
        "n_mapped": len(report["mapped"]),
        "n_unmapped": len(report["unmapped"]),
        "n_unresolved": len(report["unresolved"]),
    }
    return report


__all__ = ["import_lxcat_raw_file"]
