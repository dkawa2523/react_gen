from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml


def read_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def write_numeric_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        writer.writerows(rows)


def find_import(
    registry_root: Path,
    kind: str,
    digest: str,
) -> dict[str, Any] | None:
    path = registry_root / "data_admin_imports.yaml"
    manifest = read_yaml(path) if path.is_file() else {}
    return next(
        (
            record
            for record in manifest.get("imports", [])
            if record.get("kind") == kind and record.get("sha256") == digest
        ),
        None,
    )


def record_import(registry_root: Path, report: dict[str, Any]) -> None:
    path = registry_root / "data_admin_imports.yaml"
    manifest = read_yaml(path) if path.is_file() else {
        "schema_version": 1,
        "imports": [],
    }
    record = {
        "kind": report["kind"],
        "input_file": report["input_file"],
        "sha256": report["sha256"],
        "summary": report["summary"],
    }
    imports = manifest.setdefault("imports", [])
    if not any(
        item.get("kind") == record["kind"]
        and item.get("sha256") == record["sha256"]
        for item in imports
    ):
        imports.append(record)
    write_yaml(path, manifest)


def duplicate_report(
    kind: str,
    path: Path,
    digest: str,
    existing: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": kind,
        "input_file": str(path),
        "sha256": digest,
        "duplicate": True,
        "existing": existing,
        "applied": [],
        "review": [],
        "summary": {"n_applied": 0, "n_review": 0},
    }


def write_report(
    report_dir: str | Path | None,
    name: str,
    report: dict[str, Any],
) -> None:
    if report_dir is not None:
        write_yaml(Path(report_dir) / name, report)
