"""Evaluate benchmark metrics independently from report presentation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_SUITE_LIMITATIONS = (
    "Fixture inputs may be synthetic and require reviewed replacements before scientific use.",
    "This benchmark evaluates network readiness, not quantitative solver accuracy.",
)


def evaluate_suite(
    cases: list[dict[str, Any]],
    setup: dict[str, Any],
) -> dict[str, Any]:
    evaluations = [evaluate_case(case) for case in cases]
    setup_failed = _setup_failed(setup)
    status_counts = {
        "passed": sum("PASS_WORKFLOW" in item["statuses"] for item in evaluations),
        "warning": sum(_has_status(item, "WARNING") for item in evaluations),
        "failed": sum(_has_status(item, "FAIL") for item in evaluations) + int(setup_failed),
    }
    return {
        "case_evaluations": evaluations,
        "status_counts": status_counts,
        "setup_failed": setup_failed,
        "limitations": list(_SUITE_LIMITATIONS),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    metrics = case["metrics"]
    statuses: list[str] = []
    failures: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    _evaluate_failures(metrics, statuses, failures)
    if _workflow_passes(metrics):
        statuses.append("PASS_WORKFLOW")
    _evaluate_data_gaps(metrics, statuses, warnings, recommendations)
    if _needs_energetics_review(case):
        recommendations.append(
            "Review ion-neutral reaction energetics for channels listed in the missing plan."
        )
    return {
        "case_id": case["id"],
        "title": case["title"],
        "statuses": unique(statuses) or ["NEEDS_DOMAIN_REVIEW"],
        "warnings": unique(warnings),
        "failures": unique(failures),
        "recommendations": unique(recommendations),
    }


def _evaluate_failures(
    metrics: dict[str, Any],
    statuses: list[str],
    failures: list[str],
) -> None:
    checks = [
        (
            as_float(metrics.get("validation_error_count")) > 0,
            "FAIL_VALIDATION",
            "Charge or element balance validation errors are present.",
        ),
        (
            as_int(metrics.get("structural_enrichment_unresolved_count")) > 0,
            "FAIL_ENRICHMENT",
            "Structural enrichment or configured-source defects remain unresolved.",
        ),
        (
            as_int(metrics.get("n_reactions")) <= 0,
            "FAIL_GENERATION",
            "No reactions were generated.",
        ),
        (
            metrics.get("generation_complete") is False,
            "FAIL_GENERATION",
            "Generation was truncated by a configured limit.",
        ),
    ]
    for failed, status, message in checks:
        if failed:
            statuses.append(status)
            failures.append(message)


def _workflow_passes(metrics: dict[str, Any]) -> bool:
    return (
        as_float(metrics.get("expectation_score")) >= 0.75
        and as_float(metrics.get("validation_error_count")) == 0
        and as_int(metrics.get("structural_enrichment_unresolved_count")) == 0
        and metrics.get("generation_complete", True) is True
        and as_int(metrics.get("n_electron_reactions")) > 0
        and as_int(metrics.get("n_ion_neutral_reactions")) > 0
    )


def _evaluate_data_gaps(
    metrics: dict[str, Any],
    statuses: list[str],
    warnings: list[str],
    recommendations: list[str],
) -> None:
    checks = [
        (
            as_float(metrics.get("cross_section_asset_coverage_fraction")) < 0.2,
            "Cross-section asset coverage is low.",
            "Import reviewed LXCat/internal cross sections for electron reactions.",
        ),
        (
            as_float(metrics.get("provenance_coverage_fraction")) < 0.5,
            "Provenance coverage is low for generated reactions.",
            "Promote reviewed imported/literature channels with provenance after domain review.",
        ),
        (
            as_float(metrics.get("inferred_reaction_fraction")) > 0.5,
            "Inferred reaction fraction is high.",
            "Reduce inferred reaction fraction by replacing inferred channels with reviewed data.",
        ),
        (
            as_int(metrics.get("n_dnt_property_ready_pairs")) == 0,
            "No DNT-ready pairs were identified.",
            "Fill DNT neutral properties such as collision_radius_A where missing.",
        ),
    ]
    for failed, warning, recommendation in checks:
        if failed:
            statuses.append("WARNING_DATA_GAPS")
            warnings.append(warning)
            recommendations.append(recommendation)
    if as_int(metrics.get("n_missing_plan_actions")) > 0:
        recommendations.append(
            "Review missing-data actions and fill manual templates where source "
            "enrichment cannot help."
        )


def _setup_failed(setup: dict[str, Any]) -> bool:
    return (
        bool(setup)
        and setup.get("report", {}).get("summary", {}).get("required_data_ready") is False
    )


def _has_status(evaluation: dict[str, Any], prefix: str) -> bool:
    return any(str(status).startswith(prefix) for status in evaluation["statuses"])


def _needs_energetics_review(case: dict[str, Any]) -> bool:
    actions = case.get("missing_plan", {}).get("actions", [])
    if not isinstance(actions, list):
        return False
    return any(
        action.get("action") == "review_reaction_energetics"
        for action in actions
        if isinstance(action, dict)
    )


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
