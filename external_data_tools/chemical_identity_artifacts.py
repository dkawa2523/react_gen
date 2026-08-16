from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .chemical_identity_normalize import normalize_identity_records


def load_species_entries(path: Path) -> list[dict[str, str]]:
    payload = read_yaml_mapping(path)
    entries = payload.get("species", [])
    if not isinstance(entries, list):
        raise ValueError("species list must contain a species list")

    normalized = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("query"):
            raise ValueError("species entries require id and query")
        normalized.append({"id": str(entry["id"]), "query": str(entry["query"])})
    return normalized


def dry_run_plan(
    species_entries: list[dict[str, str]],
    provider: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dry_run": True,
        "provider": provider,
        "summary": {
            "total_species": len(species_entries),
            "planned": len(species_entries),
            "records": 0,
            "unresolved": 0,
        },
        "planned": [
            {"species": entry["id"], "query": entry["query"], "provider": provider}
            for entry in species_entries
        ],
    }


def write_identity_artifacts(
    output_root: Path,
    snapshot_path: Path,
    provider: str,
    records: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> dict[str, Any]:
    snapshot = normalize_identity_records(records)
    snapshot["source"]["generated_at"] = _utc_now()
    snapshot["source"]["provider"] = provider
    snapshot["unresolved"] = unresolved
    _write_yaml(snapshot_path, snapshot)

    source_files = [
        item
        for record in records
        for item in record.get("source_records", [])
        if isinstance(item, dict)
    ]
    _write_source_manifest(
        output_root / "manifest.yaml",
        provider,
        snapshot_path,
        records,
        unresolved,
        source_files,
    )
    return snapshot


def _write_source_manifest(
    path: Path,
    provider: str,
    snapshot_path: Path,
    records: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
    source_files: list[dict[str, Any]],
) -> None:
    payload = {
        "schema_version": 1,
        "provider": provider,
        "snapshot": str(snapshot_path),
        "generated_at": _utc_now(),
        "records": len(records),
        "unresolved": len(unresolved),
        "source_files": source_files,
    }
    _write_yaml(path, payload)


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def read_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML input must be a mapping: {path}")
    return payload


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
