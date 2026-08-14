from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from external_data_tools.benchmark_io import (
    now,
    read_yaml,
    resolve_path,
    write_yaml,
)
from external_data_tools.benchmark_quality_gate import (
    enrichment_quality_gate as _enrichment_quality_gate,
)
from external_data_tools.benchmark_setup import run_setup
from external_data_tools.benchmark_workflow import run_benchmark


def run_benchmarks(config_path: str | Path, only: str | None = None) -> dict[str, Any]:
    config_path = Path(config_path)
    config = read_yaml(config_path)
    benchmarks = _select_benchmarks(config.get("benchmarks"), only)
    results_root = (config_path.parent / "results").resolve()
    setup_report = _run_setup(config.get("setup"), config_path, results_root)
    reports = [
        run_benchmark(
            benchmark,
            config_path=config_path,
            results_root=results_root,
        )
        for benchmark in benchmarks
    ]
    summary = _build_summary(config_path, reports, setup_report, results_root)
    write_yaml(results_root / "summary.yaml", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local react_gen benchmarks.")
    parser.add_argument("config", type=Path, help="benchmark_config.yaml")
    parser.add_argument("--only", default=None, help="run only one benchmark id")
    args = parser.parse_args(argv)

    summary = run_benchmarks(args.config, only=args.only)
    _print_summary(summary)
    return 0 if summary["summary"]["n_failed"] == 0 else 1


def _select_benchmarks(value: Any, only: str | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("benchmark config must contain a benchmarks list")
    selected = [
        item
        for item in value
        if isinstance(item, dict) and (only is None or item.get("id") == only)
    ]
    if only is not None and not selected:
        raise ValueError(f"benchmark id not found: {only}")
    return selected


def _run_setup(
    value: Any,
    config_path: Path,
    results_root: Path,
) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not value:
        return None
    setup_path = resolve_path(value.get("config"), config_path)
    if setup_path is None:
        return None
    report_path = results_root / "setup_report.yaml"
    report, return_code = run_setup(
        setup_path,
        check=True,
        write_report=report_path,
    )
    if return_code != 0 and value.get("require_success", True):
        raise RuntimeError(f"benchmark setup check failed: {setup_path}; report: {report_path}")
    return report


def _build_summary(
    config_path: Path,
    reports: list[dict[str, Any]],
    setup_report: dict[str, Any] | None,
    results_root: Path,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": now(),
        "config": str(config_path),
        "summary": {
            "n_benchmarks": len(reports),
            "n_passed": sum(1 for report in reports if report["passed"]),
            "n_failed": sum(1 for report in reports if not report["passed"]),
        },
        "benchmarks": [_summary_row(report) for report in reports],
    }
    if setup_report is not None:
        summary["setup"] = {
            "report": str(results_root / "setup_report.yaml"),
            "required_data_ready": setup_report["summary"]["required_data_ready"],
        }
    return summary


def _summary_row(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": report["id"],
        "passed": report["passed"],
        "score": report["expectations"]["score"],
        "report": report["report_path"],
        "metrics": report["metrics_path"],
    }


def _print_summary(summary: dict[str, Any]) -> None:
    counts = summary["summary"]
    print(
        f"benchmarks: {counts['n_benchmarks']} run, "
        f"{counts['n_passed']} passed, {counts['n_failed']} failed"
    )
    print(f"summary: {Path(summary['config']).parent / 'results' / 'summary.yaml'}")


__all__ = ["_enrichment_quality_gate", "run_benchmarks"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
