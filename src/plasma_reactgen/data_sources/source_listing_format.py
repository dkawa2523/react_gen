from __future__ import annotations

from typing import Any


def format_source_list_report(report: dict[str, Any]) -> str:
    lines = [
        f"Source profile: {report['source_profile']}",
        "Active sources: " + _format_list(report["active_sources"]),
        "Optional sources: " + _format_list(report["optional_sources"]),
        "Optional configured sources: " + _format_list(report["optional_configured_sources"]),
        "Disabled sources: " + _format_list(report["disabled_sources"]),
        "External-only sources: " + _format_list(report["external_only_sources"]),
    ]
    _append_missing_configuration(lines, report["missing_configuration"])
    _append_license_review(lines, report["license_review_required"])
    counts = report["provider_counts"]
    lines.append(
        "Provider counts: "
        f"species={counts['species']}, properties={counts['properties']}, "
        f"reactions={counts['reactions']}"
    )
    return "\n".join(lines)


def _append_missing_configuration(lines: list[str], missing: list[dict[str, Any]]) -> None:
    if not missing:
        lines.append("Missing configuration: none")
        return
    lines.append("Missing configuration:")
    for item in missing:
        lines.append(f"  - {item['source']} ({item['section']}): requires {item['required']}")


def _append_license_review(lines: list[str], reviews: list[dict[str, Any]]) -> None:
    if not reviews:
        lines.append("License review required: none")
        return
    lines.append("License review required:")
    for item in reviews:
        lines.append(
            f"  - {item['source']} ({item['catalog_source_id']}): {item.get('notes') or ''}"
        )


def _format_list(items: list[str]) -> str:
    return ", ".join(items) if items else "none"
