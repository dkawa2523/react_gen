from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from external_data_tools.http_client import download_many
from external_data_tools.source_setup_io import read_yaml, resolve_path


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def chemicals_report(
    config: dict[str, Any],
    config_path: Path,
    *,
    install: bool,
) -> dict[str, Any]:
    optional = config.get("optional_python_dependencies", {})
    chemicals = optional.get("chemicals", {}) if isinstance(optional, dict) else {}
    requirements = resolve_path(
        chemicals.get(
            "requirements",
            "external_data_tools/requirements-chemicals.txt",
        ),
        config_path,
    )
    record = {
        "package": "chemicals",
        "available": importlib.util.find_spec("chemicals") is not None,
        "install_requested": install,
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
    result = run_install_command(command)
    record.update(
        {
            "command": " ".join(command),
            "return_code": result.returncode,
            "installed": result.returncode == 0,
            "available": importlib.util.find_spec("chemicals") is not None,
        }
    )
    if result.returncode != 0:
        record["error"] = result.stderr.strip() or "pip install failed"
    return record


def downloads_report(
    config: dict[str, Any],
    config_path: Path,
    *,
    requested: bool,
) -> dict[str, Any]:
    if not requested:
        return _download_summary(requested=False, ran=False)
    policies = config.get("policies")
    if not isinstance(policies, dict) or not policies.get(
        "allow_network_downloads",
        False,
    ):
        return {
            **_download_summary(requested=True, ran=False, failed=1),
            "error": "network downloads are disabled by policy",
        }

    reports = [
        _download_source(source, config_path)
        for source in config.get("sources", [])
        if isinstance(source, dict) and source.get("enabled") and source.get("download_manifest")
    ]
    summary = {
        key: sum(int(report.get("summary", {}).get(key, 0)) for report in reports)
        for key in ("total", "downloaded", "failed")
    }
    return {
        "requested": True,
        "ran": bool(reports),
        "summary": summary,
        "reports": reports,
    }


def run_install_command(command: list[str]) -> CommandResult:
    return asyncio.run(_run_install_command(command))


async def _run_install_command(command: list[str]) -> CommandResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return CommandResult(
        returncode=process.returncode or 0,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


def _download_source(
    source: dict[str, Any],
    config_path: Path,
) -> dict[str, Any]:
    manifest_path = resolve_path(source["download_manifest"], config_path)
    if not manifest_path.exists():
        return {
            "source_id": source.get("source_id"),
            "manifest": str(manifest_path),
            "ran": False,
            "error": "download manifest not found",
            "summary": {"total": 0, "downloaded": 0, "failed": 1},
        }
    output_root = resolve_path(
        source.get("download_output_root", "external_data/raw"),
        config_path,
    )
    report = download_many(read_yaml(manifest_path), output_root, dry_run=False)
    report.update(
        {
            "source_id": source.get("source_id"),
            "manifest": str(manifest_path),
            "output_root": str(output_root),
        }
    )
    return report


def _download_summary(
    *,
    requested: bool,
    ran: bool,
    failed: int = 0,
) -> dict[str, Any]:
    return {
        "requested": requested,
        "ran": ran,
        "summary": {"total": 0, "downloaded": 0, "failed": failed},
    }


__all__ = [
    "CommandResult",
    "chemicals_report",
    "downloads_report",
    "run_install_command",
]
