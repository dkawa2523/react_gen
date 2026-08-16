from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from external_data_tools.source_catalog_check import validate_source_catalog

_REPOSITORY_RELATIVE_ROOTS = {
    "benchmarks",
    "external_data",
    "external_data_tools",
    "workspaces",
}
_PATH_FIELDS = ("snapshot_path", "raw_output_root", "download_manifest")
_COPY_FIELDS = (*_PATH_FIELDS, "validator", "cli")


def source_records(
    config: dict[str, Any],
    config_path: Path,
) -> list[dict[str, Any]]:
    sources = config.get("sources", [])
    if not isinstance(sources, list):
        return []
    return [_source_record(source, config_path) for source in sources if isinstance(source, dict)]


def catalog_report(
    config: dict[str, Any],
    config_path: Path,
) -> dict[str, Any]:
    catalog_value = config.get("source_catalog")
    if not catalog_value:
        return {"valid": True, "skipped": True}
    catalog_path = resolve_path(catalog_value, config_path)
    if not catalog_path.exists():
        return {
            "valid": False,
            "errors": [f"source catalog not found: {catalog_path}"],
            "warnings": [],
        }
    return validate_source_catalog(
        catalog_path,
        project_root=_project_root(config_path),
    )


def default_report_path(config: dict[str, Any], config_path: Path) -> Path:
    policies = config.get("policies")
    report_path = (
        policies.get("report_path", "external_data/manifests/source_setup_report.yaml")
        if isinstance(policies, dict)
        else "external_data/manifests/source_setup_report.yaml"
    )
    return resolve_path(report_path, config_path)


def resolve_path(value: Any, config_path: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if path.parts and path.parts[0] in _REPOSITORY_RELATIVE_ROOTS:
        return cwd_candidate
    return (config_path.parent / path).resolve()


def read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return payload


def write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _source_record(source: dict[str, Any], config_path: Path) -> dict[str, Any]:
    record = {
        "source_id": source.get("source_id"),
        "enabled": bool(source.get("enabled", False)),
        "access_mode": source.get("access_mode"),
        "automation_level": source.get("automation_level"),
        "requires_registration": bool(source.get("requires_registration", False)),
        "requires_license_review": bool(source.get("requires_license_review", False)),
        "requires_api_key": bool(source.get("requires_api_key", False)),
        "status": "enabled" if source.get("enabled", False) else "disabled",
        "notes": source.get("notes", []),
    }
    record.update(
        {
            key: _record_value(key, source[key], config_path)
            for key in _COPY_FIELDS
            if source.get(key)
        }
    )
    return record


def _record_value(key: str, value: Any, config_path: Path) -> Any:
    return str(resolve_path(value, config_path)) if key in _PATH_FIELDS else value


def _project_root(config_path: Path) -> Path:
    if config_path.parent.name == "external_data":
        return config_path.parent.parent.resolve()
    return Path.cwd().resolve()


__all__ = [
    "catalog_report",
    "default_report_path",
    "read_yaml",
    "resolve_path",
    "source_records",
    "write_yaml",
]
