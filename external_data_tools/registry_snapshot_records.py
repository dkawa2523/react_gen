from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from external_data_tools.registry_admin_io import read_yaml, record_import, write_report
from external_data_tools.registry_records import REDISTRIBUTION_VALUES


def read_snapshot_records(path: Path) -> list[dict[str, Any]]:
    """Read supported CSV or YAML snapshot record containers."""

    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8", newline="") as handle:
            return _mapping_records(csv.DictReader(handle))
    return _records_from_payload(read_yaml(path))


def finish_snapshot_report(
    kind: str,
    source: Path,
    registry_root: Path,
    digest: str,
    applied: list[dict[str, Any]],
    review: list[dict[str, Any]],
    report_dir: str | Path | None,
) -> dict[str, Any]:
    report = {
        "schema_version": 1,
        "kind": kind,
        "input_file": str(source),
        "sha256": digest,
        "applied": applied,
        "review": review,
        "duplicate": False,
        "summary": {"n_applied": len(applied), "n_review": len(review)},
    }
    record_import(registry_root, report)
    write_report(report_dir, f"{kind}_import.yaml", report)
    return report


def snapshot_source_record(
    record: dict[str, Any],
    source_file: Path,
    digest: str,
) -> dict[str, Any]:
    redistribution = str(record.get("redistribution_status") or "site-local")
    if redistribution not in REDISTRIBUTION_VALUES:
        redistribution = "site-local"
    return {
        "source_type": record.get("source_type") or "local_snapshot",
        "source": record.get("source") or source_file.name,
        "citation": record.get("citation"),
        "sha256": digest,
        "redistribution_status": redistribution,
    }


def _records_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return _mapping_records(payload)
    if not isinstance(payload, dict):
        return []
    for key in ("records", "properties", "rates"):
        records = payload.get(key)
        if isinstance(records, list):
            return _mapping_records(records)
    return [dict(payload)] if payload else []


def _mapping_records(records: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in records if isinstance(item, dict)]
