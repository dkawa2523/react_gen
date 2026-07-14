from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from external_data_tools.cache import sha256_file


def check_data_requirements(path: Path) -> dict[str, Any]:
    path = Path(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("data requirements must be a YAML mapping")

    records = []
    for section in ("required_for_registry_benchmark", "optional_for_registry_benchmark"):
        for item in payload.get(section, []) if isinstance(payload.get(section, []), list) else []:
            if isinstance(item, dict):
                records.append(_check_one_requirement(item, base_dir=path.parent, section=section))

    required_missing = [item for item in records if item["status"] == "required_missing"]
    optional_missing = [item for item in records if item["status"] == "optional_missing"]
    return {
        "schema_version": 1,
        "requirements_file": str(path),
        "data_status": records,
        "summary": {
            "n_records": len(records),
            "n_ready": sum(1 for item in records if item["status"] == "ready"),
            "n_required_missing": len(required_missing),
            "n_optional_missing": len(optional_missing),
            "required_data_ready": not required_missing,
            "optional_data_ready": not optional_missing,
        },
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
    if cwd_candidate.exists() or path.parts[:1] in {("benchmarks",), ("cases",), ("external_data",)}:
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
