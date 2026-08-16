from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from external_data_tools.cache import sha256_file

REQUIREMENT_SECTIONS = (
    "required_for_registry_benchmark",
    "optional_for_registry_benchmark",
)


def check_data_requirements(path: Path) -> dict[str, Any]:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("data requirements must be a YAML mapping")

    records = _requirement_records(payload, path.parent)
    return {
        "schema_version": 1,
        "requirements_file": str(path),
        "data_status": records,
        "summary": _requirements_summary(records),
    }


def _requirement_records(payload: dict[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for section in REQUIREMENT_SECTIONS:
        items = payload.get(section, [])
        if not isinstance(items, list):
            continue
        records.extend(
            _check_one_requirement(item, base_dir=base_dir, section=section)
            for item in items
            if isinstance(item, dict)
        )
    return records


def _requirements_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {
        status: sum(item["status"] == status for item in records)
        for status in ("ready", "required_missing", "optional_missing")
    }
    return {
        "n_records": len(records),
        "n_ready": status_counts["ready"],
        "n_required_missing": status_counts["required_missing"],
        "n_optional_missing": status_counts["optional_missing"],
        "required_data_ready": status_counts["required_missing"] == 0,
        "optional_data_ready": status_counts["optional_missing"] == 0,
    }


def _check_one_requirement(item: dict[str, Any], *, base_dir: Path, section: str) -> dict[str, Any]:
    required = bool(item.get("required", section == "required_for_registry_benchmark"))
    raw_path = item.get("path")
    resolved = _resolve_path(raw_path, base_dir) if raw_path else None
    ready = bool(resolved and resolved.exists())
    status = "ready" if ready else "required_missing" if required else "optional_missing"
    record = {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "section": section,
        "required": required,
        "path": str(resolved) if resolved is not None else None,
        "status": status,
    }
    if ready and resolved and resolved.is_file():
        record["sha256"] = sha256_file(resolved)
    if status != "ready":
        record["suggested_action"] = _suggested_action(item)
    return record


def _resolve_path(value: Any, base_dir: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    repository_roots = {("benchmarks",), ("cases",), ("external_data",)}
    if cwd_candidate.exists() or path.parts[:1] in repository_roots:
        return cwd_candidate
    return (base_dir / path).resolve()


def _suggested_action(item: dict[str, Any]) -> str:
    kind = item.get("kind")
    if kind == "cross_section_csv":
        return "Provide a reviewed local CSV/TSV cross-section fixture."
    if kind == "cross_section_asset_set":
        return "Import reviewed LXCat or user-provided files using reactgen import-cross-sections."
    if kind == "internal_file_db":
        return "Provide reviewed internal_data YAML fixtures."
    return "Provide the required local benchmark data."
