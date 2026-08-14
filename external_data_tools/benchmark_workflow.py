from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from external_data_tools.benchmark_commands import run_reactgen
from external_data_tools.benchmark_expectations import evaluate_expectations
from external_data_tools.benchmark_io import (
    clear_generated_path,
    ensure_under,
    now,
    required_path,
    resolve_path,
    write_yaml,
)
from external_data_tools.benchmark_metrics import collect_metrics
from external_data_tools.benchmark_quality_gate import enrichment_quality_gate


@dataclass(frozen=True)
class BenchmarkPaths:
    case: Path
    registry: Path
    source_profile: Path
    workspace: Path
    output: Path
    expectation: Path | None

    @classmethod
    def from_config(
        cls,
        benchmark: dict[str, Any],
        config_path: Path,
    ) -> BenchmarkPaths:
        return cls(
            case=required_path(benchmark.get("case"), config_path, "case"),
            registry=required_path(
                benchmark.get("registry", "registry"),
                config_path,
                "registry",
            ),
            source_profile=required_path(
                benchmark.get("source_profile", "local_only"),
                config_path,
                "source_profile",
            ),
            workspace=required_path(
                benchmark.get("workspace"),
                config_path,
                "workspace",
            ),
            output=required_path(benchmark.get("output"), config_path, "output"),
            expectation=resolve_path(benchmark.get("expectation"), config_path),
        )

    @property
    def prepared_registry(self) -> Path:
        return self.workspace / "prepared_registry"

    @property
    def missing_plan(self) -> Path:
        return self.workspace / "missing_plan.yaml"

    @property
    def manual_inputs(self) -> Path:
        return self.workspace / "manual_inputs"

    @property
    def result_dir(self) -> Path:
        return self.output.parent

    def prepare_outputs(self, results_root: Path) -> None:
        ensure_under(self.workspace, results_root, "workspace")
        ensure_under(self.output, results_root, "output")
        clear_generated_path(self.workspace, results_root, "workspace")
        clear_generated_path(self.output, results_root, "output")
        self.result_dir.mkdir(parents=True, exist_ok=True)


def run_benchmark(
    benchmark: dict[str, Any],
    *,
    config_path: Path,
    results_root: Path,
) -> dict[str, Any]:
    benchmark_id = str(benchmark.get("id") or "")
    if not benchmark_id:
        raise ValueError("benchmark entry missing id")
    paths = BenchmarkPaths.from_config(benchmark, config_path)
    paths.prepare_outputs(results_root)
    steps = _execute_workflow(benchmark, paths, config_path)
    quality_gate = enrichment_quality_gate(paths.workspace / "prepare_report.yaml")
    expectations = evaluate_expectations(paths.output, paths.expectation)
    metrics = collect_metrics(
        paths.output,
        paths.prepared_registry,
        missing_plan=paths.missing_plan,
        expectation_score=expectations["score"],
        structural_enrichment_unresolved_count=quality_gate["structural_unresolved_count"],
    )
    return _write_report(
        benchmark_id,
        paths,
        steps,
        quality_gate,
        expectations,
        metrics,
    )


def _execute_workflow(
    benchmark: dict[str, Any],
    paths: BenchmarkPaths,
    config_path: Path,
) -> list[dict[str, Any]]:
    steps = [
        run_reactgen(
            [
                "enrich",
                str(paths.case),
                "--registry",
                str(paths.registry),
                "--workspace",
                str(paths.workspace),
                "--fresh",
                "--source-profile",
                str(paths.source_profile),
            ]
        )
    ]
    steps.extend(_import_cross_sections(benchmark, paths, config_path))
    mapping = resolve_path(benchmark.get("cross_section_mapping"), config_path)
    if mapping is not None:
        steps.append(
            run_reactgen(
                [
                    "apply-cross-section-mapping",
                    str(mapping),
                    "--workspace",
                    str(paths.workspace),
                ]
            )
        )
    steps.extend(_generation_steps(paths))
    return steps


def _import_cross_sections(
    benchmark: dict[str, Any],
    paths: BenchmarkPaths,
    config_path: Path,
) -> list[dict[str, Any]]:
    steps = []
    for item in _as_list(benchmark.get("cross_section_imports")):
        if isinstance(item, dict):
            steps.append(run_reactgen(_cross_section_args(item, paths, config_path)))
    return steps


def _cross_section_args(
    item: dict[str, Any],
    paths: BenchmarkPaths,
    config_path: Path,
) -> list[str]:
    source_file = required_path(item.get("file"), config_path, "cross-section file")
    args = [
        "import-cross-sections",
        str(source_file),
        "--workspace",
        str(paths.workspace),
        "--source",
        str(item.get("source", "local_file")),
    ]
    for key, option in (
        ("reaction_id", "--reaction-id"),
        ("target", "--target"),
        ("license_note", "--license-note"),
    ):
        if item.get(key):
            args.extend([option, str(item[key])])
    return args


def _generation_steps(paths: BenchmarkPaths) -> list[dict[str, Any]]:
    commands = [
        [
            "generate",
            str(paths.case),
            "--registry",
            str(paths.prepared_registry),
            "--output",
            str(paths.output),
        ],
        [
            "plan-missing",
            str(paths.output),
            "--output",
            str(paths.missing_plan),
        ],
        [
            "template-missing",
            str(paths.output),
            "--output-dir",
            str(paths.manual_inputs),
        ],
    ]
    return [run_reactgen(command) for command in commands]


def _write_report(
    benchmark_id: str,
    paths: BenchmarkPaths,
    steps: list[dict[str, Any]],
    quality_gate: dict[str, Any],
    expectations: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    metrics_path = paths.result_dir / "benchmark_metrics.yaml"
    report_path = paths.result_dir / "benchmark_report.yaml"
    write_yaml(metrics_path, metrics)
    report = {
        "schema_version": 1,
        "id": benchmark_id,
        "case": str(paths.case),
        "registry": str(paths.registry),
        "source_profile": str(paths.source_profile),
        "workspace": str(paths.workspace),
        "output": str(paths.output),
        "generated_at": now(),
        "steps": steps,
        "metrics": metrics,
        "metrics_path": str(metrics_path),
        "expectations": expectations,
        "quality_gate": quality_gate,
        "missing_plan": str(paths.missing_plan),
        "manual_input_templates": str(paths.manual_inputs),
        "passed": _benchmark_passed(steps, quality_gate, expectations, metrics),
        "report_path": str(report_path),
        "constraints": {
            "network_access": "not_used",
            "curated_registry_mutated": False,
        },
    }
    write_yaml(report_path, report)
    return report


def _benchmark_passed(
    steps: list[dict[str, Any]],
    quality_gate: dict[str, Any],
    expectations: dict[str, Any],
    metrics: dict[str, Any],
) -> bool:
    return bool(
        expectations["passed"]
        and quality_gate["passed"]
        and metrics["generation_complete"]
        and all(step["return_code"] == 0 for step in steps)
    )


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


__all__ = ["BenchmarkPaths", "run_benchmark"]
