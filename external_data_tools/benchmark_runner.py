from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import argparse
import shutil
import sys

import yaml

from external_data_tools.benchmark_expectations import evaluate_expectations
from external_data_tools.benchmark_metrics import collect_metrics
from external_data_tools.benchmark_setup import run_setup
from external_data_tools.solver_discovery import check_solver_config

_LOCAL_SRC = Path(__file__).resolve().parents[1] / "src"
if _LOCAL_SRC.exists() and str(_LOCAL_SRC) not in sys.path:
    sys.path.insert(0, str(_LOCAL_SRC))

from plasma_reactgen.interface.cli import main as reactgen_main


def run_benchmarks(config_path: str | Path, only: str | None = None) -> dict[str, Any]:
    config_path = Path(config_path)
    config = _read_yaml(config_path)
    benchmarks = config.get("benchmarks", [])
    if not isinstance(benchmarks, list):
        raise ValueError("benchmark config must contain a benchmarks list")

    results_root = (config_path.parent / "results").resolve()

    setup_report = None
    setup_config = config.get("setup") if isinstance(config.get("setup"), dict) else {}
    if setup_config:
        setup_path = _resolve_path(setup_config.get("config"), config_path)
        if setup_path is not None:
            setup_report, setup_rc = run_setup(
                setup_path,
                check=True,
                write_report=results_root / "setup_report.yaml",
            )
            if setup_rc != 0:
                message = f"benchmark setup check failed: {setup_path}; report: {results_root / 'setup_report.yaml'}"
                if setup_config.get("require_success", True):
                    raise RuntimeError(message)

    selected = [item for item in benchmarks if isinstance(item, dict) and (only is None or item.get("id") == only)]
    if only is not None and not selected:
        raise ValueError(f"benchmark id not found: {only}")

    reports = []
    for benchmark in selected:
        reports.append(_run_one_benchmark(benchmark, config_path=config_path, results_root=results_root))

    summary = {
        "schema_version": 1,
        "generated_at": _now(),
        "config": str(config_path),
        "summary": {
            "n_benchmarks": len(reports),
            "n_passed": sum(1 for report in reports if report["passed"]),
            "n_failed": sum(1 for report in reports if not report["passed"]),
        },
        "benchmarks": [
            {
                "id": report["id"],
                "passed": report["passed"],
                "score": report["expectations"]["score"],
                "report": report["report_path"],
                "metrics": report["metrics_path"],
            }
            for report in reports
        ],
    }
    if setup_report is not None:
        summary["setup"] = {
            "report": str(results_root / "setup_report.yaml"),
            "required_data_ready": setup_report["summary"]["required_data_ready"],
            "required_solvers_ready": setup_report["summary"]["required_solvers_ready"],
        }
    _write_yaml(results_root / "summary.yaml", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run local react_gen benchmarks.")
    parser.add_argument("config", type=Path, help="benchmark_config.yaml")
    parser.add_argument("--only", default=None, help="run only one benchmark id")
    args = parser.parse_args(argv)

    summary = run_benchmarks(args.config, only=args.only)
    _print_summary(summary)
    return 0 if summary["summary"]["n_failed"] == 0 else 1


def _run_one_benchmark(benchmark: dict[str, Any], *, config_path: Path, results_root: Path) -> dict[str, Any]:
    benchmark_id = str(benchmark.get("id") or "")
    if not benchmark_id:
        raise ValueError("benchmark entry missing id")

    case = _resolve_path(benchmark["case"], config_path)
    registry = _resolve_path(benchmark.get("registry", "registry"), config_path)
    source_profile = _resolve_path(benchmark.get("source_profile", "local_only"), config_path)
    workspace = _resolve_path(benchmark["workspace"], config_path)
    output = _resolve_path(benchmark["output"], config_path)
    expectation = benchmark.get("expectation")
    expectation_path = _resolve_path(expectation, config_path) if expectation else None
    solver_status = _collect_solver_status(benchmark, config_path)
    prepared_registry = workspace / "prepared_registry"
    result_dir = output.parent
    missing_plan_path = workspace / "missing_plan.yaml"
    manual_input_dir = workspace / "manual_inputs"

    _ensure_under(workspace, results_root, "workspace")
    _ensure_under(output, results_root, "output")
    _safe_clear(workspace, results_root)
    _safe_clear(output, results_root)
    result_dir.mkdir(parents=True, exist_ok=True)

    steps = []
    steps.append(
        _run_reactgen(
            [
                "enrich",
                str(case),
                "--registry",
                str(registry),
                "--workspace",
                str(workspace),
                "--source-profile",
                str(source_profile),
            ]
        )
    )
    for import_item in _as_list(benchmark.get("cross_section_imports")):
        if not isinstance(import_item, dict):
            continue
        import_args = [
            "import-cross-sections",
            str(_resolve_path(import_item["file"], config_path)),
            "--workspace",
            str(workspace),
            "--source",
            str(import_item.get("source", "local_file")),
        ]
        if import_item.get("reaction_id"):
            import_args.extend(["--reaction-id", str(import_item["reaction_id"])])
        if import_item.get("target"):
            import_args.extend(["--target", str(import_item["target"])])
        if import_item.get("license_note"):
            import_args.extend(["--license-note", str(import_item["license_note"])])
        steps.append(_run_reactgen(import_args))

    if benchmark.get("cross_section_mapping"):
        steps.append(
            _run_reactgen(
                [
                    "apply-cross-section-mapping",
                    str(_resolve_path(benchmark["cross_section_mapping"], config_path)),
                    "--workspace",
                    str(workspace),
                ]
            )
        )

    steps.append(
        _run_reactgen(
            [
                "generate",
                str(case),
                "--registry",
                str(prepared_registry),
                "--output",
                str(output),
                "--export-dnt-inputs",
            ]
        )
    )
    steps.append(
        _run_reactgen(
            [
                "plan-missing",
                str(output),
                "--output",
                str(missing_plan_path),
            ]
        )
    )
    steps.append(
        _run_reactgen(
            [
                "template-missing",
                str(output),
                "--output-dir",
                str(manual_input_dir),
            ]
        )
    )

    expectations = evaluate_expectations(output, expectation_path)
    metrics = collect_metrics(
        output,
        prepared_registry,
        missing_plan=missing_plan_path,
        expectation_score=expectations["score"],
        solver_status_summary=solver_status["summary"],
    )
    metrics_path = result_dir / "benchmark_metrics.yaml"
    report_path = result_dir / "benchmark_report.yaml"
    _write_yaml(metrics_path, metrics)
    live_solver_required = bool(benchmark.get("require_live_solvers", False))
    solver_gate_passed = True
    if live_solver_required:
        solver_gate_passed = not any(
            solver_status["summary"].get(key, 0)
            for key in ("skipped_missing_executable", "skipped_missing_adapter", "skipped_missing_input_adapter")
        )

    report = {
        "schema_version": 1,
        "id": benchmark_id,
        "case": str(case),
        "registry": str(registry),
        "source_profile": str(source_profile),
        "workspace": str(workspace),
        "output": str(output),
        "generated_at": _now(),
        "steps": steps,
        "metrics": metrics,
        "metrics_path": str(metrics_path),
        "expectations": expectations,
        "solver_status": solver_status,
        "missing_plan": str(missing_plan_path),
        "manual_input_templates": str(manual_input_dir),
        "passed": bool(
            expectations["passed"]
            and solver_gate_passed
            and all(step["return_code"] == 0 for step in steps)
        ),
        "report_path": str(report_path),
        "constraints": {
            "network_access": "not_used",
            "solver_execution": "not_used",
            "curated_registry_mutated": False,
        },
    }
    _write_yaml(report_path, report)
    return report


def _run_reactgen(args: list[str]) -> dict[str, Any]:
    rc = reactgen_main(args)
    step = {
        "command": "reactgen " + " ".join(args),
        "return_code": rc,
    }
    if rc != 0:
        raise RuntimeError(f"benchmark command failed: {step['command']}")
    return step


def _collect_solver_status(benchmark: dict[str, Any], config_path: Path) -> dict[str, Any]:
    solver_config_path = _resolve_path(benchmark.get("external_solvers"), config_path)
    if solver_config_path is None or not solver_config_path.exists():
        return {
            "schema_version": 1,
            "solvers": {},
            "summary": _solver_status_summary({}),
            "warning": "solver config not provided",
        }
    raw = _read_yaml(solver_config_path)
    checked = check_solver_config(raw)
    solvers = checked.get("solvers", {})
    return {
        "schema_version": 1,
        "config": str(solver_config_path),
        "solvers": solvers,
        "summary": _solver_status_summary(solvers),
    }


def _solver_status_summary(solvers: dict[str, Any]) -> dict[str, int]:
    summary = {
        "ready": 0,
        "disabled": 0,
        "skipped_missing_executable": 0,
        "skipped_missing_adapter": 0,
        "skipped_missing_input_adapter": 0,
        "completed": 0,
        "failed": 0,
    }
    for solver in solvers.values():
        if not isinstance(solver, dict):
            continue
        status = str(solver.get("status", ""))
        adapter = str(solver.get("adapter", ""))
        if status == "disabled":
            summary["disabled"] += 1
        elif status == "ready" and adapter == "export_only":
            summary["skipped_missing_input_adapter"] += 1
        elif status == "ready":
            summary["ready"] += 1
        elif status == "missing_adapter":
            summary["skipped_missing_adapter"] += 1
        elif status in {"missing_executable", "manual_install_required", "package_install_suggested"}:
            summary["skipped_missing_executable"] += 1
        else:
            summary["failed"] += 1
    return summary


def _resolve_path(value: Any, config_path: Path) -> Path:
    if value is None:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.exists() or path.parts[:1] in {("cases",), ("registry",), ("benchmarks",), ("external_data",)}:
        return cwd_candidate
    return (config_path.parent / path).resolve()


def _ensure_under(path: Path, root: Path, label: str) -> None:
    resolved = path.resolve()
    root = root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"benchmark {label} must be under {root}: {path}") from exc


def _safe_clear(path: Path, root: Path) -> None:
    _ensure_under(path, root, "output path")
    if path.exists():
        shutil.rmtree(path)


def _read_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML file must contain a mapping: {path}")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _print_summary(summary: dict[str, Any]) -> None:
    counts = summary["summary"]
    print(
        f"benchmarks: {counts['n_benchmarks']} run, "
        f"{counts['n_passed']} passed, {counts['n_failed']} failed"
    )
    print(f"summary: {Path(summary['config']).parent / 'results' / 'summary.yaml'}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
