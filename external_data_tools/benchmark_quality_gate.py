from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.benchmark_io import read_yaml


def enrichment_quality_gate(prepare_report_path: Path) -> dict[str, Any]:
    """Fail on structural enrichment defects, not ordinary data gaps."""

    if not prepare_report_path.exists():
        return _missing_report_result(prepare_report_path)

    report = read_yaml(prepare_report_path)
    unresolved = _as_list(report.get("unresolved"))
    missing_properties = [
        item
        for item in unresolved
        if isinstance(item, dict) and item.get("kind") == "missing_property"
    ]
    structural = [
        item
        for item in unresolved
        if not isinstance(item, dict) or item.get("kind") != "missing_property"
    ]
    by_category = {
        "non_missing_property_unresolved": len(structural),
        "unavailable_sources": len(_as_list(report.get("unavailable_sources"))),
        "unresolved_reactions": len(_as_list(report.get("unresolved_reactions"))),
        "invalid_or_skipped_reaction_channels": _invalid_channel_count(report),
    }
    structural_count = sum(by_category.values())
    return {
        "passed": structural_count == 0,
        "prepare_report": str(prepare_report_path),
        "structural_unresolved_count": structural_count,
        "normal_missing_property_count": len(missing_properties),
        "by_category": by_category,
    }


def _missing_report_result(path: Path) -> dict[str, Any]:
    return {
        "passed": False,
        "prepare_report": str(path),
        "structural_unresolved_count": 1,
        "normal_missing_property_count": 0,
        "by_category": {"missing_prepare_report": 1},
    }


def _invalid_channel_count(report: dict[str, Any]) -> int:
    return sum(
        1
        for item in _as_list(report.get("reaction_channels_skipped"))
        if isinstance(item, dict) and item.get("reason") != "duplicate_channel"
    )


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


__all__ = ["enrichment_quality_gate"]
