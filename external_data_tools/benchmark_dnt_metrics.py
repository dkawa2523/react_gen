from __future__ import annotations

from collections import Counter
from typing import Any


def dnt_readiness_metrics(
    dnt_tasks: list[dict[str, Any]],
    dnt_summary: dict[str, Any],
    dnt_manifest: dict[str, Any],
) -> dict[str, int | bool]:
    task_count = len(dnt_tasks) or int(dnt_summary.get("n_dnt_pairs", 0))
    property_ready, missing_properties = _property_counts(dnt_tasks, dnt_summary)
    complete_statuses = _complete_statuses(dnt_tasks, dnt_manifest)
    counts = Counter(complete_statuses)
    return {
        "property_ready": property_ready,
        "missing_properties": missing_properties,
        "complete_ready": counts["ready"],
        "ready_with_warnings": counts["ready_with_warnings"],
        "missing_required_data": counts["missing_required_data"],
        "no_dnt_channels": counts["no_dnt_channels"],
        "complete_readiness_available": bool(complete_statuses) or task_count == 0,
    }


def _property_counts(
    tasks: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[int, int]:
    statuses = [
        _nested_status(task, "pair_property_readiness") or _nested_status(task, "readiness")
        for task in tasks
        if isinstance(task, dict)
    ]
    if statuses:
        ready = sum(status == "ready" for status in statuses)
        return ready, len(statuses) - ready
    return (
        int(summary.get("n_ready_pairs", 0)),
        int(summary.get("n_pairs_with_missing_properties", 0)),
    )


def _complete_statuses(
    tasks: list[dict[str, Any]],
    manifest: dict[str, Any],
) -> list[str]:
    statuses = [
        status
        for task in tasks
        if isinstance(task, dict)
        if (status := _nested_status(task, "complete_readiness")) is not None
    ]
    if statuses:
        return statuses
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list):
        return []
    return [str(pair["status"]) for pair in pairs if isinstance(pair, dict) and pair.get("status")]


def _nested_status(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, dict) or value.get("status") is None:
        return None
    return str(value["status"])


__all__ = ["dnt_readiness_metrics"]
