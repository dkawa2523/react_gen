from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def build_source_setup_report(
    *,
    config_path: Path,
    check: bool,
    install_chemicals: bool,
    download_explicit_data: bool,
    validation: dict[str, Any],
    sources: list[dict[str, Any]],
    chemicals: dict[str, Any],
    downloads: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).isoformat(),
        "config": str(config_path),
        "mode": {
            "check": check,
            "install_chemicals": install_chemicals,
            "download_explicit_data": download_explicit_data,
        },
        "summary": _summary(
            validation,
            sources,
            chemicals,
            downloads,
            catalog,
        ),
        "validation": validation,
        "source_catalog": catalog,
        "sources": sources,
        "chemicals": chemicals,
        "downloads": downloads,
    }


def source_setup_exit_code(report: dict[str, Any]) -> int:
    failed = (
        not report["summary"]["valid"]
        or bool(report["downloads"].get("error"))
        or bool(report["summary"]["downloads_failed"])
        or bool(report["chemicals"].get("install_requested") and report["chemicals"].get("error"))
    )
    return int(failed)


def format_source_setup_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "external source setup:",
        f"  valid: {str(summary['valid']).lower()}",
        f"  enabled_sources: {summary['n_enabled_sources']}/{summary['n_sources']}",
        f"  chemicals_available: {str(summary['chemicals_available']).lower()}",
        f"  downloads_ran: {str(summary['downloads_ran']).lower()}",
        f"  downloads_failed: {summary['downloads_failed']}",
    ]
    errors = report["validation"]["errors"]
    if errors:
        lines.append("  validation_errors:")
        lines.extend(f"    - {error}" for error in errors)
    if report["downloads"].get("error"):
        lines.append(f"  download_error: {report['downloads']['error']}")
    return "\n".join(lines)


def _summary(
    validation: dict[str, Any],
    sources: list[dict[str, Any]],
    chemicals: dict[str, Any],
    downloads: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    return {
        "valid": bool(validation["valid"] and catalog.get("valid", True)),
        "n_sources": len(sources),
        "n_enabled_sources": sum(item["enabled"] for item in sources),
        "chemicals_available": bool(chemicals["available"]),
        "downloads_ran": bool(downloads["ran"]),
        "downloads_failed": int(downloads.get("summary", {}).get("failed", 0)),
    }
