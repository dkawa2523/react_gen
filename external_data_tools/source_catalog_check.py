from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FIELDS = {
    "source_id",
    "category",
    "allowed_in_core_generate",
    "allowed_in_enrich",
    "allowed_in_external_tools",
    "requires_license_review",
    "requires_api_key",
    "redistribution_risk",
    "default_status",
    "notes",
}

VALID_CATEGORIES = {
    "bundled",
    "internal",
    "public_snapshot",
    "public_api",
    "commercial_or_license_restricted",
    "user_provided_file",
    "optional_python_package",
}

VALID_RISKS = {"low", "medium", "high", "unknown"}
VALID_STATUSES = {"curated", "literature_supported", "imported", "estimated", "inferred"}
BOOL_FIELDS = (
    "allowed_in_core_generate",
    "allowed_in_enrich",
    "allowed_in_external_tools",
    "requires_license_review",
    "requires_api_key",
)


def load_source_catalog(path: str | Path) -> dict[str, Any]:
    catalog_path = Path(path)
    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source catalog must be a YAML mapping")
    return payload


def validate_source_catalog(
    path: str | Path, project_root: str | Path | None = None
) -> dict[str, Any]:
    catalog_path = Path(path)
    root = Path(project_root) if project_root is not None else _default_project_root(catalog_path)
    return validate_catalog_payload(load_source_catalog(catalog_path), project_root=root)


def validate_catalog_payload(
    payload: dict[str, Any],
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    sources = _source_records(payload.get("sources"), errors)
    seen: set[str] = set()
    core_dependencies = (
        _core_dependencies(Path(project_root)) if project_root is not None else set()
    )
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"sources[{index}] must be a mapping")
            continue
        source_errors, source_warnings = _validate_source(
            source,
            index=index,
            seen=seen,
            core_dependencies=core_dependencies,
        )
        errors.extend(source_errors)
        warnings.extend(source_warnings)
    return {
        "valid": not errors,
        "summary": {
            "n_sources": len(sources),
            "n_errors": len(errors),
            "n_warnings": len(warnings),
        },
        "errors": errors,
        "warnings": warnings,
    }


def _source_records(value: Any, errors: list[str]) -> list[Any]:
    if isinstance(value, list):
        return value
    errors.append("sources must be a list")
    return []


def _validate_source(
    source: dict[str, Any],
    *,
    index: int,
    seen: set[str],
    core_dependencies: set[str],
) -> tuple[list[str], list[str]]:
    source_id = str(source.get("source_id", f"<missing:{index}>"))
    errors = [
        f"{source_id}: missing required field {field}"
        for field in sorted(REQUIRED_FIELDS - set(source))
    ]
    if source_id in seen:
        errors.append(f"{source_id}: duplicate source_id")
    seen.add(source_id)
    errors.extend(_value_errors(source_id, source))
    errors.extend(_policy_errors(source_id, source, core_dependencies))
    warnings = _source_warnings(source_id, source)
    return errors, warnings


def _value_errors(label: str, source: dict[str, Any]) -> list[str]:
    errors = []
    for field, allowed in (
        ("category", VALID_CATEGORIES),
        ("redistribution_risk", VALID_RISKS),
        ("default_status", VALID_STATUSES),
    ):
        if source.get(field) not in allowed:
            errors.append(f"{label}: invalid {field} {source.get(field)!r}")
    errors.extend(
        f"{label}: {field} must be boolean"
        for field in BOOL_FIELDS
        if field in source and not isinstance(source[field], bool)
    )
    return errors


def _policy_errors(
    label: str,
    source: dict[str, Any],
    core_dependencies: set[str],
) -> list[str]:
    errors = []
    category = source.get("category")
    risk = source.get("redistribution_risk")
    if category in {"public_api", "commercial_or_license_restricted"} and source.get(
        "allowed_in_core_generate"
    ):
        errors.append(f"{label}: {category} sources cannot be allowed in core generate")
    if risk in {"high", "unknown"} and not source.get("requires_license_review"):
        errors.append(f"{label}: {risk} redistribution risk requires license review")
    if category == "optional_python_package":
        package_name = str(source.get("package_name") or label)
        if _normalize_dependency_name(package_name) in core_dependencies:
            errors.append(
                f"{label}: optional package {package_name!r} is listed in "
                "core pyproject dependencies"
            )
    return errors


def _source_warnings(label: str, source: dict[str, Any]) -> list[str]:
    if source.get("category") == "bundled" and source.get("requires_api_key"):
        return [f"{label}: bundled sources should not require API keys"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate external_data/source_catalog.yaml governance metadata."
    )
    parser.add_argument("catalog", type=Path, help="source catalog YAML path")
    args = parser.parse_args(argv)

    report = validate_source_catalog(args.catalog)
    if report["valid"]:
        print(f"source catalog check passed: {report['summary']['n_sources']} sources")
        return 0

    print("source catalog check failed:", file=sys.stderr)
    for error in report["errors"]:
        print(f"- {error}", file=sys.stderr)
    return 1


def _default_project_root(catalog_path: Path) -> Path:
    if catalog_path.parent.name == "external_data":
        return catalog_path.parent.parent
    return Path.cwd()


def _core_dependencies(project_root: Path) -> set[str]:
    pyproject = project_root / "pyproject.toml"
    if not pyproject.exists():
        return set()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    if not isinstance(deps, list):
        return set()
    return {_normalize_dependency_name(str(dep)) for dep in deps}


def _normalize_dependency_name(requirement: str) -> str:
    name = re.split(r"[\s<>=!~;\[]", requirement.strip(), maxsplit=1)[0]
    return name.replace("_", "-").lower()


if __name__ == "__main__":
    raise SystemExit(main())
