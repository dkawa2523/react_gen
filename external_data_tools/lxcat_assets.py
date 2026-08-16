from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from external_data_tools.cache import safe_filename, sha256_file
from external_data_tools.lxcat_parser import REQUIRED_COLUMNS, ParsedCrossSection

LICENSE_NOTE = "User must follow LXCat citation and redistribution requirements."


def asset_locations(
    prepared_registry: Path,
    raw_file: Path,
    parsed: ParsedCrossSection,
    target: str,
    reaction_id: str | None,
) -> tuple[str, Path, Path]:
    name = _asset_name(raw_file, parsed, target, reaction_id)
    relative_path = f"assets/cross_sections/{name}.csv"
    asset_path = prepared_registry / relative_path
    return relative_path, asset_path, asset_path.with_suffix(".metadata.yaml")


def write_asset(
    asset_path: Path,
    metadata_path: Path,
    *,
    raw_file: Path,
    parsed: ParsedCrossSection,
    source: str,
    target: str,
    reaction_id: str | None,
) -> None:
    _write_normalized_csv(asset_path, parsed.rows)
    metadata = {
        "original_file": str(raw_file),
        "sha256": sha256_file(raw_file),
        "imported_at": datetime.now(UTC).isoformat(),
        "source": source,
        "target": target,
        "process_label_original": parsed.process_label_original,
        "reaction_id": reaction_id,
        "input_format": parsed.input_format,
        "units": {"energy": "eV", "cross_section": "m2"},
        "row_count": len(parsed.rows),
        "energy_min_eV": parsed.rows[0]["energy_eV"],
        "energy_max_eV": parsed.rows[-1]["energy_eV"],
        "license_note": LICENSE_NOTE,
    }
    metadata_path.write_text(
        yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def asset_record(
    relative_path: str,
    parsed: ParsedCrossSection,
    reaction_id: str | None,
    *,
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "asset_path": relative_path,
        "metadata_path": str(Path(relative_path).with_suffix(".metadata.yaml")).replace(
            "\\",
            "/",
        ),
        "row_count": len(parsed.rows),
        "process_label_original": parsed.process_label_original,
        "reaction_id": reaction_id,
        "dry_run": dry_run,
    }


def _asset_name(
    raw_file: Path,
    parsed: ParsedCrossSection,
    target: str,
    reaction_id: str | None,
) -> str:
    base = reaction_id or parsed.process_label_original or target or raw_file.stem
    return f"{safe_filename(base)}_{sha256_file(raw_file)[:12]}"


def _write_normalized_csv(path: Path, rows: list[dict[str, float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REQUIRED_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


__all__ = ["asset_locations", "asset_record", "write_asset"]
