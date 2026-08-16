from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .astrochem_reaction import convert_reaction_row, reaction_pair_key
from .umist_rate22 import read_umist_rate22

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
    target_manifest: Path | None = None,
) -> dict[str, Any]:
    input_file = Path(input_file)
    output = Path(output)
    rows = _read_rows(input_file, database)
    target_pair_keys = _target_pair_keys(target_manifest)
    converted = []
    rate_candidates = []
    skipped = []
    unresolved = []
    filtered_out = 0

    for index, row in enumerate(rows, start=2):
        if target_pair_keys is not None and reaction_pair_key(row) not in target_pair_keys:
            filtered_out += 1
            continue
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
                    "reason": "unsupported_same_sign_ion_pair",
                    "reactants": [row.get("reactant1"), row.get("reactant2")],
                }
            )
            continue
        converted.append(reaction)
        rate_candidates.append(_rate_candidate(reaction))

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
    rate_output = output.with_suffix(".rate_candidates.yaml")
    rate_output.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "source": {
                    "database": database,
                    "review_required": True,
                    "applicability": "astrochemical_candidate_not_semiconductor_validated",
                },
                "records": rate_candidates,
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    family_counts = Counter(reaction["family"] for reaction in converted)

    report = {
        "schema_version": 1,
        "input_file": str(input_file),
        "output": str(output),
        "database": database,
        "total_rows": len(rows),
        "selected_rows": len(rows) - filtered_out,
        "filtered_out": filtered_out,
        "ion_neutral_rows": family_counts["ion_neutral"],
        "converted": len(converted),
        "converted_by_family": dict(sorted(family_counts.items())),
        "rate_candidates_output": str(rate_output),
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


def _rate_candidate(reaction: dict[str, Any]) -> dict[str, Any]:
    rate = reaction["data"]["rate_form"]
    reactants = [reaction["projectile"], reaction["target"]]
    products = [item["species"] for item in reaction["products"]]
    return {
        "equation": f"{' + '.join(reactants)} -> {' + '.join(products)}",
        "representation": "arrhenius",
        "unit": "cm3/s",
        "parameters": {
            "alpha": rate["alpha"],
            "beta": rate["beta"],
            "gamma_K": rate["gamma"],
            "form": "alpha*(T/300 K)^beta*exp(-gamma_K/T)",
        },
        "temperature_min_K": rate["temperature_min_K"],
        "temperature_max_K": rate["temperature_max_K"],
        "source": reaction["source_record"]["database"],
        "citation": reaction["source_record"]["citation"],
        "redistribution_status": "site-local",
        "review_required": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert local KIDA/UMIST-like CSV/TSV networks to reviewed reaction "
            "and rate-candidate YAML."
        )
    )
    parser.add_argument("network", type=Path)
    parser.add_argument("--database", required=True, choices=["KIDA", "UMIST"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--target-manifest",
        type=Path,
        help="Only convert pair keys listed in an acquisition target manifest.",
    )
    args = parser.parse_args(argv)

    report = convert_astrochem_network(
        args.network,
        database=args.database,
        output=args.output,
        target_manifest=args.target_manifest,
    )
    print(
        "astrochem network convert: "
        f"total_rows={report['total_rows']} "
        f"converted={report['converted']} "
        f"skipped={report['skipped']} "
        f"unresolved={len(report['unresolved'])} "
        f"output={args.output}"
    )
    return 1 if report["unresolved"] else 0


def _read_rows(path: Path, database: str) -> list[dict[str, str]]:
    if path.suffix.lower() == ".rates":
        if database != "UMIST":
            raise ValueError("native .rates input is supported only for UMIST")
        return read_umist_rate22(path)
    delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        columns = list(reader.fieldnames or [])
        missing = [column for column in REQUIRED_COLUMNS if column not in columns]
        if missing:
            raise ValueError(f"astrochemical network missing required columns: {missing}")
        return [dict(row) for row in reader]


def _target_pair_keys(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    targets = payload.get("targets", []) if isinstance(payload, dict) else []
    return {
        str(target["pair_key"])
        for target in targets
        if isinstance(target, dict) and target.get("pair_key")
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
