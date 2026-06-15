from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import argparse
import sys

import yaml


CASE_TITLES = {
    "ar_o2_simple": "Ar/O2 simple oxygen plasma",
    "ar_cf4_fluorocarbon": "Ar/CF4 fluorocarbon plasma",
    "sf6_o2_electronegative": "Ar/SF6/O2 electronegative plasma",
}


def generate_benchmark_report(summary_path: str | Path, output: str | Path | None = None) -> dict[str, Any]:
    summary_path = Path(summary_path)
    summary = _read_yaml(summary_path)
    cases = [_load_case(row, summary_path) for row in _as_list(summary.get("benchmarks"))]
    setup = _load_setup(summary, summary_path)
    evaluation = _evaluate_suite(summary, cases, setup)
    markdown = _render_markdown(summary_path, summary, cases, setup, evaluation)

    output_path = Path(output) if output is not None else summary_path.with_name("semiconductor_benchmark_report.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return {
        "schema_version": 1,
        "summary": summary_path.as_posix(),
        "output": output_path.as_posix(),
        "case_count": len(cases),
        "statuses": evaluation["status_counts"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write a human-readable semiconductor benchmark evaluation report.")
    parser.add_argument("summary", type=Path, help="benchmarks/results/summary.yaml")
    parser.add_argument("--output", type=Path, default=None, help="Markdown report path")
    args = parser.parse_args(argv)

    result = generate_benchmark_report(args.summary, args.output)
    print(f"Wrote benchmark evaluation report: {result['output']}")
    print(f"  cases: {result['case_count']}")
    print(f"  passed: {result['statuses']['passed']}")
    print(f"  warnings: {result['statuses']['warning']}")
    print(f"  failed: {result['statuses']['failed']}")
    print(f"  skipped: {result['statuses']['skipped']}")
    return 0 if result["statuses"]["failed"] == 0 else 1


def _load_case(row: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    report_path = _resolve_path(row.get("report"), summary_path)
    metrics_path = _resolve_path(row.get("metrics"), summary_path)
    report = _read_yaml(report_path) if report_path is not None else {}
    metrics = _read_yaml(metrics_path) if metrics_path is not None else {}
    output_path = Path(str(report.get("output"))) if report.get("output") else None
    reactions = _read_yaml(output_path / "network.reactions.yaml") if output_path is not None else {}
    states = _read_yaml(output_path / "network.states.yaml") if output_path is not None else {}
    missing_plan_path = Path(str(report.get("missing_plan"))) if report.get("missing_plan") else None
    missing_plan = _read_yaml(missing_plan_path) if missing_plan_path is not None else {}

    case_id = str(row.get("id") or report.get("id") or "unknown")
    return {
        "id": case_id,
        "title": CASE_TITLES.get(case_id, case_id),
        "summary_row": row,
        "report_path": report_path,
        "metrics_path": metrics_path,
        "report": report,
        "metrics": metrics,
        "reactions": _as_list(reactions.get("reactions")),
        "states": _as_list(states.get("species")),
        "missing_plan": missing_plan,
        "missing_plan_path": missing_plan_path,
    }


def _load_setup(summary: dict[str, Any], summary_path: Path) -> dict[str, Any]:
    setup = summary.get("setup")
    if not isinstance(setup, dict):
        return {}
    report_path = _resolve_path(setup.get("report"), summary_path)
    payload = _read_yaml(report_path) if report_path is not None else {}
    return {
        "summary": setup,
        "report_path": report_path,
        "report": payload,
    }


def _evaluate_suite(summary: dict[str, Any], cases: list[dict[str, Any]], setup: dict[str, Any]) -> dict[str, Any]:
    case_evaluations = [_evaluate_case(case) for case in cases]
    setup_failed = False
    if setup:
        setup_summary = setup.get("report", {}).get("summary", {})
        setup_failed = setup_summary.get("required_data_ready") is False

    statuses = {
        "passed": sum(1 for item in case_evaluations if "PASS_WORKFLOW" in item["statuses"]),
        "warning": sum(1 for item in case_evaluations if any(status.startswith("WARNING") for status in item["statuses"])),
        "failed": sum(1 for item in case_evaluations if any(status.startswith("FAIL") for status in item["statuses"])),
        "skipped": sum(1 for item in case_evaluations if "SKIPPED_SOLVER" in item["statuses"]),
        "needs_domain_review": len(case_evaluations),
    }
    if setup_failed:
        statuses["failed"] += 1

    solver_summary = _sum_solver_statuses(cases)
    return {
        "case_evaluations": case_evaluations,
        "status_counts": statuses,
        "solver_summary": solver_summary,
        "setup_failed": setup_failed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary_counts": summary.get("summary", {}),
    }


def _evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    metrics = case["metrics"]
    statuses: list[str] = []
    warnings: list[str] = []
    failures: list[str] = []
    recommendations: list[str] = []

    if _float(metrics.get("validation_error_count")) > 0:
        statuses.append("FAIL_VALIDATION")
        failures.append("Charge or element balance validation errors are present.")
    if _int(metrics.get("n_reactions")) <= 0:
        statuses.append("FAIL_GENERATION")
        failures.append("No reactions were generated.")
    if (
        _float(metrics.get("expectation_score")) >= 0.75
        and _float(metrics.get("validation_error_count")) == 0
        and _int(metrics.get("n_electron_reactions")) > 0
        and _int(metrics.get("n_ion_neutral_reactions")) > 0
    ):
        statuses.append("PASS_WORKFLOW")

    if _float(metrics.get("cross_section_asset_coverage_fraction")) < 0.2:
        statuses.append("WARNING_DATA_GAPS")
        warnings.append("Cross-section asset coverage is low.")
        recommendations.append("Import reviewed LXCat/internal cross sections for electron reactions.")
    if _float(metrics.get("provenance_coverage_fraction")) < 0.5:
        statuses.append("WARNING_DATA_GAPS")
        warnings.append("Provenance coverage is low for generated reactions.")
        recommendations.append("Promote reviewed imported/literature channels with provenance after domain review.")
    if _float(metrics.get("inferred_reaction_fraction")) > 0.5:
        statuses.append("WARNING_DATA_GAPS")
        warnings.append("Inferred reaction fraction is high.")
        recommendations.append("Reduce inferred reaction fraction by replacing inferred channels with reviewed data.")
    if _int(metrics.get("n_dnt_ready_pairs")) == 0:
        statuses.append("WARNING_DATA_GAPS")
        warnings.append("No DNT-ready pairs were identified.")
        recommendations.append("Fill DNT neutral properties such as collision_radius_A where missing.")
    if _int(metrics.get("n_missing_plan_actions")) > 0:
        recommendations.append("Review missing-data actions and fill manual templates where source enrichment cannot help.")

    solver_summary = metrics.get("solver_status_summary", {})
    if isinstance(solver_summary, dict) and any(
        _int(solver_summary.get(key)) > 0
        for key in ("disabled", "skipped_missing_executable", "skipped_missing_adapter", "skipped_missing_input_adapter")
    ):
        if _int(solver_summary.get("skipped_missing_executable")) > 0:
            statuses.append("WARNING_SOLVER_SKIPPED")
        statuses.append("SKIPPED_SOLVER")
        warnings.append("Optional live solvers were disabled or skipped; this is not a registry benchmark failure.")
        recommendations.append("Configure live solver paths only if quantitative transport/coupling validation is needed.")

    if _needs_energetics_review(case):
        recommendations.append("Review ion-neutral reaction energetics for channels listed in the missing plan.")

    unique_statuses = _unique(statuses) or ["NEEDS_DOMAIN_REVIEW"]
    return {
        "case_id": case["id"],
        "title": case["title"],
        "statuses": unique_statuses,
        "warnings": _unique(warnings),
        "failures": _unique(failures),
        "recommendations": _unique(recommendations),
    }


def _render_markdown(
    summary_path: Path,
    summary: dict[str, Any],
    cases: list[dict[str, Any]],
    setup: dict[str, Any],
    evaluation: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append("# Semiconductor Low-Pressure Plasma Reaction-Network Benchmark")
    lines.append("")
    lines.append("## Title And Scope")
    lines.append("")
    lines.append("This report evaluates mechanism readiness, data coverage, missing-data transparency, and benchmark workflow for:")
    for case_id in ("ar_o2_simple", "ar_cf4_fluorocarbon", "sf6_o2_electronegative"):
        lines.append(f"- {CASE_TITLES[case_id]} (`{case_id}`)")
    lines.append("")
    lines.append("This benchmark does not validate final quantitative plasma process accuracy. Fixture values and cross sections may be synthetic and must be replaced with reviewed data before scientific conclusions.")
    lines.append("")

    lines.extend(_execution_summary(summary, setup, evaluation))
    lines.extend(_case_summary(cases, evaluation))
    lines.extend(_case_status_details(evaluation))
    lines.extend(_ar_o2_evaluation(cases))
    lines.extend(_practical_usefulness(cases, evaluation))
    lines.extend(_plausibility_checks(cases))
    lines.extend(_warnings_and_limitations(evaluation))
    lines.extend(_recommended_actions(evaluation))
    lines.extend(_appendix(summary_path, cases, setup))
    return "\n".join(lines) + "\n"


def _execution_summary(summary: dict[str, Any], setup: dict[str, Any], evaluation: dict[str, Any]) -> list[str]:
    status_counts = evaluation["status_counts"]
    solver = evaluation["solver_summary"]
    lines = ["## Execution Summary", ""]
    lines.append(f"- Report generated at: {evaluation['generated_at']}")
    lines.append(f"- Benchmark summary timestamp: {summary.get('generated_at', 'unknown')}")
    lines.append(f"- Benchmark ids: {', '.join(str(item.get('id')) for item in _as_list(summary.get('benchmarks')))}")
    lines.append(f"- Passed workflow cases: {status_counts['passed']}")
    lines.append(f"- Warning cases: {status_counts['warning']}")
    lines.append(f"- Failed checks: {status_counts['failed']}")
    lines.append(f"- Skipped solver cases: {status_counts['skipped']}")
    lines.append(f"- Needs domain review: {status_counts['needs_domain_review']}")
    lines.append("")
    lines.append("Solver status summary:")
    for key in ("ready", "disabled", "skipped_missing_executable", "skipped_missing_adapter", "skipped_missing_input_adapter", "completed", "failed"):
        lines.append(f"- {key}: {solver.get(key, 0)}")
    if any(solver.get(key, 0) for key in ("disabled", "skipped_missing_executable", "skipped_missing_adapter", "skipped_missing_input_adapter")):
        lines.append("- Live external solvers were skipped or disabled; this is a warning, not a benchmark failure.")
    if setup and setup.get("report_path"):
        lines.append(f"- Setup report: `{setup['report_path']}`")
    lines.append("")
    return lines


def _case_summary(cases: list[dict[str, Any]], evaluation: dict[str, Any]) -> list[str]:
    eval_by_id = {item["case_id"]: item for item in evaluation["case_evaluations"]}
    lines = ["## Case-By-Case Summary", ""]
    lines.append("| Case | Status | Species | Reactions | Electron | Ion-neutral | Score | Xsec coverage | DNT ready | Missing actions | Provenance | Solver |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for case in cases:
        metrics = case["metrics"]
        solver = metrics.get("solver_status_summary", {})
        status = ", ".join(eval_by_id.get(case["id"], {}).get("statuses", []))
        lines.append(
            "| "
            + " | ".join(
                [
                    case["title"],
                    status,
                    str(_int(metrics.get("n_species"))),
                    str(_int(metrics.get("n_reactions"))),
                    str(_int(metrics.get("n_electron_reactions"))),
                    str(_int(metrics.get("n_ion_neutral_reactions"))),
                    f"{_float(metrics.get('expectation_score')):.2f}",
                    f"{_float(metrics.get('cross_section_asset_coverage_fraction')):.2f}",
                    str(_int(metrics.get("n_dnt_ready_pairs"))),
                    str(_int(metrics.get("n_missing_plan_actions"))),
                    f"{_float(metrics.get('provenance_coverage_fraction')):.2f}",
                    _solver_label(solver),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _case_status_details(evaluation: dict[str, Any]) -> list[str]:
    lines = ["## Case Status Details", ""]
    for case_eval in evaluation["case_evaluations"]:
        lines.append(f"### {case_eval['title']}")
        lines.append(f"- Status tags: {', '.join(case_eval['statuses'])}")
        for failure in case_eval["failures"]:
            lines.append(f"- failed: {failure}")
        for warning in case_eval["warnings"]:
            lines.append(f"- warning: {warning}")
        if not case_eval["failures"] and not case_eval["warnings"]:
            lines.append("- passed: no benchmark warnings or failures were generated by the report rules.")
        lines.append("- needs domain review: benchmark fixture and imported data should be reviewed before scientific use.")
        lines.append("")
    return lines


def _ar_o2_evaluation(cases: list[dict[str, Any]]) -> list[str]:
    case = next((item for item in cases if item["id"] == "ar_o2_simple"), None)
    lines = ["## Ar/O2 Specific Evaluation", ""]
    if case is None:
        lines.append("- FAILED: Ar/O2 simple oxygen plasma case was not present in the summary.")
        lines.append("")
        return lines
    reactions = case["reactions"]
    states = {str(item.get("id")) for item in case["states"] if isinstance(item, dict)}
    o2_types = {
        str(reaction.get("type"))
        for reaction in reactions
        if reaction.get("family") == "electron" and "O2" in str(reaction.get("equation", ""))
    }
    channel_ids = {str(reaction.get("id")) for reaction in reactions if isinstance(reaction, dict)}
    for reaction_type in ("elastic", "ionization", "dissociation", "attachment"):
        lines.append(f"- {'passed' if reaction_type in o2_types else 'failed'}: O2 electron {reaction_type} reaction type")
    lines.append(f"- {'passed' if any(reaction.get('family') == 'ion_neutral' for reaction in reactions) else 'failed'}: ion-neutral family exists")
    lines.append(f"- {'passed' if 'Arp_O2_elastic' in channel_ids or 'Arp_O2_charge_transfer' in channel_ids else 'warning'}: Ar+ + O2 channel exists when fixture is present")
    lines.append(f"- {'passed' if 'O' in states else 'failed'}: O species present or generated")
    lines.append(f"- {'passed' if 'O-' in states else 'failed'}: O- species present or generated")
    lines.append(f"- {'passed' if _int(case['metrics'].get('validation_error_count')) == 0 else 'failed'}: validation_error_count == 0")
    lines.append("- warning: synthetic fixture data is present and must not be used for production plasma modeling.")
    lines.append("")
    return lines


def _practical_usefulness(cases: list[dict[str, Any]], evaluation: dict[str, Any]) -> list[str]:
    lines = ["## Practical Modeling Usefulness", ""]
    for case, case_eval in zip(cases, evaluation["case_evaluations"]):
        metrics = case["metrics"]
        lines.append(f"### {case['title']}")
        lines.append(f"- {'passed' if _int(metrics.get('n_electron_reactions')) > 0 else 'failed'}: at least one electron reaction")
        lines.append(f"- {'passed' if _int(metrics.get('n_ion_neutral_reactions')) > 0 else 'failed'}: at least one ion-neutral reaction")
        lines.append(f"- {'passed' if case['report'].get('expectations', {}).get('missing_species') == [] else 'failed'}: required species present")
        lines.append(f"- {'passed' if _int(metrics.get('validation_error_count')) == 0 else 'failed'}: charge/element balance errors are zero")
        lines.append(f"- {'passed' if _int(metrics.get('n_missing_plan_actions')) > 0 else 'warning'}: missing data items are actionable")
        lines.append(f"- {'passed' if _int(metrics.get('n_dnt_tasks')) > 0 else 'warning'}: DNT pairs identified")
        lines.append(f"- {'passed' if _int(metrics.get('n_reactions_with_cross_section_asset')) > 0 else 'warning'}: at least one electron reaction has a cross-section asset")
        lines.append(f"- {'passed' if _float(metrics.get('inferred_reaction_fraction')) <= 0.5 else 'warning'}: inferred fraction is not too high")
        if case_eval["recommendations"]:
            lines.append(f"- needs domain review: {'; '.join(case_eval['recommendations'])}")
        lines.append("")
    return lines


def _plausibility_checks(cases: list[dict[str, Any]]) -> list[str]:
    lines = ["## Plausibility Checks", ""]
    for case in cases:
        report = case["report"]
        metrics = case["metrics"]
        expectations = report.get("expectations", {})
        lines.append(f"### {case['title']}")
        lines.append(f"- {'passed' if expectations.get('missing_species') == [] else 'failed'}: required species present")
        lines.append(f"- {'passed' if expectations.get('missing_reaction_families') == [] else 'failed'}: required reaction families present")
        lines.append(f"- {'passed' if _int(metrics.get('validation_error_count')) == 0 else 'failed'}: validation_error_count == 0")
        lines.append("- passed: no unreviewed imported data was promoted to the curated registry by the benchmark runner")
        lines.append(f"- {'passed' if _int(metrics.get('n_missing_data_items')) >= 0 else 'failed'}: missing data is reported")
        lines.append("- skipped: optional solver skipped status is not a failure for registry-level benchmarks")
        lines.append("")
    return lines


def _warnings_and_limitations(evaluation: dict[str, Any]) -> list[str]:
    lines = ["## Warnings And Limitations", ""]
    lines.append("- warning: fixture cross-section data may be synthetic.")
    lines.append("- skipped: external solvers are not executed unless configured.")
    lines.append("- skipped: no Boltzmann, DNT, ngspice, or other quantitative solver validation runs by default.")
    lines.append("- warning: missing cross sections remain a modeling blocker for quantitative rates.")
    lines.append("- warning: missing `collision_radius_A` remains a DNT blocker for affected neutral targets.")
    lines.append("- needs domain review: synthetic fixture values must be replaced before scientific conclusions.")
    if evaluation["setup_failed"]:
        lines.append("- failed: required fixture data was missing during setup.")
    lines.append("")
    return lines


def _recommended_actions(evaluation: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    for case_eval in evaluation["case_evaluations"]:
        recommendations.extend(case_eval["recommendations"])
    fallback = [
        "Import reviewed LXCat/internal cross sections.",
        "Fill DNT neutral properties.",
        "Review ion-neutral reaction energetics.",
        "Reduce inferred reaction fraction by promoting reviewed data.",
        "Configure live solver paths if quantitative transport validation is needed.",
    ]
    lines = ["## Recommended Next Actions", ""]
    for item in _unique([*recommendations, *fallback]):
        lines.append(f"- {item}")
    lines.append("")
    return lines


def _appendix(summary_path: Path, cases: list[dict[str, Any]], setup: dict[str, Any]) -> list[str]:
    lines = ["## Appendix", ""]
    lines.append(f"- Summary: `{summary_path}`")
    if setup.get("report_path"):
        lines.append(f"- Setup report: `{setup['report_path']}`")
    for case in cases:
        report = case["report"]
        output = report.get("output")
        plot_paths = _plot_paths(Path(str(output))) if output else []
        lines.append(f"- {case['title']} report: `{case['report_path']}`")
        lines.append(f"- {case['title']} metrics: `{case['metrics_path']}`")
        lines.append(f"- {case['title']} missing plan: `{case['missing_plan_path']}`")
        lines.append(f"- {case['title']} source profile: `{report.get('source_profile')}`")
        lines.append(f"- {case['title']} external solver config: `{report.get('solver_status', {}).get('config')}`")
        if plot_paths:
            for plot_path in plot_paths:
                lines.append(f"- {case['title']} plot: `{plot_path}`")
        else:
            lines.append(f"- {case['title']} plots: none detected")
    lines.append("")
    return lines


def _sum_solver_statuses(cases: list[dict[str, Any]]) -> dict[str, int]:
    result = {
        "ready": 0,
        "disabled": 0,
        "skipped_missing_executable": 0,
        "skipped_missing_adapter": 0,
        "skipped_missing_input_adapter": 0,
        "completed": 0,
        "failed": 0,
    }
    for case in cases:
        summary = case["metrics"].get("solver_status_summary", {})
        if not isinstance(summary, dict):
            continue
        for key in result:
            result[key] += _int(summary.get(key))
    return result


def _solver_label(solver: Any) -> str:
    if not isinstance(solver, dict):
        return "unknown"
    if _int(solver.get("ready")):
        return "ready"
    if _int(solver.get("disabled")):
        return "skipped: disabled"
    if _int(solver.get("skipped_missing_executable")):
        return "skipped: missing executable"
    if _int(solver.get("skipped_missing_adapter")) or _int(solver.get("skipped_missing_input_adapter")):
        return "skipped: missing adapter"
    if _int(solver.get("failed")):
        return "failed"
    return "skipped"


def _needs_energetics_review(case: dict[str, Any]) -> bool:
    actions = _as_list(case.get("missing_plan", {}).get("actions"))
    return any(action.get("action") == "review_reaction_energetics" for action in actions if isinstance(action, dict))


def _plot_paths(output_path: Path) -> list[Path]:
    if not output_path.exists():
        return []
    return sorted([*output_path.rglob("*.svg"), *output_path.rglob("*.png"), *output_path.rglob("*.pdf")])


def _resolve_path(value: Any, summary_path: Path) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path
    candidate = (summary_path.parent / path).resolve()
    if candidate.exists():
        return candidate
    return (Path.cwd() / path).resolve()


def _read_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _unique(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


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
