from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

SUPPORTED_UNITS = {"eV", "amu", "D", "A3"}
REQUIRED_RECORD_KEYS = {
    "species",
    "property",
    "value",
    "unit",
    "status",
    "evidence_type",
    "source_record",
}
REQUIRED_SOURCE_RECORD_KEYS = {
    "source_type",
    "database",
    "source_id",
    "citation",
    "accessed_date",
}


def validate_nist_snapshot(path: Path) -> dict[str, Any]:
    payload = _read_yaml(path)
    records = payload.get("records", [])
    if not isinstance(records, list):
        raise ValueError("NIST snapshot must contain a records list")

    errors: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(_error(index, None, "record_not_mapping", "record must be a mapping"))
            continue
        errors.extend(_validate_record(index, record))

    return {
        "schema_version": 1,
        "valid": not errors,
        "summary": {
            "records": len(records),
            "errors": len(errors),
        },
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a manually prepared local NIST snapshot YAML file."
    )
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args(argv)

    report = validate_nist_snapshot(args.snapshot)
    print(
        "nist snapshot validate: "
        f"valid={report['valid']} "
        f"records={report['summary']['records']} "
        f"errors={report['summary']['errors']}"
    )
    return 0 if report["valid"] else 1


def _validate_record(index: int, record: dict[str, Any]) -> list[dict[str, Any]]:
    species = record.get("species")
    return [
        *_missing_record_key_errors(index, species, record),
        *_value_errors(index, species, record),
        *_source_record_errors(index, species, record.get("source_record")),
    ]


def _missing_record_key_errors(
    index: int,
    species: Any,
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        _error(index, species, "missing_key", f"missing required key: {key}", key)
        for key in sorted(REQUIRED_RECORD_KEYS - record.keys())
    ]


def _value_errors(
    index: int,
    species: Any,
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    errors = []

    unit = record.get("unit")
    if unit is not None and unit not in SUPPORTED_UNITS:
        errors.append(
            _error(index, species, "unsupported_unit", f"unsupported unit: {unit}", "unit")
        )

    value = record.get("value")
    if value is not None and not isinstance(value, int | float):
        errors.append(_error(index, species, "non_numeric_value", "value must be numeric", "value"))
    return errors


def _source_record_errors(
    index: int,
    species: Any,
    source_record: Any,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if source_record is not None and not isinstance(source_record, dict):
        return [
            _error(
                index,
                species,
                "invalid_source_record",
                "source_record must be a mapping",
                "source_record",
            )
        ]

    if isinstance(source_record, dict):
        errors.extend(
            _error(index, species, "missing_source_key", f"missing source_record key: {key}", key)
            for key in sorted(REQUIRED_SOURCE_RECORD_KEYS - source_record.keys())
        )
        database = source_record.get("database")
        if database is not None and not str(database).startswith("NIST"):
            errors.append(
                _error(
                    index,
                    species,
                    "non_nist_database",
                    f"source_record.database must start with NIST: {database}",
                    "source_record.database",
                )
            )

    return errors


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed NIST snapshot YAML: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("NIST snapshot must be a YAML mapping")
    return payload


def _error(
    index: int,
    species: Any,
    reason: str,
    message: str,
    field: str | None = None,
) -> dict[str, Any]:
    payload = {
        "index": index,
        "species": species,
        "reason": reason,
        "message": message,
    }
    if field is not None:
        payload["field"] = field
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
