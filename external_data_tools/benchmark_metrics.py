"""Assemble the stable benchmark metrics artifact from generated outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from external_data_tools.benchmark_dnt_metrics import dnt_readiness_metrics
from external_data_tools.benchmark_io import read_optional_yaml
from external_data_tools.benchmark_reaction_metrics import (
    count_cross_section_assets,
    fraction,
    max_reaction_depth,
    reaction_counts,
    validation_error_count,
)


def collect_metrics(
    output_dir: str | Path,
    prepared_registry: str | Path | None = None,
    *,
    missing_plan: str | Path | None = None,
    expectation_score: float | None = None,
    structural_enrichment_unresolved_count: int | None = None,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    registry_path = Path(prepared_registry) if prepared_registry is not None else None
    plan_path = Path(missing_plan) if missing_plan is not None else None
    payloads = _load_output_payloads(output_dir)
    plan = read_optional_yaml(plan_path)

    reactions = _as_list(payloads["reactions"].get("reactions"))
    states = _as_list(payloads["states"].get("species"))
    missing_data = _as_list(payloads["missing"].get("missing_data"))
    dnt_tasks = _as_list(payloads["dnt"].get("dnt_tasks"))
    reaction_summary = _as_dict(payloads["reactions"].get("summary"))
    coverage_summary = _as_dict(payloads["coverage"].get("summary"))
    dnt_summary = _as_dict(payloads["dnt"].get("summary"))
    readiness = dnt_readiness_metrics(
        dnt_tasks,
        dnt_summary,
        payloads["dnt_manifest"],
    )
    counts = reaction_counts(reactions, registry_path)
    truncations = _as_list(payloads["reactions"].get("truncations"))
    return {
        "schema_version": 1,
        "n_species": len(states) or int(reaction_summary.get("n_species", 0)),
        "n_reactions": counts["total"],
        "n_electron_reactions": counts["electron"],
        "n_ion_neutral_reactions": counts["ion_neutral"],
        "max_depth_reached": int(
            reaction_summary.get("max_depth_reached", max_reaction_depth(reactions))
        ),
        "n_pairs_found": int(coverage_summary.get("n_pairs_found", 0)),
        "n_pairs_missing": int(coverage_summary.get("n_pairs_missing", 0)),
        "n_missing_data_items": len(missing_data),
        "generation_complete": reaction_summary.get("generation_complete", True) is True,
        "n_generation_truncations": len(truncations),
        "n_missing_plan_actions": len(_as_list(plan.get("actions"))),
        "n_dnt_tasks": len(dnt_tasks) or int(dnt_summary.get("n_dnt_pairs", 0)),
        "n_dnt_property_ready_pairs": readiness["property_ready"],
        "n_dnt_complete_ready_pairs": readiness["complete_ready"],
        "n_dnt_ready_with_warnings_pairs": readiness["ready_with_warnings"],
        "n_dnt_pairs_with_missing_properties": readiness["missing_properties"],
        "n_dnt_pairs_missing_required_data": readiness["missing_required_data"],
        "n_dnt_pairs_without_channels": readiness["no_dnt_channels"],
        "dnt_complete_readiness_available": readiness["complete_readiness_available"],
        "n_cross_section_assets": count_cross_section_assets(registry_path),
        "n_reactions_with_cross_section_asset": counts["with_cross_section"],
        "cross_section_asset_coverage_fraction": fraction(
            counts["with_cross_section"],
            counts["electron"],
        ),
        "n_reactions_with_provenance": counts["with_provenance"],
        "provenance_coverage_fraction": fraction(
            counts["with_provenance"],
            counts["total"],
        ),
        "n_inferred_reactions": counts["inferred"],
        "n_imported_reactions": counts["imported"],
        "n_literature_supported_reactions": counts["literature_supported"],
        "inferred_reaction_fraction": fraction(counts["inferred"], counts["total"]),
        "imported_or_literature_supported_fraction": fraction(
            counts["imported_or_literature"],
            counts["total"],
        ),
        "validation_error_count": validation_error_count(reactions, missing_data),
        "structural_enrichment_unresolved_count": int(structural_enrichment_unresolved_count or 0),
        "expectation_score": 1.0 if expectation_score is None else float(expectation_score),
    }


def _load_output_payloads(output_dir: Path) -> dict[str, dict[str, Any]]:
    filenames = {
        "reactions": "network.reactions.yaml",
        "states": "network.states.yaml",
        "coverage": "coverage_report.yaml",
        "missing": "missing_data.yaml",
        "dnt": "dnt_tasks.yaml",
        "dnt_manifest": "dnt_manifest.yaml",
    }
    return {name: read_optional_yaml(output_dir / filename) for name, filename in filenames.items()}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


__all__ = ["collect_metrics"]
