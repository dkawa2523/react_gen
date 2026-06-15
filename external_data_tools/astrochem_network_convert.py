from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re

import yaml

from .cache import safe_filename


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
            reaction = _convert_row(row, database=database, line_number=index)
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


def _convert_row(row: dict[str, str], *, database: str, line_number: int) -> dict[str, Any] | None:
    reactant1 = _normalize_species(row.get("reactant1", ""))
    reactant2 = _normalize_species(row.get("reactant2", ""))
    if reactant1 is None or reactant2 is None:
        raise ValueError("reactant notation could not be normalized")

    charge1 = _charge(reactant1)
    charge2 = _charge(reactant2)
    if (charge1 != 0 and charge2 != 0) or (charge1 == 0 and charge2 == 0):
        return None

    projectile = reactant1 if charge1 != 0 else reactant2
    target = reactant2 if charge1 != 0 else reactant1
    products = _products(row)
    if products is None:
        raise ValueError("product notation could not be normalized")

    reaction_id = _reaction_id(database, projectile, target, products, line_number)
    reaction = {
        "id": reaction_id,
        "projectile": projectile,
        "target": target,
        "family": "ion_neutral",
        "type": "reactive_scattering",
        "products": [{"species": product, "n": 1} for product in products],
        "status": "imported",
        "data": {
            "rate_form": {
                "alpha": _float_or_none(row.get("alpha")),
                "beta": _float_or_none(row.get("beta")),
                "gamma": _float_or_none(row.get("gamma")),
                "temperature_min_K": _float_or_none(row.get("temperature_min_K")),
                "temperature_max_K": _float_or_none(row.get("temperature_max_K")),
            },
            "provenance": {
                "database": database,
                "original_source": row.get("source"),
                "reference": row.get("reference"),
            },
            "review_status": "astrochem_candidate_not_semiconductor_validated",
        },
        "source_record": {
            "source_type": "local_snapshot",
            "database": database,
            "source_id": row.get("source") or reaction_id,
            "citation": row.get("reference"),
            "review_required": True,
        },
    }
    dnt_class = _dnt_class_if_simple_charge_transfer(projectile, target, products)
    if dnt_class:
        reaction["dnt_class"] = dnt_class
    return reaction


def _products(row: dict[str, str]) -> list[str] | None:
    products = []
    for key in ("product1", "product2", "product3"):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        product = _normalize_species(raw)
        if product is None:
            return None
        products.append(product)
    return products


def _normalize_species(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if any(token in text for token in (" ", "/", "?", "*")):
        return None
    text = text.replace("(+)", "+").replace("(-)", "-")
    if text.endswith("+") or text.endswith("-"):
        return text
    if text.endswith("_p"):
        return f"{text[:-2]}+"
    if text.endswith("_m"):
        return f"{text[:-2]}-"

    match = re.match(r"^(.+?)([+-])(\d*)$", text)
    if match:
        base, sign, magnitude = match.groups()
        if magnitude in {"", "1"}:
            return f"{base}{sign}"
        return None
    return text


def _charge(species: str) -> int:
    if species.endswith("+"):
        return 1
    if species.endswith("-"):
        return -1
    return 0


def _dnt_class_if_simple_charge_transfer(
    projectile: str,
    target: str,
    products: list[str],
) -> str | None:
    if len(products) != 2:
        return None
    neutral_projectile = projectile.rstrip("+-")
    charged_target = f"{target}{projectile[-1]}" if projectile.endswith(("+", "-")) else target
    if neutral_projectile in products and charged_target in products:
        return "long_range_charge_exchange"
    return None


def _reaction_id(database: str, projectile: str, target: str, products: list[str], line_number: int) -> str:
    pieces = [database.lower(), projectile, target, *products, str(line_number)]
    return "_".join(safe_filename(piece) for piece in pieces if piece)


def _float_or_none(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return float(text)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
