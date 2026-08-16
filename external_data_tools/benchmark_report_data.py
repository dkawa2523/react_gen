"""Load benchmark artifacts needed by evaluation and report rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.benchmark_io import read_optional_yaml

CASE_TITLES = {
    "ar_o2_simple": "Ar/O2 simple oxygen plasma",
    "ar_cf4_fluorocarbon": "Ar/CF4 fluorocarbon plasma",
    "sf6_o2_electronegative": "Ar/SF6/O2 electronegative plasma",
}


def load_benchmark_report_data(
    summary_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    summary = read_optional_yaml(summary_path)
    cases = [_load_case(row, summary_path) for row in as_list(summary.get("benchmarks"))]
    return summary, cases, _load_setup(summary, summary_path)


def _load_case(row: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    report_path = _resolve_path(row.get("report"), summary_path)
    metrics_path = _resolve_path(row.get("metrics"), summary_path)
    report = read_optional_yaml(report_path)
    metrics = read_optional_yaml(metrics_path)
    output_path = _path_value(report.get("output"))
    missing_plan_path = _path_value(report.get("missing_plan"))
    reactions = read_optional_yaml(output_path / "network.reactions.yaml" if output_path else None)
    states = read_optional_yaml(output_path / "network.states.yaml" if output_path else None)
    case_id = str(row.get("id") or report.get("id") or "unknown")
    return {
        "id": case_id,
        "title": CASE_TITLES.get(case_id, case_id),
        "report_path": report_path,
        "metrics_path": metrics_path,
        "report": report,
        "metrics": metrics,
        "reactions": as_list(reactions.get("reactions")),
        "states": as_list(states.get("species")),
        "missing_plan": read_optional_yaml(missing_plan_path),
        "missing_plan_path": missing_plan_path,
    }


def _load_setup(summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    setup = summary.get("setup")
    if not isinstance(setup, dict):
        return {}
    report_path = _resolve_path(setup.get("report"), summary_path)
    return {"report_path": report_path, "report": read_optional_yaml(report_path)}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _path_value(value: Any) -> Path | None:
    return Path(str(value)) if value else None


def _resolve_path(value: Any, summary_path: Path) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    relative_to_summary = (summary_path.parent / path).resolve()
    return relative_to_summary if relative_to_summary.exists() else (Path.cwd() / path).resolve()
