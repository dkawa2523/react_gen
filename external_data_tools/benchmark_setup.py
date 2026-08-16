from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from external_data_tools.benchmark_data_requirements import check_data_requirements
from external_data_tools.http_client import download_many
from external_data_tools.source_setup_actions import run_install_command


def run_setup(
    config_path: str | Path,
    *,
    check: bool = False,
    install_python_deps: bool = False,
    download_explicit_data: bool = False,
    write_report: str | Path | None = None,
) -> tuple[dict[str, Any], int]:
    config_path = Path(config_path)
    config = _read_yaml(config_path)
    policies = config.get("policies", {}) if isinstance(config.get("policies"), dict) else {}

    data_config_path = _resolve_path(
        config.get("data_requirements", {}).get("config"),
        config_path,
    )
    if data_config_path is None:
        raise ValueError("benchmark setup requires data_requirements.config")

    data_report = check_data_requirements(data_config_path)
    python_report = _python_dependency_report(config, config_path, install_python_deps)
    download_report = _download_report(config, config_path, download_explicit_data, policies)

    report = _setup_report(
        config_path=config_path,
        data_report=data_report,
        python_report=python_report,
        download_report=download_report,
        policies=policies,
        check=check,
    )

    exit_code = _exit_code(report, policies)
    if write_report is not None:
        _write_yaml(Path(write_report), report)
    return report, exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check local registry benchmark data and Python tooling."
    )
    parser.add_argument("--config", type=Path, required=True, help="benchmark setup YAML")
    parser.add_argument("--check", action="store_true", help="check benchmark data")
    parser.add_argument(
        "--install-python-deps",
        action="store_true",
        help="explicitly install listed Python requirements",
    )
    parser.add_argument(
        "--download-explicit-data",
        action="store_true",
        help="download explicit user-provided URLs if policy allows it",
    )
    parser.add_argument(
        "--write-report", type=Path, default=None, help="optional setup report YAML path"
    )
    args = parser.parse_args(argv)

    report, exit_code = run_setup(
        args.config,
        check=args.check,
        install_python_deps=args.install_python_deps,
        download_explicit_data=args.download_explicit_data,
        write_report=args.write_report,
    )
    _print_summary(report)
    return exit_code


def _python_dependency_report(
    config: dict[str, Any], config_path: Path, install: bool
) -> dict[str, Any]:
    python_config = config.get("python", {}) if isinstance(config.get("python"), dict) else {}
    configured_requirements = python_config.get("requirements", [])
    requirements = (
        [
            resolved
            for value in configured_requirements
            if value and (resolved := _resolve_path(value, config_path)) is not None
        ]
        if isinstance(configured_requirements, list)
        else []
    )

    records = []
    installed = False
    for requirement in requirements:
        record: dict[str, Any] = {
            "requirements": str(requirement),
            "exists": requirement.exists(),
            "installed": False,
        }
        if install:
            if not requirement.exists():
                record["error"] = "requirements file not found"
            else:
                command = [sys.executable, "-m", "pip", "install", "-r", str(requirement)]
                result = run_install_command(command)
                record["command"] = " ".join(command)
                record["return_code"] = result.returncode
                record["installed"] = result.returncode == 0
                installed = installed or bool(record["installed"])
        records.append(record)

    return {
        "requested": bool(install),
        "python_optional_dependencies_installed": bool(installed),
        "requirements": records,
    }


def _download_report(
    config: dict[str, Any],
    config_path: Path,
    download: bool,
    policies: dict[str, Any],
) -> dict[str, Any]:
    if not download:
        return {"requested": False, "ran": False, "summary": {"downloaded": 0, "failed": 0}}
    if not policies.get("allow_network_downloads", False):
        return {
            "requested": True,
            "ran": False,
            "error": "network downloads are disabled by policy",
            "summary": {"downloaded": 0, "failed": 1},
        }

    manifest_path = _resolve_path(config.get("downloads", {}).get("manifest"), config_path)
    if manifest_path is None or not manifest_path.exists():
        return {
            "requested": True,
            "ran": False,
            "error": "download manifest not found",
            "summary": {"downloaded": 0, "failed": 1},
        }

    manifest = _read_yaml(manifest_path)
    report = download_many(manifest, manifest_path.parent, dry_run=False)
    report["requested"] = True
    report["ran"] = True
    report["manifest"] = str(manifest_path)
    return report


def _setup_report(
    *,
    config_path: Path,
    data_report: dict[str, Any],
    python_report: dict[str, Any],
    download_report: dict[str, Any],
    policies: dict[str, Any],
    check: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "config": str(config_path),
        "mode": {
            "check": bool(check),
            "install_python_deps": bool(python_report["requested"]),
            "download_explicit_data": bool(download_report.get("requested")),
        },
        "summary": {
            "required_data_ready": bool(data_report["summary"]["required_data_ready"]),
            "optional_data_ready": bool(data_report["summary"]["optional_data_ready"]),
            "python_optional_dependencies_installed": bool(
                python_report["python_optional_dependencies_installed"]
            ),
            "downloads_ready": not download_report.get("error")
            and download_report.get("summary", {}).get("failed", 0) == 0,
        },
        "policies": policies,
        "data_status": data_report["data_status"],
        "python": python_report,
        "downloads": download_report,
    }


def _exit_code(report: dict[str, Any], policies: dict[str, Any]) -> int:
    if (
        policies.get("fail_if_required_data_missing", True)
        and not report["summary"]["required_data_ready"]
    ):
        return 1
    if report["downloads"].get("error"):
        return 1
    return 0


def _resolve_path(value: Any, config_path: Path) -> Path | None:
    if value is None:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists() or path.parts[:1] in {
        ("benchmarks",),
        ("external_data",),
        ("external_data_tools",),
    }:
        return cwd_candidate
    return (config_path.parent / path).resolve()


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
    print("benchmark setup:")
    print(f"  required_data_ready: {str(summary['required_data_ready']).lower()}")
    print(f"  optional_data_ready: {str(summary['optional_data_ready']).lower()}")
    dependencies_installed = str(summary["python_optional_dependencies_installed"]).lower()
    print(f"  python_optional_dependencies_installed: {dependencies_installed}")
    if report["downloads"].get("error"):
        print(f"  download_error: {report['downloads']['error']}")


if __name__ == "__main__":
    raise SystemExit(main())
