from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import shutil

import yaml

from .cache import safe_filename, sha256_file


SUPPORTED_ADF_CLASSES = {"ADF01", "ADF07"}


def import_openadas_manifest(manifest_path: Path, *, workspace: Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    workspace = Path(workspace)
    payload = _read_yaml(manifest_path)
    files = payload.get("files", [])
    if not isinstance(files, list):
        raise ValueError("OpenADAS manifest must contain a files list")

    source = payload.get("source", {})
    if not isinstance(source, dict):
        source = {}

    report: dict[str, Any] = {
        "schema_version": 1,
        "manifest": str(manifest_path),
        "workspace": str(workspace),
        "registry_mutated": False,
        "source": {
            "database": source.get("database", "OpenADAS"),
            "access_mode": source.get("access_mode", "manual_download"),
        },
        "files": [],
        "ion_reaction_tables": [],
        "unresolved": [],
        "summary": {
            "n_files": len(files),
            "n_cached": 0,
            "n_ion_reaction_tables": 0,
            "n_unresolved": 0,
        },
    }

    file_records: dict[str, dict[str, Any]] = {}
    for item in files:
        if not isinstance(item, dict):
            report["unresolved"].append({"reason": "file_record_not_mapping"})
            continue
        try:
            record = _cache_file(item, workspace)
        except Exception as exc:
            report["unresolved"].append(
                {
                    "id": item.get("id"),
                    "reason": "cache_failed",
                    "message": str(exc),
                }
            )
            continue

        report["files"].append(record)
        file_records[record["id"]] = record
        if record["adf_class"] not in SUPPORTED_ADF_CLASSES:
            report["unresolved"].append(
                {
                    "id": record["id"],
                    "adf_class": record["adf_class"],
                    "reason": "unsupported_adf_class",
                }
            )

    table_records = _write_ion_reaction_tables(payload.get("openadas_mappings", []), file_records)
    report["ion_reaction_tables"].extend(table_records)
    report["summary"]["n_cached"] = len(report["files"])
    report["summary"]["n_ion_reaction_tables"] = len(table_records)
    report["summary"]["n_unresolved"] = len(report["unresolved"])

    report_path = workspace / "openadas_import_report.yaml"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        yaml.safe_dump(report, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Register manually downloaded OpenADAS raw files in a local workspace."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)

    report = import_openadas_manifest(args.manifest, workspace=args.workspace)
    print(
        "openadas raw import: "
        f"cached={report['summary']['n_cached']} "
        f"ion_tables={report['summary']['n_ion_reaction_tables']} "
        f"unresolved={report['summary']['n_unresolved']} "
        f"report={args.workspace / 'openadas_import_report.yaml'}"
    )
    return 1 if report["summary"]["n_unresolved"] else 0


def _cache_file(item: dict[str, Any], workspace: Path) -> dict[str, Any]:
    file_id = str(item.get("id") or "")
    if not file_id:
        raise ValueError("OpenADAS file record requires id")
    local_path = item.get("local_path")
    if not local_path:
        raise ValueError(f"OpenADAS file record requires local_path: {file_id}")
    original_path = Path(local_path)
    if not original_path.exists():
        raise FileNotFoundError(original_path)

    digest = sha256_file(original_path)
    adf_class = str(item.get("adf_class") or "").upper()
    cache_root = workspace / "source_cache"
    cached_path = (
        cache_root
        / "openadas"
        / safe_filename(file_id)
        / f"{safe_filename(original_path.stem)}_{digest[:12]}{original_path.suffix}"
    )
    cached_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original_path, cached_path)

    source_file = {
        "source_type": "local_file_cache",
        "source_name": "openadas",
        "id": file_id,
        "adf_class": adf_class,
        "original_path": str(original_path),
        "cached_path": cached_path.relative_to(cache_root).as_posix(),
        "sha256": digest,
        "imported_at": _utc_now(),
        "description": item.get("description"),
        "citation": item.get("citation"),
    }
    _append_source_manifest(cache_root / "manifest.yaml", source_file)
    return source_file


def _write_ion_reaction_tables(
    mappings: Any,
    file_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if mappings is None:
        return []
    if not isinstance(mappings, list):
        raise ValueError("openadas_mappings must be a list when provided")

    grouped: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for mapping in mappings:
        if not isinstance(mapping, dict):
            continue
        file_id = mapping.get("file_id")
        file_record = file_records.get(str(file_id))
        if file_record is None or file_record.get("adf_class") != "ADF01":
            continue
        output_table = mapping.get("output_table")
        if not output_table:
            continue
        grouped[Path(output_table)].append(_ion_reaction_record(mapping, file_record))

    written = []
    for output_table, reactions in grouped.items():
        payload = _load_existing_ion_table(output_table)
        payload.setdefault("reactions", []).extend(reactions)
        output_table.parent.mkdir(parents=True, exist_ok=True)
        output_table.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        written.append(
            {
                "output_table": str(output_table),
                "n_reactions": len(reactions),
            }
        )
    return written


def _ion_reaction_record(mapping: dict[str, Any], file_record: dict[str, Any]) -> dict[str, Any]:
    projectile = str(mapping.get("projectile") or "")
    target = str(mapping.get("target") or "")
    reaction_type = str(mapping.get("type") or "charge_transfer")
    reaction_id = mapping.get("id") or "_".join(
        safe_filename(part) for part in (file_record["id"], projectile, target, reaction_type) if part
    )
    return {
        "id": reaction_id,
        "projectile": projectile,
        "target": target,
        "family": mapping.get("family", "ion_neutral"),
        "type": reaction_type,
        "dnt_class": mapping.get("dnt_class"),
        "products": mapping.get("products", []),
        "status": mapping.get("status", "imported"),
        "evidence_type": "openadas_raw_file_metadata",
        "citation": file_record.get("citation"),
        "data": {
            "openadas": {
                "file_id": file_record["id"],
                "adf_class": file_record["adf_class"],
                "cached_path": file_record["cached_path"],
                "original_file": file_record["original_path"],
                "sha256": file_record["sha256"],
                "description": file_record.get("description"),
            }
        },
        "source_record": {
            "source_type": "public_database_snapshot",
            "database": "OpenADAS",
            "access_mode": "manual_download",
            "source_id": file_record["id"],
            "citation": file_record.get("citation"),
        },
    }


def _load_existing_ion_table(path: Path) -> dict[str, Any]:
    if path.exists():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(payload, dict):
            payload.setdefault("source", _openadas_source())
            return payload
    return {
        "schema_version": 1,
        "source": _openadas_source(),
        "reactions": [],
    }


def _openadas_source() -> dict[str, Any]:
    return {
        "source_type": "public_database_snapshot",
        "database": "OpenADAS",
        "access_mode": "manual_download",
        "generated_at": _utc_now(),
    }


def _append_source_manifest(path: Path, source_file: dict[str, Any]) -> None:
    if path.exists():
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            payload = {}
    else:
        payload = {}
    source_files = payload.get("source_files", [])
    if not isinstance(source_files, list):
        source_files = []
    record = dict(source_file)
    if any(item.get("sha256") == source_file["sha256"] for item in source_files if isinstance(item, dict)):
        record["notes"] = ["A source file with the same sha256 was already recorded."]
    source_files.append(record)
    payload = {"schema_version": int(payload.get("schema_version", 1)), "source_files": source_files}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("OpenADAS manifest must be a YAML mapping")
    return payload


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
