from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import re
import sys
import tomllib

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
BOOL_FIELDS = {
    "allowed_in_core_generate",
    "allowed_in_enrich",
    "allowed_in_external_tools",
    "requires_license_review",
    "requires_api_key",
}


def load_source_catalog(path: str | Path) -> dict[str, Any]:
    catalog_path = Path(path)
    payload = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("source catalog must be a YAML mapping")
    return payload


def validate_source_catalog(path: str | Path, project_root: str | Path | None = None) -> dict[str, Any]:
    catalog_path = Path(path)
    root = Path(project_root) if project_root is not None else _default_project_root(catalog_path)
    return validate_catalog_payload(load_source_catalog(catalog_path), project_root=root)


def validate_catalog_payload(payload: dict[str, Any], project_root: str | Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    sources = payload.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be a list")
        sources = []

    seen: set[str] = set()
    core_dependencies = _core_dependencies(Path(project_root)) if project_root is not None else set()

    for index, source in enumerate(sources):
        label = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{label} must be a mapping")
            continue

        source_id = str(source.get("source_id", f"<missing:{index}>"))
        label = source_id
        missing = sorted(REQUIRED_FIELDS - set(source))
        for field in missing:
            errors.append(f"{label}: missing required field {field}")

        if source_id in seen:
            errors.append(f"{label}: duplicate source_id")
        seen.add(source_id)

        category = source.get("category")
        if category not in VALID_CATEGORIES:
            errors.append(f"{label}: invalid category {category!r}")

        risk = source.get("redistribution_risk")
        if risk not in VALID_RISKS:
            errors.append(f"{label}: invalid redistribution_risk {risk!r}")

        status = source.get("default_status")
        if status not in VALID_STATUSES:
            errors.append(f"{label}: invalid default_status {status!r}")

        for field in BOOL_FIELDS:
            if field in source and not isinstance(source[field], bool):
                errors.append(f"{label}: {field} must be boolean")

        if category in {"public_api", "commercial_or_license_restricted"} and source.get("allowed_in_core_generate"):
            errors.append(f"{label}: {category} sources cannot be allowed in core generate")

        if risk in {"high", "unknown"} and not source.get("requires_license_review"):
            errors.append(f"{label}: {risk} redistribution risk requires license review")

        if category == "optional_python_package":
            package_name = str(source.get("package_name") or source_id)
            normalized = _normalize_dependency_name(package_name)
            if normalized in core_dependencies:
                errors.append(
                    f"{label}: optional package {package_name!r} is listed in core pyproject dependencies"
                )

        if category == "bundled" and source.get("requires_api_key"):
            warnings.append(f"{label}: bundled sources should not require API keys")

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate external_data/source_catalog.yaml governance metadata.")
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
