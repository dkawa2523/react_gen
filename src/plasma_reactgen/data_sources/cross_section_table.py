from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.data_sources.cache import record_source_file
from plasma_reactgen.domain.identifiers import to_file_key

REQUIRED_COLUMNS = ("energy_eV", "cross_section_m2")


@dataclass
class CrossSectionImportResult:
    asset_path: Path
    metadata_path: Path
    relative_asset_path: str
    row_count: int
    linked_reaction_files: list[Path]
    source_cache_record: dict[str, Any] | None = None


def import_cross_section_table(
    input_file: str | Path,
    workspace: str | Path,
    *,
    source: str = "local_file",
    reaction_id: str | None = None,
    target: str | None = None,
    license_note: str | None = None,
) -> CrossSectionImportResult:
    input_path = Path(input_file)
    workspace = Path(workspace)
    rows, columns = read_cross_section_table(input_path)
    safe_name = _safe_table_name(input_path, rows, reaction_id, target)
    cache_record = record_source_file(
        workspace / "source_cache",
        source,
        input_path,
    )

    output_dir = workspace / "prepared_registry" / "assets" / "cross_sections"
    asset_path = output_dir / f"{safe_name}.csv"
    metadata_path = output_dir / f"{safe_name}.metadata.yaml"
    relative_asset_path = f"assets/cross_sections/{safe_name}.csv"
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_normalized_csv(asset_path, rows)
    _write_metadata(
        metadata_path,
        input_path=input_path,
        rows=rows,
        columns=columns,
        source=source,
        license_note=license_note,
        cache_record=cache_record,
    )
    linked = []
    if reaction_id:
        linked = link_prepared_reaction_channel(
            workspace / "prepared_registry",
            reaction_id=reaction_id,
            relative_asset_path=relative_asset_path,
            source=source,
        )

    return CrossSectionImportResult(
        asset_path=asset_path,
        metadata_path=metadata_path,
        relative_asset_path=relative_asset_path,
        row_count=len(rows),
        linked_reaction_files=linked,
        source_cache_record=cache_record,
    )


def read_cross_section_table(input_file: str | Path) -> tuple[list[dict[str, float]], list[str]]:
    input_path = Path(input_file)
    delimiter = "\t" if input_path.suffix.lower() in {".tsv", ".tab"} else ","
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        columns = list(reader.fieldnames or [])
        _validate_columns(columns, input_path)
        rows = [_normalized_row(row, line_number=index + 2) for index, row in enumerate(reader)]

    if len(rows) < 2:
        raise ValueError("cross-section table must contain at least two data rows")
    rows.sort(key=lambda item: item["energy_eV"])
    return rows, columns


def link_prepared_reaction_channel(
    prepared_registry: str | Path,
    *,
    reaction_id: str,
    relative_asset_path: str,
    source: str,
) -> list[Path]:
    prepared_registry = Path(prepared_registry)
    reaction_root = prepared_registry / "reactions"
    if not reaction_root.exists():
        return []

    updated: list[Path] = []
    for path in sorted(reaction_root.glob("*/*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        changed = False
        for channel in payload.get("channels", []):
            if not isinstance(channel, dict) or channel.get("id") != reaction_id:
                continue
            channel.setdefault("data", {})["cross_section"] = {
                "status": "local_file_registered",
                "path": relative_asset_path,
                "format": "csv_energy_eV_sigma_m2",
                "source": source,
            }
            changed = True
        if changed:
            path.write_text(
                yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            updated.append(path)
    return updated


def _validate_columns(columns: list[str], input_path: Path) -> None:
    missing = [name for name in REQUIRED_COLUMNS if name not in columns]
    if missing:
        raise ValueError(f"cross-section table missing required columns {missing}: {input_path}")


def _normalized_row(row: dict[str, Any], *, line_number: int) -> dict[str, float]:
    energy = _float_value(row.get("energy_eV"), "energy_eV", line_number)
    sigma = _float_value(row.get("cross_section_m2"), "cross_section_m2", line_number)
    if sigma < 0:
        raise ValueError(f"cross_section_m2 must be non-negative on line {line_number}")
    return {
        "energy_eV": energy,
        "cross_section_m2": sigma,
    }


def _float_value(value: Any, column: str, line_number: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{column} must be numeric on line {line_number}") from exc


def _write_normalized_csv(path: Path, rows: list[dict[str, float]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(REQUIRED_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_metadata(
    path: Path,
    *,
    input_path: Path,
    rows: list[dict[str, float]],
    columns: list[str],
    source: str,
    license_note: str | None,
    cache_record: dict[str, Any] | None = None,
) -> None:
    metadata = {
        "source_type": "public_database_snapshot" if source == "lxcat_offline" else "local_file",
        "database": "LXCat" if source == "lxcat_offline" else "user_provided",
        "original_file": str(input_path),
        "imported_at": datetime.now(UTC).isoformat(),
        "columns": columns,
        "units": {
            "energy": "eV",
            "cross_section": "m2",
        },
        "row_count": len(rows),
        "energy_min_eV": rows[0]["energy_eV"],
        "energy_max_eV": rows[-1]["energy_eV"],
        "sha256": _sha256(input_path),
        "license_note": license_note
        or "User is responsible for source licensing, attribution, and redistribution permissions.",
    }
    if cache_record is not None:
        metadata["source_cache"] = cache_record
    path.write_text(
        yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _safe_table_name(
    input_path: Path,
    rows: list[dict[str, float]],
    reaction_id: str | None,
    target: str | None,
) -> str:
    base = reaction_id or target or input_path.stem
    digest = _sha256(input_path)[:10]
    return f"{to_file_key(base)}_{digest}"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
