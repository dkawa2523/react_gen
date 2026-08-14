from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .astrochem_reaction import convert_reaction_row

REQUIRED_COLUMNS = (
    "reactant1",
    "reactant2",
    "product1",
    "product2",
    "product3",
    "alpha",
    "beta",
    "gamma",
    "temperature_min_K",
    "temperature_max_K",
    "source",
    "reference",
)


def convert_astrochem_network(
    input_file: Path,
    *,
    database: str,
    output: Path,
) -> dict[str, Any]:
    input_file = Path(input_file)
    output = Path(output)
    rows = _read_rows(input_file)
    converted = []
    skipped = []
    unresolved = []

    for index, row in enumerate(rows, start=2):
        try:
            reaction = convert_reaction_row(row, database=database, line_number=index)
        except ValueError as exc:
            unresolved.append(
                {
                    "line": index,
                    "reason": "invalid_notation",
                    "message": str(exc),
                    "reactants": [row.get("reactant1"), row.get("reactant2")],
                }
            )
            continue
        if reaction is None:
            skipped.append(
                {
                    "line": index,
                    "reason": "not_ion_neutral",
                    "reactants": [row.get("reactant1"), row.get("reactant2")],
                }
            )
            continue
        converted.append(reaction)

    payload = {
        "schema_version": 1,
        "source": {
            "source_type": "local_snapshot",
            "database": database,
            "review_required": True,
            "generated_at": _utc_now(),
        },
        "reactions": converted,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    report = {
        "schema_version": 1,
        "input_file": str(input_file),
        "output": str(output),
        "database": database,
        "total_rows": len(rows),
        "ion_neutral_rows": len(converted) + len(unresolved),
        "converted": len(converted),
        "skipped": len(skipped),
        "unresolved": unresolved,
        "skipped_rows": skipped,
    }
    report_path = output.with_suffix(".conversion_report.yaml")
    report_path.write_text(
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert local KIDA/UMIST-like CSV/TSV networks to ion reaction table YAML."
    )
    parser.add_argument("network", type=Path)
    parser.add_argument("--database", required=True, choices=["KIDA", "UMIST"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    report = convert_astrochem_network(args.network, database=args.database, output=args.output)
    print(
        "astrochem network convert: "
        f"total_rows={report['total_rows']} "
        f"converted={report['converted']} "
        f"skipped={report['skipped']} "
        f"unresolved={len(report['unresolved'])} "
        f"output={args.output}"
    )
    return 1 if report["unresolved"] else 0


def _read_rows(path: Path) -> list[dict[str, str]]:
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        columns = list(reader.fieldnames or [])
        missing = [column for column in REQUIRED_COLUMNS if column not in columns]
        if missing:
            raise ValueError(f"astrochemical network missing required columns: {missing}")
        return [dict(row) for row in reader]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
