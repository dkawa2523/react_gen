from __future__ import annotations

from pathlib import Path
from typing import Any
import sys

import yaml

_LOCAL_SRC = Path(__file__).resolve().parents[1] / "src"
if _LOCAL_SRC.exists() and str(_LOCAL_SRC) not in sys.path:
    sys.path.insert(0, str(_LOCAL_SRC))

from plasma_reactgen.infrastructure.registry_paths import registry_asset_exists


def collect_metrics(
    output_dir: str | Path,
    prepared_registry: str | Path | None = None,
    *,
    missing_plan: str | Path | None = None,
    expectation_score: float | None = None,
    solver_status_summary: dict[str, int] | None = None,
    structural_enrichment_unresolved_count: int | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    prepared_registry_path = Path(prepared_registry) if prepared_registry is not None else None
    missing_plan_path = Path(missing_plan) if missing_plan is not None else None

    reactions_payload = _read_yaml(output_dir / "network.reactions.yaml")
    states_payload = _read_yaml(output_dir / "network.states.yaml")
    coverage_payload = _read_yaml(output_dir / "coverage_report.yaml")
    missing_payload = _read_yaml(output_dir / "missing_data.yaml")
    dnt_payload = _read_yaml(output_dir / "dnt_tasks.yaml")
    dnt_manifest_payload = _read_yaml(output_dir / "dnt_manifest.yaml")
    plan_payload = _read_yaml(missing_plan_path) if missing_plan_path is not None else {}

    reactions = _as_list(reactions_payload.get("reactions"))
    states = _as_list(states_payload.get("species"))
    missing_data = _as_list(missing_payload.get("missing_data"))
    dnt_tasks = _as_list(dnt_payload.get("dnt_tasks"))
    reaction_summary = reactions_payload.get("summary", {}) if isinstance(reactions_payload.get("summary"), dict) else {}
    coverage_summary = coverage_payload.get("summary", {}) if isinstance(coverage_payload.get("summary"), dict) else {}
    dnt_summary = dnt_payload.get("summary", {}) if isinstance(dnt_payload.get("summary"), dict) else {}
    dnt_readiness = _dnt_readiness_metrics(dnt_tasks, dnt_summary, dnt_manifest_payload)
    generation_complete = reaction_summary.get("generation_complete", True) is True
    truncations = _as_list(reactions_payload.get("truncations"))

    n_reactions = len(reactions)
    n_inferred = sum(1 for reaction in reactions if _reaction_status(reaction) == "inferred")
    n_imported = sum(1 for reaction in reactions if _reaction_status(reaction) == "imported")
    n_literature_supported = sum(1 for reaction in reactions if _reaction_status(reaction) == "literature_supported")
    n_imported_or_literature = sum(
        1 for reaction in reactions if _reaction_status(reaction) in {"imported", "literature_supported"}
    )
    n_electron = sum(1 for reaction in reactions if reaction.get("family") == "electron")
    n_ion_neutral = sum(1 for reaction in reactions if reaction.get("family") == "ion_neutral")
    n_with_cross_sections = sum(
        1
        for reaction in reactions
        if _has_cross_section_asset(reaction, prepared_registry_path)
    )
    n_with_provenance = sum(1 for reaction in reactions if _has_provenance(reaction))

    return {
        "schema_version": 1,
        "n_species": len(states) or int(reaction_summary.get("n_species", 0)),
        "n_reactions": n_reactions,
        "n_electron_reactions": n_electron,
        "n_ion_neutral_reactions": n_ion_neutral,
        "max_depth_reached": int(reaction_summary.get("max_depth_reached", _max_depth(reactions))),
        "n_pairs_found": int(coverage_summary.get("n_pairs_found", 0)),
        "n_pairs_missing": int(coverage_summary.get("n_pairs_missing", 0)),
        "n_missing_data_items": len(missing_data),
        "generation_complete": generation_complete,
        "n_generation_truncations": len(truncations),
        "n_missing_plan_actions": len(_as_list(plan_payload.get("actions"))),
        "n_dnt_tasks": len(dnt_tasks) or int(dnt_summary.get("n_dnt_pairs", 0)),
        # Legacy metric: this intentionally remains pair-property readiness.
        "n_dnt_ready_pairs": dnt_readiness["property_ready"],
        "n_dnt_property_ready_pairs": dnt_readiness["property_ready"],
        "n_dnt_complete_ready_pairs": dnt_readiness["complete_ready"],
        "n_dnt_ready_with_warnings_pairs": dnt_readiness["ready_with_warnings"],
        "n_dnt_pairs_with_missing_properties": dnt_readiness["missing_properties"],
        "n_dnt_pairs_missing_required_data": dnt_readiness["missing_required_data"],
        "n_dnt_pairs_without_channels": dnt_readiness["no_dnt_channels"],
        "dnt_complete_readiness_available": dnt_readiness["complete_readiness_available"],
        "dnt_readiness_semantics": {
            "n_dnt_ready_pairs": "legacy alias for n_dnt_property_ready_pairs",
            "property_ready": "required ion/neutral pair properties are present",
            "complete_ready": "pair properties and all required DNT channel fields are present",
            "ready_with_warnings": "pair properties are present but one or more DNT channel fields are missing",
        },
        "n_cross_section_assets": _count_cross_section_assets(prepared_registry_path),
        "n_reactions_with_cross_section_asset": n_with_cross_sections,
        "cross_section_asset_coverage_fraction": _fraction(n_with_cross_sections, n_electron),
        "n_reactions_with_provenance": n_with_provenance,
        "provenance_coverage_fraction": _fraction(n_with_provenance, n_reactions),
        "n_inferred_reactions": n_inferred,
        "n_imported_reactions": n_imported,
        "n_literature_supported_reactions": n_literature_supported,
        "inferred_reaction_fraction": _fraction(n_inferred, n_reactions),
        "imported_or_literature_supported_fraction": _fraction(n_imported_or_literature, n_reactions),
        "validation_error_count": _validation_error_count(reactions, missing_data),
        "structural_enrichment_unresolved_count": int(structural_enrichment_unresolved_count or 0),
        "expectation_score": 1.0 if expectation_score is None else float(expectation_score),
        "solver_status_summary": _solver_summary(solver_status_summary),
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _max_depth(reactions: list[dict[str, Any]]) -> int:
    depths = []
    for reaction in reactions:
        try:
            depths.append(int(reaction.get("depth", 0)))
        except (TypeError, ValueError):
            continue
    return max(depths, default=0)


def _dnt_readiness_metrics(
    dnt_tasks: list[dict[str, Any]],
    dnt_summary: dict[str, Any],
    dnt_manifest: dict[str, Any],
) -> dict[str, Any]:
    task_count = len(dnt_tasks) or int(dnt_summary.get("n_dnt_pairs", 0))
    property_statuses = [
        _nested_status(task, "pair_property_readiness")
        or _nested_status(task, "readiness")
        for task in dnt_tasks
        if isinstance(task, dict)
    ]
    if property_statuses:
        property_ready = sum(status == "ready" for status in property_statuses)
        missing_properties = sum(status != "ready" for status in property_statuses)
    else:
        property_ready = int(dnt_summary.get("n_ready_pairs", 0))
        missing_properties = int(dnt_summary.get("n_pairs_with_missing_properties", 0))

    complete_statuses = [
        status
        for task in dnt_tasks
        if isinstance(task, dict)
        if (status := _nested_status(task, "complete_readiness")) is not None
    ]
    if not complete_statuses:
        complete_statuses = [
            str(pair.get("status"))
            for pair in _as_list(dnt_manifest.get("pairs"))
            if isinstance(pair, dict) and pair.get("status")
        ]

    return {
        "property_ready": property_ready,
        "missing_properties": missing_properties,
        "complete_ready": sum(status == "ready" for status in complete_statuses),
        "ready_with_warnings": sum(status == "ready_with_warnings" for status in complete_statuses),
        "missing_required_data": sum(status == "missing_required_data" for status in complete_statuses),
        "no_dnt_channels": sum(status == "no_dnt_channels" for status in complete_statuses),
        "complete_readiness_available": bool(complete_statuses) or task_count == 0,
    }


def _nested_status(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if not isinstance(value, dict) or value.get("status") is None:
        return None
    return str(value["status"])


def _reaction_status(reaction: dict[str, Any]) -> str | None:
    data_status = reaction.get("data_status")
    if isinstance(data_status, dict):
        return data_status.get("reaction")
    return None


def _has_cross_section_asset(
    reaction: dict[str, Any],
    prepared_registry: Path | None,
) -> bool:
    if prepared_registry is None:
        return False
    data = reaction.get("data")
    if not isinstance(data, dict):
        return False
    cross_section = data.get("cross_section")
    return (
        isinstance(cross_section, dict)
        and registry_asset_exists(prepared_registry, cross_section.get("path"))
    )


def _has_provenance(reaction: dict[str, Any]) -> bool:
    data = reaction.get("data")
    if not isinstance(data, dict):
        return False
    return any(data.get(key) for key in ("provenance", "source_record", "evidence"))


def _count_cross_section_assets(prepared_registry: Path | None) -> int:
    if prepared_registry is None:
        return 0
    assets = prepared_registry / "assets" / "cross_sections"
    if not assets.exists():
        return 0
    return len(list(assets.glob("*.csv")))


def _fraction(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _solver_summary(value: dict[str, int] | None) -> dict[str, int]:
    defaults = {
        "ready": 0,
        "disabled": 0,
        "skipped_missing_executable": 0,
        "skipped_missing_adapter": 0,
        "skipped_missing_input_adapter": 0,
        "completed": 0,
        "failed": 0,
    }
    if isinstance(value, dict):
        for key in defaults:
            try:
                defaults[key] = int(value.get(key, defaults[key]))
            except (TypeError, ValueError):
                defaults[key] = 0
    return defaults


def _validation_error_count(reactions: list[dict[str, Any]], missing_data: list[dict[str, Any]]) -> int:
    reaction_errors = 0
    for reaction in reactions:
        validation = reaction.get("validation")
        if isinstance(validation, dict) and any(value not in {"ok", None} for value in validation.values()):
            reaction_errors += 1
    missing_errors = sum(1 for item in missing_data if isinstance(item, dict) and item.get("severity") == "error")
    return reaction_errors + missing_errors


def _forbidden_violations(reactions: list[dict[str, Any]], forbidden: Any) -> list[dict[str, Any]]:
    if not isinstance(forbidden, dict) or not forbidden.get("reactions_with_failed_balance"):
        return []
    violations = []
    for reaction in reactions:
        if not isinstance(reaction, dict):
            continue
        validation = reaction.get("validation")
        if not isinstance(validation, dict):
            continue
        failed = {
            key: value
            for key, value in validation.items()
            if key in {"charge_balance", "element_balance"} and value not in {"ok", None}
        }
        if failed:
            violations.append({"reaction_id": reaction.get("id"), "validation": failed})
    return violations
