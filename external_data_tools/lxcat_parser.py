from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_COLUMNS = ("energy_eV", "cross_section_m2")
_OPTIONAL_METADATA_COLUMNS = ("process", "target", "reaction_id")


@dataclass
class ParsedCrossSection:
    rows: list[dict[str, float]]
    columns: list[str]
    process_label_original: str | None = None
    target: str | None = None
    reaction_id: str | None = None
    input_format: str = "unknown"


@dataclass
class _BolsigBlock:
    process_label: str | None = None
    target: str | None = None
    reaction_id: str | None = None
    rows: list[dict[str, float]] = field(default_factory=list)
    saw_numeric: bool = False
    labels_after_rows: int = 0

    def consume(self, line: str, line_number: int) -> None:
        numeric = _numeric_row_from_line(line)
        if numeric is not None:
            self.rows.append(numeric)
            self.saw_numeric = True
            return
        metadata = _metadata_line(line)
        if metadata is not None:
            self._apply_metadata(*metadata)
            return
        if _looks_like_header(line):
            return
        if self.saw_numeric:
            self.labels_after_rows += 1
        elif self.process_label is None:
            self.process_label = line
        else:
            raise ValueError(f"multiple process labels before numeric data near line {line_number}")

    def _apply_metadata(self, key: str, value: str) -> None:
        if key in {"process", "process_label"}:
            self.process_label = value
        elif key == "target":
            self.target = value
        elif key == "reaction_id":
            self.reaction_id = value


def parse_lxcat_raw_file(path: Path) -> ParsedCrossSection:
    path = Path(path)
    if path.suffix.lower() in {".csv", ".tsv", ".tab"}:
        return _parse_delimited_table(path)
    return _parse_minimal_bolsig_block(path)


def _parse_delimited_table(path: Path) -> ParsedCrossSection:
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        columns = list(reader.fieldnames or [])
        missing = [column for column in REQUIRED_COLUMNS if column not in columns]
        if missing:
            raise ValueError(f"missing required columns: {missing}")
        metadata_values: dict[str, set[str]] = {
            column: set() for column in _OPTIONAL_METADATA_COLUMNS if column in columns
        }
        rows = []
        for line_number, row in enumerate(reader, start=2):
            rows.append(_row_from_mapping(row, line_number=line_number))
            _collect_metadata(metadata_values, row)

    if len(rows) < 2:
        raise ValueError("cross-section table must contain at least two numeric rows")
    metadata = _constant_metadata(metadata_values)
    rows.sort(key=lambda item: item["energy_eV"])
    return ParsedCrossSection(
        rows=rows,
        columns=columns,
        process_label_original=metadata.get("process"),
        target=metadata.get("target"),
        reaction_id=metadata.get("reaction_id"),
        input_format="csv_tsv",
    )


def _collect_metadata(
    values: dict[str, set[str]],
    row: dict[str, Any],
) -> None:
    for column in values:
        value = str(row.get(column) or "").strip()
        if value:
            values[column].add(value)


def _constant_metadata(values: dict[str, set[str]]) -> dict[str, str]:
    metadata = {}
    for column, found in values.items():
        if len(found) > 1:
            raise ValueError(f"multiple {column} values are ambiguous: {sorted(found)}")
        if found:
            metadata[column] = next(iter(found))
    return metadata


def _parse_minimal_bolsig_block(path: Path) -> ParsedCrossSection:
    block = _BolsigBlock()
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if _is_ignorable(line):
            continue
        block.consume(line, line_number)
    _validate_bolsig_block(block)
    block.rows.sort(key=lambda item: item["energy_eV"])
    return ParsedCrossSection(
        rows=block.rows,
        columns=list(REQUIRED_COLUMNS),
        process_label_original=block.process_label,
        target=block.target,
        reaction_id=block.reaction_id,
        input_format="bolsig_lxcat_minimal",
    )


def _is_ignorable(line: str) -> bool:
    return not line or line.startswith(("#", "//")) or set(line) <= {"-", "="}


def _validate_bolsig_block(block: _BolsigBlock) -> None:
    if block.labels_after_rows:
        raise ValueError("multiple plain-text blocks are ambiguous")
    if not block.process_label:
        raise ValueError("plain-text block requires an unambiguous process label")
    if len(block.rows) < 2:
        raise ValueError("plain-text block must contain at least two numeric rows")


def _row_from_mapping(row: dict[str, Any], *, line_number: int) -> dict[str, float]:
    energy = _float_value(row.get("energy_eV"), "energy_eV", line_number)
    cross_section = _float_value(
        row.get("cross_section_m2"),
        "cross_section_m2",
        line_number,
    )
    if cross_section < 0:
        raise ValueError(f"cross_section_m2 must be non-negative on line {line_number}")
    return {"energy_eV": energy, "cross_section_m2": cross_section}


def _numeric_row_from_line(line: str) -> dict[str, float] | None:
    parts = [part for part in re.split(r"[\s,]+", line) if part]
    if len(parts) < 2:
        return None
    try:
        energy = float(parts[0])
        cross_section = float(parts[1])
    except ValueError:
        return None
    if cross_section < 0:
        raise ValueError("cross-section values must be non-negative")
    return {"energy_eV": energy, "cross_section_m2": cross_section}


def _metadata_line(line: str) -> tuple[str, str] | None:
    match = re.match(r"^([A-Za-z_][A-Za-z0-9_ -]*)\s*[:=]\s*(.+)$", line)
    if not match:
        return None
    key = match.group(1).strip().lower().replace(" ", "_").replace("-", "_")
    return key, match.group(2).strip()


def _looks_like_header(line: str) -> bool:
    lowered = line.lower()
    return "energy" in lowered and ("cross" in lowered or "sigma" in lowered)


def _float_value(value: Any, column: str, line_number: int) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{column} must be numeric on line {line_number}") from exc


__all__ = ["ParsedCrossSection", "parse_lxcat_raw_file"]
