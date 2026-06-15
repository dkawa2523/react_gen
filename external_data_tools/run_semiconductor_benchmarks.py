from __future__ import annotations

from pathlib import Path
from typing import Any
import argparse
import sys

import yaml

from external_data_tools.benchmark_report import generate_benchmark_report
from external_data_tools.benchmark_runner import run_benchmarks
from external_data_tools.benchmark_setup import run_setup

_LOCAL_SRC = Path(__file__).resolve().parents[1] / "src"
if _LOCAL_SRC.exists() and str(_LOCAL_SRC) not in sys.path:
    sys.path.insert(0, str(_LOCAL_SRC))

from plasma_reactgen.interface.cli import main as reactgen_main


DEFAULT_CONFIG = Path("benchmarks/benchmark_config_semiconductor.yaml")
DEFAULT_CASE_IDS = [
    "ar_o2_simple",
    "ar_cf4_fluorocarbon",
    "sf6_o2_electronegative",
]


def run_semiconductor_benchmarks(
    config: str | Path = DEFAULT_CONFIG,
    *,
    only: str | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    config_path = Path(config)
    config_payload = _read_yaml(config_path)
    selected_ids = _selected_case_ids(config_payload, only)
    results_root = (config_path.parent / "results").resolve()
    setup_report_path = results_root / "setup_report.yaml"

    setup_result = _run_setup_check(config_payload, config_path, setup_report_path)
    if setup_result["return_code"] != 0:
        return {
            "schema_version": 1,
            "return_code": 1,
            "config": str(config_path),
            "cases": selected_ids,
            "setup_report": str(setup_report_path),
            "summary": None,
            "semiconductor_report": None,
            "plots": {},
            "case_reports": {},
            "missing_plans": {},
            "manual_inputs": {},
            "strict_failures": [],
            "error": "required benchmark setup check failed",
            "solver_skipped": False,
        }

    summary = run_benchmarks(config_path, only=only)
    summary_path = config_path.parent / "results" / "summary.yaml"

    plots = _generate_plots(summary_path)
    report_path = results_root / "semiconductor_benchmark_report.md"
    generate_benchmark_report(summary_path, report_path)

    artifacts = _collect_artifacts(summary_path)
    strict_failures = _strict_failures(artifacts["case_reports"]) if strict else []
    missing_outputs = _missing_required_outputs(summary_path, artifacts)
    solver_skipped = _solver_skipped(artifacts["case_reports"])
    return_code = 0
    error = None
    if summary["summary"]["n_failed"] > 0:
        return_code = 1
        error = "benchmark runner reported failed cases"
    elif missing_outputs:
        return_code = 1
        error = "required benchmark outputs are missing"
    elif strict_failures:
        return_code = 1
        error = "strict benchmark checks failed"

    return {
        "schema_version": 1,
        "return_code": return_code,
        "config": str(config_path),
        "cases": selected_ids,
        "setup_report": str(setup_report_path),
        "summary": str(summary_path),
        "semiconductor_report": str(report_path),
        "plots": plots,
        "case_reports": {case_id: str(path) for case_id, path in artifacts["case_report_paths"].items()},
        "missing_plans": {case_id: str(path) for case_id, path in artifacts["missing_plans"].items()},
        "manual_inputs": {case_id: str(path) for case_id, path in artifacts["manual_inputs"].items()},
        "strict_failures": strict_failures,
        "missing_outputs": [str(path) for path in missing_outputs],
        "solver_skipped": solver_skipped,
        "error": error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local semiconductor benchmark workflow end to end.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="benchmark config YAML")
    parser.add_argument("--only", choices=DEFAULT_CASE_IDS, default=None, help="run only one default semiconductor case")
    parser.add_argument("--strict", action="store_true", help="fail on low expectation score or validation errors")
    args = parser.parse_args(argv)

    result = run_semiconductor_benchmarks(args.config, only=args.only, strict=args.strict)
    _print_result(result)
    return int(result["return_code"])


def _run_setup_check(config: dict[str, Any], config_path: Path, setup_report_path: Path) -> dict[str, Any]:
    setup = config.get("setup") if isinstance(config.get("setup"), dict) else {}
    setup_config = setup.get("config") if isinstance(setup, dict) else None
    if not setup_config:
        return {"return_code": 0}
    report, return_code = run_setup(
        _resolve_path(setup_config, config_path),
        check=True,
        write_report=setup_report_path,
    )
    return {"return_code": return_code, "report": report}


def _generate_plots(summary_path: Path) -> dict[str, str]:
    summary = _read_yaml(summary_path)
    plots: dict[str, str] = {}
    for row in _as_list(summary.get("benchmarks")):
        report_path = Path(str(row.get("report")))
        report = _read_yaml(report_path)
        case_id = str(row.get("id"))
        output_dir = Path(str(report.get("output")))
        if not output_dir.exists():
            continue
        rc = reactgen_main(["visualize", str(output_dir)])
        if rc != 0:
            raise RuntimeError(f"visualization failed for {case_id}: {output_dir}")
        plots[case_id] = str(output_dir / "visualizations")
    return plots


def _collect_artifacts(summary_path: Path) -> dict[str, dict[str, Path]]:
    summary = _read_yaml(summary_path)
    case_reports: dict[str, dict[str, Any]] = {}
    case_report_paths: dict[str, Path] = {}
    missing_plans: dict[str, Path] = {}
    manual_inputs: dict[str, Path] = {}
    for row in _as_list(summary.get("benchmarks")):
        case_id = str(row.get("id"))
        report_path = Path(str(row.get("report")))
        report = _read_yaml(report_path)
        case_reports[case_id] = report
        case_report_paths[case_id] = report_path
        if report.get("missing_plan"):
            missing_plans[case_id] = Path(str(report["missing_plan"]))
        if report.get("manual_input_templates"):
            manual_inputs[case_id] = Path(str(report["manual_input_templates"]))
    return {
        "case_reports": case_reports,
        "case_report_paths": case_report_paths,
        "missing_plans": missing_plans,
        "manual_inputs": manual_inputs,
    }


def _missing_required_outputs(summary_path: Path, artifacts: dict[str, dict[str, Path]]) -> list[Path]:
    missing: list[Path] = []
    if not summary_path.exists():
        missing.append(summary_path)
    for path in artifacts["case_report_paths"].values():
        if not path.exists():
            missing.append(path)
    for path in artifacts["missing_plans"].values():
        if not path.exists():
            missing.append(path)
    for path in artifacts["manual_inputs"].values():
        if not path.exists() or not (path / "README.md").exists():
            missing.append(path)
    return missing


def _strict_failures(case_reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for case_id, report in case_reports.items():
        metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
        score = _float(metrics.get("expectation_score"))
        validation_errors = _int(metrics.get("validation_error_count"))
        if score < 0.75:
            failures.append({"case": case_id, "reason": "expectation_score_below_threshold", "value": score})
        if validation_errors > 0:
            failures.append({"case": case_id, "reason": "validation_errors", "value": validation_errors})
    return failures


def _solver_skipped(case_reports: dict[str, dict[str, Any]]) -> bool:
    for report in case_reports.values():
        metrics = report.get("metrics", {}) if isinstance(report.get("metrics"), dict) else {}
        summary = metrics.get("solver_status_summary", {})
        if not isinstance(summary, dict):
            continue
        for key in ("disabled", "skipped_missing_executable", "skipped_missing_adapter", "skipped_missing_input_adapter"):
            if _int(summary.get(key)) > 0:
                return True
    return False


def _selected_case_ids(config: dict[str, Any], only: str | None) -> list[str]:
    ids = [
        str(item.get("id"))
        for item in _as_list(config.get("benchmarks"))
        if isinstance(item, dict) and (only is None or item.get("id") == only)
    ]
    return ids


def _print_result(result: dict[str, Any]) -> None:
    print("Semiconductor benchmark workflow")
    print("  cases:")
    for case_id in result["cases"]:
        print(f"    - {case_id}")
    if result.get("solver_skipped"):
        print("External solvers skipped because no executable paths are configured. This is expected for registry-level benchmark runs.")
    print(f"  setup_report: {result['setup_report']}")
    print(f"  summary: {result['summary']}")
    print(f"  semiconductor_report: {result['semiconductor_report']}")
    for case_id in result["cases"]:
        if case_id in result["plots"]:
            print(f"  {case_id} plots: {result['plots'][case_id]}")
        if case_id in result["case_reports"]:
            print(f"  {case_id} benchmark_report: {result['case_reports'][case_id]}")
        if case_id in result["missing_plans"]:
            print(f"  {case_id} missing_plan: {result['missing_plans'][case_id]}")
        if case_id in result["manual_inputs"]:
            print(f"  {case_id} manual_inputs: {result['manual_inputs'][case_id]}")
    if result.get("strict_failures"):
        print("  strict_failures:")
        for item in result["strict_failures"]:
            print(f"    - {item['case']}: {item['reason']}={item['value']}")
    if result.get("error"):
        print(f"  error: {result['error']}")


def _resolve_path(value: Any, config_path: Path) -> Path:
    path = Path(str(value))
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists() or path.parts[:1] in {("benchmarks",), ("external_data",), ("external_data_tools")}:
        return cwd_candidate
    return (config_path.parent / path).resolve()


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return payload


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
