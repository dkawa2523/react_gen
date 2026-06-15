from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

import yaml

from .cache import safe_filename, sha256_file
from .lxcat_manifest import (
    find_lxcat_mapping,
    load_lxcat_mappings,
    update_prepared_electron_channel,
)


LICENSE_NOTE = "User must follow LXCat citation and redistribution requirements."
REQUIRED_COLUMNS = ("energy_eV", "cross_section_m2")


@dataclass
class ParsedCrossSection:
    rows: list[dict[str, float]]
    columns: list[str]
    process_label_original: str | None = None
    target: str | None = None
    reaction_id: str | None = None
    input_format: str = "unknown"


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
    prepared_registry = workspace / "prepared_registry"
    report: dict[str, Any] = {
        "schema_version": 1,
        "input_file": str(raw_file),
        "workspace": str(workspace),
        "dry_run": bool(dry_run),
        "registry_mutated": False,
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

    try:
        parsed = parse_lxcat_raw_file(raw_file)
    except ValueError as exc:
        report["unresolved"].append(
            {
                "file": str(raw_file),
                "reason": "ambiguous_or_unsupported_format",
                "message": str(exc),
            }
        )
        _finalize_summary(report)
        return report

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
        _finalize_summary(report)
        return report

    mappings = load_lxcat_mappings(mapping_file)
    mapping = find_lxcat_mapping(
        mappings,
        target=parsed_target,
        process_label=parsed.process_label_original,
    )
    resolved_reaction_id = (
        reaction_id
        or (mapping or {}).get("reaction_id")
        or parsed.reaction_id
    )
    safe_name = _asset_name(raw_file, parsed, parsed_target, resolved_reaction_id)
    relative_asset_path = f"assets/cross_sections/{safe_name}.csv"
    asset_path = prepared_registry / relative_asset_path
    metadata_path = asset_path.with_suffix(".metadata.yaml")

    asset_record = {
        "asset_path": relative_asset_path,
        "metadata_path": f"assets/cross_sections/{safe_name}.metadata.yaml",
        "row_count": len(parsed.rows),
        "process_label_original": parsed.process_label_original,
        "reaction_id": resolved_reaction_id,
        "dry_run": bool(dry_run),
    }
    report["assets"].append(asset_record)

    if not dry_run:
        _write_normalized_csv(asset_path, parsed.rows)
        _write_metadata(
            metadata_path,
            raw_file=raw_file,
            parsed=parsed,
            source=source,
            target=parsed_target,
            reaction_id=resolved_reaction_id,
        )

    if resolved_reaction_id:
        mapping_status = (mapping or {}).get("mapping_status") or (
            "provided" if reaction_id or parsed.reaction_id else None
        )
        if dry_run:
            report["mapped"].append(
                {
                    "reaction_id": resolved_reaction_id,
                    "asset_path": relative_asset_path,
                    "mapping_status": mapping_status,
                    "dry_run": True,
                }
            )
        else:
            updated = update_prepared_electron_channel(
                prepared_registry,
                reaction_id=resolved_reaction_id,
                asset_path=relative_asset_path,
                source=source,
                process_label_original=parsed.process_label_original,
                mapping_status=mapping_status,
            )
            if updated:
                for path in updated:
                    report["mapped"].append(
                        {
                            "reaction_id": resolved_reaction_id,
                            "asset_path": relative_asset_path,
                            "file": str(path),
                            "mapping_status": mapping_status,
                        }
                    )
            else:
                report["unresolved"].append(
                    {
                        "reaction_id": resolved_reaction_id,
                        "asset_path": relative_asset_path,
                        "reason": "reaction_id_not_found",
                    }
                )
    else:
        report["unmapped"].append(
            {
                "target": parsed_target,
                "process_label_original": parsed.process_label_original,
                "asset_path": relative_asset_path,
                "reason": "no_mapping_matched",
            }
        )

    _finalize_summary(report)
    return report


def parse_lxcat_raw_file(path: Path) -> ParsedCrossSection:
    path = Path(path)
    if path.suffix.lower() in {".csv", ".tsv", ".tab"}:
        return _parse_delimited_table(path)
    return _parse_minimal_bolsig_block(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Normalize manually downloaded LXCat/BOLSIG-style raw files."
    )
    parser.add_argument("raw_file", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--source", default="lxcat_manual")
    parser.add_argument("--mapping-file", type=Path, default=Path("external_data/lxcat/mappings.yaml"))
    parser.add_argument("--reaction-id")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    report = import_lxcat_raw_file(
        args.raw_file,
        workspace=args.workspace,
        target=args.target,
        source=args.source,
        mapping_file=args.mapping_file,
        reaction_id=args.reaction_id,
        dry_run=args.dry_run,
    )
    report_path = args.workspace / "lxcat_import_report.yaml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    print(
        "lxcat raw import: "
        f"assets={report['summary']['n_assets_imported']} "
        f"mapped={report['summary']['n_mapped']} "
        f"unresolved={report['summary']['n_unresolved']} "
        f"report={report_path}"
    )
    return 1 if report["summary"]["n_unresolved"] else 0


def _parse_delimited_table(path: Path) -> ParsedCrossSection:
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        columns = list(reader.fieldnames or [])
        missing = [column for column in REQUIRED_COLUMNS if column not in columns]
        if missing:
            raise ValueError(f"missing required columns: {missing}")
        rows = [_row_from_mapping(row, line_number=index + 2) for index, row in enumerate(reader)]

    if len(rows) < 2:
        raise ValueError("cross-section table must contain at least two numeric rows")

    metadata = _constant_optional_metadata(path, delimiter, columns)
    rows.sort(key=lambda item: item["energy_eV"])
    return ParsedCrossSection(
        rows=rows,
        columns=columns,
        process_label_original=metadata.get("process"),
        target=metadata.get("target"),
        reaction_id=metadata.get("reaction_id"),
        input_format="csv_tsv",
    )


def _constant_optional_metadata(path: Path, delimiter: str, columns: list[str]) -> dict[str, str]:
    optional = [column for column in ("process", "target", "reaction_id") if column in columns]
    if not optional:
        return {}
    values: dict[str, set[str]] = {column: set() for column in optional}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=delimiter):
            for column in optional:
                value = str(row.get(column) or "").strip()
                if value:
                    values[column].add(value)
    metadata = {}
    for column, found in values.items():
        if len(found) > 1:
            raise ValueError(f"multiple {column} values are ambiguous: {sorted(found)}")
        if found:
            metadata[column] = next(iter(found))
    return metadata


def _parse_minimal_bolsig_block(path: Path) -> ParsedCrossSection:
    process_label: str | None = None
    target: str | None = None
    reaction_id: str | None = None
    rows: list[dict[str, float]] = []
    saw_numeric = False
    labels_after_rows = 0

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "//")) or set(line) <= {"-", "="}:
            continue
        numeric = _numeric_row_from_line(line)
        if numeric is not None:
            rows.append(numeric)
            saw_numeric = True
            continue
        metadata = _metadata_line(line)
        if metadata is not None:
            key, value = metadata
            if key in {"process", "process_label"}:
                process_label = value
            elif key == "target":
                target = value
            elif key == "reaction_id":
                reaction_id = value
            continue
        if _looks_like_header(line):
            continue
        if saw_numeric:
            labels_after_rows += 1
            continue
        if process_label is None:
            process_label = line
        else:
            raise ValueError(f"multiple process labels before numeric data near line {line_number}")

    if labels_after_rows:
        raise ValueError("multiple plain-text blocks are ambiguous")
    if not process_label:
        raise ValueError("plain-text block requires an unambiguous process label")
    if len(rows) < 2:
        raise ValueError("plain-text block must contain at least two numeric rows")
    rows.sort(key=lambda item: item["energy_eV"])
    return ParsedCrossSection(
        rows=rows,
        columns=["energy_eV", "cross_section_m2"],
        process_label_original=process_label,
        target=target,
        reaction_id=reaction_id,
        input_format="bolsig_lxcat_minimal",
    )


def _row_from_mapping(row: dict[str, Any], *, line_number: int) -> dict[str, float]:
    energy = _float_value(row.get("energy_eV"), "energy_eV", line_number)
    sigma = _float_value(row.get("cross_section_m2"), "cross_section_m2", line_number)
    if sigma < 0:
        raise ValueError(f"cross_section_m2 must be non-negative on line {line_number}")
    return {"energy_eV": energy, "cross_section_m2": sigma}


def _numeric_row_from_line(line: str) -> dict[str, float] | None:
    parts = [part for part in re.split(r"[\s,]+", line) if part]
    if len(parts) < 2:
        return None
    try:
        energy = float(parts[0])
        sigma = float(parts[1])
    except ValueError:
        return None
    if sigma < 0:
        raise ValueError("cross-section values must be non-negative")
    return {"energy_eV": energy, "cross_section_m2": sigma}


def _metadata_line(line: str) -> tuple[str, str] | None:
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_ -]*)\s*[:=]\s*(.+)$", line)
    if not match:
        return None
    key = match.group(1).strip().lower().replace(" ", "_").replace("-", "_")
    value = match.group(2).strip()
    return key, value


def _looks_like_header(line: str) -> bool:
    lowered = line.lower()
    return "energy" in lowered and ("cross" in lowered or "sigma" in lowered)


def _float_value(value: Any, column: str, line_number: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{column} must be numeric on line {line_number}") from exc


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
        for row in rows:
            writer.writerow(row)


def _write_metadata(
    path: Path,
    *,
    raw_file: Path,
    parsed: ParsedCrossSection,
    source: str,
    target: str,
    reaction_id: str | None,
) -> None:
    metadata = {
        "original_file": str(raw_file),
        "sha256": sha256_file(raw_file),
        "imported_at": datetime.now(timezone.utc).isoformat(),
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
    path.write_text(
        yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _finalize_summary(report: dict[str, Any]) -> None:
    report["summary"]["n_assets_imported"] = 0 if report["dry_run"] else len(report["assets"])
    report["summary"]["n_mapped"] = len(report["mapped"])
    report["summary"]["n_unmapped"] = len(report["unmapped"])
    report["summary"]["n_unresolved"] = len(report["unresolved"])


if __name__ == "__main__":
    raise SystemExit(main())
