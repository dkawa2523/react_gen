from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.source_setup_io import resolve_path

UNSAFE_AUTOMATION_LEVELS = {
    "scraping",
    "crawler",
    "login_automation",
    "hidden_api_discovery",
}
_REQUIRED_SOURCE_FIELDS = (
    "source_id",
    "enabled",
    "access_mode",
    "automation_level",
)


def validate_access_profile(
    payload: dict[str, Any],
    *,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    errors = []
    warnings = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be a list")
        sources = []

    seen: set[str] = set()
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be a mapping")
            continue
        source_errors, source_warnings = _source_findings(
            source,
            index=index,
            seen=seen,
            config_path=Path(config_path) if config_path is not None else None,
        )
        errors.extend(source_errors)
        warnings.extend(source_warnings)
    return {
        "valid": not errors,
        "summary": {"n_errors": len(errors), "n_warnings": len(warnings)},
        "errors": errors,
        "warnings": warnings,
    }


def _source_findings(
    source: dict[str, Any],
    *,
    index: int,
    seen: set[str],
    config_path: Path | None,
) -> tuple[list[str], list[str]]:
    source_id = str(source.get("source_id") or f"<missing:{index}>")
    errors = []
    if source_id in seen:
        errors.append(f"{source_id}: duplicate source_id")
    seen.add(source_id)
    errors.extend(
        f"{source_id}: missing required field {field}"
        for field in _REQUIRED_SOURCE_FIELDS
        if field not in source
    )
    errors.extend(_source_policy_errors(source_id, source))
    warnings = _source_warnings(source_id, source, config_path)
    return errors, warnings


def _source_policy_errors(
    source_id: str,
    source: dict[str, Any],
) -> list[str]:
    errors = []
    if source.get("allowed_in_core_generate") is True:
        errors.append(f"{source_id}: external source access cannot be allowed in core generate")
    automation_level = source.get("automation_level")
    if automation_level in UNSAFE_AUTOMATION_LEVELS:
        errors.append(f"{source_id}: unsupported automation_level {automation_level!r}")
    return errors


def _source_warnings(
    source_id: str,
    source: dict[str, Any],
    config_path: Path | None,
) -> list[str]:
    warnings = []
    if source.get("requires_license_review") and not source.get("license_note"):
        warnings.append(
            f"{source_id}: license review is required; add a license_note before sharing data"
        )
    if source.get("requires_api_key") and not source.get("api_key_env"):
        warnings.append(f"{source_id}: API key is required but api_key_env is not configured")
    manifest = source.get("download_manifest")
    if manifest and config_path is not None:
        manifest_path = resolve_path(manifest, config_path)
        if not manifest_path.exists():
            warnings.append(f"{source_id}: download manifest not found: {manifest_path}")
    return warnings


__all__ = ["validate_access_profile"]
