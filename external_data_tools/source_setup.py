from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import argparse
import importlib.util
import subprocess
import sys

import yaml

from external_data_tools.http_client import download_many
from external_data_tools.source_catalog_check import validate_source_catalog


UNSAFE_AUTOMATION_LEVELS = {"scraping", "crawler", "login_automation", "hidden_api_discovery"}


def run_source_setup(
    config_path: str | Path,
    *,
    check: bool = False,
    install_chemicals: bool = False,
    download_explicit_data: bool = False,
    write_report: str | Path | None = None,
) -> tuple[dict[str, Any], int]:
    config_path = Path(config_path)
    config = _read_yaml(config_path)
    validation = validate_access_profile(config, config_path=config_path)
    source_records = _source_records(config, config_path)
    chemicals_report = _chemicals_report(config, config_path, install=install_chemicals)
    downloads_report = _downloads_report(config, config_path, requested=download_explicit_data)
    catalog_report = _catalog_report(config, config_path)

    report = {
        "schema_version": 1,
        "generated_at": _utc_now(),
        "config": str(config_path),
        "mode": {
            "check": bool(check),
            "install_chemicals": bool(install_chemicals),
            "download_explicit_data": bool(download_explicit_data),
        },
        "summary": {
            "valid": bool(validation["valid"] and catalog_report.get("valid", True)),
            "n_sources": len(source_records),
            "n_enabled_sources": sum(1 for item in source_records if item["enabled"]),
            "chemicals_available": bool(chemicals_report["available"]),
            "chemicals_install_requested": bool(install_chemicals),
            "downloads_requested": bool(download_explicit_data),
            "downloads_ran": bool(downloads_report["ran"]),
            "downloads_failed": int(downloads_report.get("summary", {}).get("failed", 0)),
        },
        "validation": validation,
        "source_catalog": catalog_report,
        "sources": source_records,
        "chemicals": chemicals_report,
        "downloads": downloads_report,
    }

    report_path = Path(write_report) if write_report is not None else _default_report_path(config, config_path)
    if report_path is not None:
        _write_yaml(report_path, report)

    return report, _exit_code(report)


def validate_access_profile(payload: dict[str, Any], *, config_path: str | Path | None = None) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    sources = payload.get("sources")
    if not isinstance(sources, list):
        errors.append("sources must be a list")
        sources = []

    seen: set[str] = set()
    for index, source in enumerate(sources):
        label = f"sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{label} must be a mapping")
            continue

        source_id = str(source.get("source_id") or f"<missing:{index}>")
        label = source_id
        if source_id in seen:
            errors.append(f"{label}: duplicate source_id")
        seen.add(source_id)

        for field in ("source_id", "enabled", "access_mode", "automation_level"):
            if field not in source:
                errors.append(f"{label}: missing required field {field}")

        if source.get("allowed_in_core_generate") is True:
            errors.append(f"{label}: external source access cannot be allowed in core generate")

        automation_level = source.get("automation_level")
        if automation_level in UNSAFE_AUTOMATION_LEVELS:
            errors.append(f"{label}: unsupported automation_level {automation_level!r}")

        if source.get("requires_license_review") and not source.get("license_note"):
            warnings.append(f"{label}: license review is required; add a license_note before sharing data")

        if source.get("requires_api_key") and not source.get("api_key_env"):
            warnings.append(f"{label}: API key is required but api_key_env is not configured")

        manifest = source.get("download_manifest")
        if manifest and config_path is not None:
            manifest_path = _resolve_path(manifest, Path(config_path))
            if not manifest_path.exists():
                warnings.append(f"{label}: download manifest not found: {manifest_path}")

    return {
        "valid": not errors,
        "summary": {
            "n_errors": len(errors),
            "n_warnings": len(warnings),
        },
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check external source acquisition setup.")
    parser.add_argument("--config", type=Path, required=True, help="source access profile YAML")
    parser.add_argument("--check", action="store_true", help="validate setup without installing or downloading")
    parser.add_argument("--install-chemicals", action="store_true", help="explicitly install optional chemicals package requirements")
    parser.add_argument("--download-explicit-data", action="store_true", help="download explicit user-provided URL manifests if policy allows it")
    parser.add_argument("--write-report", type=Path, default=None, help="optional report path override")
    args = parser.parse_args(argv)

    report, exit_code = run_source_setup(
        args.config,
        check=args.check,
        install_chemicals=args.install_chemicals,
        download_explicit_data=args.download_explicit_data,
        write_report=args.write_report,
    )
    _print_summary(report)
    return exit_code


def _source_records(config: dict[str, Any], config_path: Path) -> list[dict[str, Any]]:
    records = []
    for source in config.get("sources", []):
        if not isinstance(source, dict):
            continue
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
        for key in ("snapshot_path", "raw_output_root", "download_manifest", "validator", "cli"):
            if source.get(key):
                value = source[key]
                record[key] = str(_resolve_path(value, config_path)) if key.endswith("path") or key.endswith("root") or key == "download_manifest" else value
        records.append(record)
    return records


def _chemicals_report(config: dict[str, Any], config_path: Path, *, install: bool) -> dict[str, Any]:
    optional = config.get("optional_python_dependencies", {})
    chemicals = optional.get("chemicals", {}) if isinstance(optional, dict) else {}
    requirements = _resolve_path(
        chemicals.get("requirements", "external_data_tools/requirements-chemicals.txt"),
        config_path,
    )
    available_before = importlib.util.find_spec("chemicals") is not None
    record = {
        "package": "chemicals",
        "available": available_before,
        "install_requested": bool(install),
        "requirements": str(requirements),
        "requirements_exists": requirements.exists(),
        "installed": False,
    }
    if not install:
        return record
    if not requirements.exists():
        record["error"] = "requirements file not found"
        return record

    command = [sys.executable, "-m", "pip", "install", "-r", str(requirements)]
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    record["command"] = " ".join(command)
    record["return_code"] = result.returncode
    record["installed"] = result.returncode == 0
    record["available"] = importlib.util.find_spec("chemicals") is not None
    if result.returncode != 0:
        record["error"] = result.stderr.strip() or "pip install failed"
    return record


def _downloads_report(config: dict[str, Any], config_path: Path, *, requested: bool) -> dict[str, Any]:
    if not requested:
        return {"requested": False, "ran": False, "summary": {"total": 0, "downloaded": 0, "failed": 0}}

    policies = config.get("policies", {}) if isinstance(config.get("policies"), dict) else {}
    if not policies.get("allow_network_downloads", False):
        return {
            "requested": True,
            "ran": False,
            "error": "network downloads are disabled by policy",
            "summary": {"total": 0, "downloaded": 0, "failed": 1},
        }

    reports = []
    total = downloaded = failed = 0
    for source in config.get("sources", []):
        if not isinstance(source, dict) or not source.get("enabled"):
            continue
        manifest_value = source.get("download_manifest")
        if not manifest_value:
            continue
        manifest_path = _resolve_path(manifest_value, config_path)
        output_root = _resolve_path(source.get("download_output_root", "external_data/raw"), config_path)
        if not manifest_path.exists():
            failed += 1
            reports.append(
                {
                    "source_id": source.get("source_id"),
                    "manifest": str(manifest_path),
                    "ran": False,
                    "error": "download manifest not found",
                    "summary": {"total": 0, "downloaded": 0, "failed": 1},
                }
            )
            continue

        report = download_many(_read_yaml(manifest_path), output_root, dry_run=False)
        report["source_id"] = source.get("source_id")
        report["manifest"] = str(manifest_path)
        report["output_root"] = str(output_root)
        reports.append(report)
        total += int(report.get("summary", {}).get("total", 0))
        downloaded += int(report.get("summary", {}).get("downloaded", 0))
        failed += int(report.get("summary", {}).get("failed", 0))

    return {
        "requested": True,
        "ran": bool(reports),
        "summary": {"total": total, "downloaded": downloaded, "failed": failed},
        "reports": reports,
    }


def _catalog_report(config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    catalog_value = config.get("source_catalog")
    if not catalog_value:
        return {"valid": True, "skipped": True}
    catalog_path = _resolve_path(catalog_value, config_path)
    if not catalog_path.exists():
        return {
            "valid": False,
            "errors": [f"source catalog not found: {catalog_path}"],
            "warnings": [],
        }
    return validate_source_catalog(catalog_path, project_root=_project_root(config_path))


def _exit_code(report: dict[str, Any]) -> int:
    if not report["summary"]["valid"]:
        return 1
    if report["downloads"].get("error") or report["summary"]["downloads_failed"]:
        return 1
    if report["chemicals"].get("install_requested") and report["chemicals"].get("error"):
        return 1
    return 0


def _default_report_path(config: dict[str, Any], config_path: Path) -> Path | None:
    policies = config.get("policies", {}) if isinstance(config.get("policies"), dict) else {}
    report_path = policies.get("report_path", "external_data/manifests/source_setup_report.yaml")
    return _resolve_path(report_path, config_path)


def _resolve_path(value: Any, config_path: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if path.parts[:1] in {("external_data",), ("external_data_tools",), ("benchmarks",), ("workspaces",)}:
        return cwd_candidate
    return (config_path.parent / path).resolve()


def _project_root(config_path: Path) -> Path:
    if config_path.parent.name == "external_data":
        return config_path.parent.parent.resolve()
    return Path.cwd().resolve()


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _print_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("external source setup:")
    print(f"  valid: {str(summary['valid']).lower()}")
    print(f"  enabled_sources: {summary['n_enabled_sources']}/{summary['n_sources']}")
    print(f"  chemicals_available: {str(summary['chemicals_available']).lower()}")
    print(f"  downloads_ran: {str(summary['downloads_ran']).lower()}")
    print(f"  downloads_failed: {summary['downloads_failed']}")
    if report["validation"]["errors"]:
        print("  validation_errors:")
        for error in report["validation"]["errors"]:
            print(f"    - {error}")
    if report["downloads"].get("error"):
        print(f"  download_error: {report['downloads']['error']}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
