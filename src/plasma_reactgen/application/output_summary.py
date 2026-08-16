from __future__ import annotations

from dataclasses import asdict
from typing import Any

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.missing_actions import (
    action_for_missing_field,
    priority_for_action,
    priority_sort,
)
from plasma_reactgen.application.network_metrics import (
    count_dnt_status,
    count_electron_reactions_missing_cross_section,
    count_reactions_with_cross_section_asset,
    count_reactions_with_provenance,
)
from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork


def build_summary(
    case_config: CaseConfig,
    network: ReactionNetwork,
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
) -> dict[str, Any]:
    status_counts = _reaction_status_counts(network)
    coverage_counts = _coverage_counts(network)
    family_counts = _reaction_family_counts(network)
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name, "gases": case_config.gases},
        "n_species": len(network.species_nodes),
        "n_reactions": len(network.reactions),
        "n_electron_reactions": sum(r.family == "electron" for r in network.reactions),
        "n_ion_neutral_reactions": sum(r.family == "ion_neutral" for r in network.reactions),
        "reactions_by_family": family_counts,
        "n_pairs_found": coverage_counts["found"],
        "n_pairs_missing": coverage_counts["missing"],
        "n_dnt_tasks": len(dnt_tasks),
        "n_missing_data_items": len(missing_data),
        "generation_complete": network.generation_complete,
        "truncations": [asdict(event) for event in network.truncations],
        "n_reactions_with_cross_section_asset": count_reactions_with_cross_section_asset(network),
        "n_reactions_missing_cross_section": count_electron_reactions_missing_cross_section(
            network
        ),
        "n_reactions_with_provenance": count_reactions_with_provenance(network),
        "n_inferred_reactions": status_counts.get("inferred", 0),
        "n_imported_reactions": status_counts.get("imported", 0),
        "n_literature_supported_reactions": status_counts.get("literature_supported", 0),
        "by_depth": _by_depth_summary(network),
    }


def build_quality_summary(
    case_config: CaseConfig,
    network: ReactionNetwork,
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
) -> dict[str, Any]:
    dnt_in_scope = case_config.outputs.dnt_inputs
    measures = _quality_measures(network)
    dnt_readiness = _dnt_readiness(dnt_tasks)

    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name, "gases": case_config.gases},
        "readiness": {
            "mechanism_ready_for_review": _mechanism_ready(network, missing_data),
            "generation_complete": network.generation_complete,
            **dnt_readiness,
            "cross_section_asset_coverage_fraction": measures["cross_section_fraction"],
            "provenance_coverage_fraction": measures["provenance_fraction"],
        },
        "top_missing_actions": _top_missing_actions(missing_data),
        "warnings": _quality_warnings(
            network,
            dnt_tasks,
            dnt_in_scope=dnt_in_scope,
            measures=measures,
            dnt_readiness=dnt_readiness,
        ),
        "notes": [
            "Advisory summary only; generation is not blocked by this file.",
            "A truncated generation is never marked mechanism-ready for review.",
            "Reaction-list readiness is independent of optional DNT and calculated-result inputs.",
            "Cross-section coverage counts electron reactions with registered local asset paths.",
            (
                "DNT pair-property and complete channel-input readiness are reported "
                "separately; neither runs a solver."
            ),
            "DNT gaps become warnings only when outputs.dnt_inputs is explicitly enabled.",
        ],
        "truncations": [asdict(event) for event in network.truncations],
    }


def _quality_measures(network: ReactionNetwork) -> dict[str, int | float]:
    n_reactions = len(network.reactions)
    n_electron = sum(reaction.family == "electron" for reaction in network.reactions)
    n_cross_sections = count_reactions_with_cross_section_asset(network)
    n_provenance = count_reactions_with_provenance(network)
    return {
        "n_reactions": n_reactions,
        "n_electron": n_electron,
        "inferred": _reaction_status_counts(network).get("inferred", 0),
        "cross_section_fraction": _fraction(n_cross_sections, n_electron),
        "provenance_fraction": _fraction(n_provenance, n_reactions),
    }


def _dnt_readiness(dnt_tasks: list[dict]) -> dict[str, dict[str, int | str]]:
    n_property_ready = count_dnt_status(dnt_tasks, "pair_property_readiness", "ready")
    complete = {
        status: count_dnt_status(dnt_tasks, "complete_readiness", status)
        for status in (
            "ready",
            "ready_with_warnings",
            "missing_required_data",
            "no_dnt_channels",
        )
    }
    return {
        "dnt_ready_pairs": {
            "ready": n_property_ready,
            "total": len(dnt_tasks),
            "scope": "pair_properties",
        },
        "dnt_complete_readiness": {
            **complete,
            "total": len(dnt_tasks),
            "scope": "pair_properties_and_channels",
        },
    }


def _mechanism_ready(
    network: ReactionNetwork,
    missing_data: list[MissingDataItem],
) -> bool:
    return bool(
        network.generation_complete
        and network.reactions
        and all(item.status != "missing" for item in network.coverage)
        and _mechanism_validation_error_count(network, missing_data) == 0
    )


def _quality_warnings(
    network: ReactionNetwork,
    dnt_tasks: list[dict],
    *,
    dnt_in_scope: bool,
    measures: dict[str, int | float],
    dnt_readiness: dict[str, dict[str, int | str]],
) -> dict[str, bool]:
    n_tasks = len(dnt_tasks)
    n_property_ready = int(dnt_readiness["dnt_ready_pairs"]["ready"])
    n_complete_ready = int(dnt_readiness["dnt_complete_readiness"]["ready"])
    return {
        "generation_truncated": not network.generation_complete,
        "inferred_fraction_high": (
            _fraction(int(measures["inferred"]), int(measures["n_reactions"])) > 0.25
        ),
        "cross_section_coverage_low": bool(
            measures["n_electron"] and measures["cross_section_fraction"] < 0.5
        ),
        "dnt_required_properties_missing": bool(dnt_in_scope and n_property_ready < n_tasks),
        "dnt_channel_inputs_incomplete": bool(
            dnt_in_scope and n_tasks and n_complete_ready < n_tasks
        ),
    }


def _coverage_counts(network: ReactionNetwork) -> dict[str, int]:
    return {
        "found": sum(item.status == "found" for item in network.coverage),
        "missing": sum(item.status == "missing" for item in network.coverage),
    }


def _reaction_status_counts(network: ReactionNetwork) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reaction in network.reactions:
        status = str(reaction.data_status.get("reaction", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _mechanism_validation_error_count(
    network: ReactionNetwork,
    missing_data: list[MissingDataItem],
) -> int:
    reaction_errors = sum(
        any(status == "failed" for status in reaction.validation.values())
        for reaction in network.reactions
    )
    non_solver_errors = sum(
        item.severity == "error" and item.required_by != "dnt_task" for item in missing_data
    )
    return reaction_errors + non_solver_errors


def _reaction_family_counts(network: ReactionNetwork) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reaction in network.reactions:
        counts[reaction.family] = counts.get(reaction.family, 0) + 1
    return dict(sorted(counts.items()))


def _by_depth_summary(network: ReactionNetwork) -> dict[str, dict[str, int]]:
    by_depth: dict[int, dict[str, int]] = {}
    for reaction in network.reactions:
        bucket = by_depth.setdefault(
            reaction.depth,
            {
                "n_reactions": 0,
                "n_electron_reactions": 0,
                "n_ion_neutral_reactions": 0,
            },
        )
        bucket["n_reactions"] += 1
        if reaction.family == "electron":
            bucket["n_electron_reactions"] += 1
        elif reaction.family == "ion_neutral":
            bucket["n_ion_neutral_reactions"] += 1
    return {str(depth): by_depth[depth] for depth in sorted(by_depth)}


def _top_missing_actions(
    missing_data: list[MissingDataItem],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in missing_data:
        action = action_for_missing_field(item.field)
        bucket = grouped.setdefault(
            action,
            {
                "action": action,
                "priority": priority_for_action(action),
                "count": 0,
                "subjects": [],
            },
        )
        bucket["count"] += 1
        if item.subject_id not in bucket["subjects"] and len(bucket["subjects"]) < 10:
            bucket["subjects"].append(item.subject_id)
    return sorted(
        grouped.values(),
        key=lambda item: (priority_sort(item["priority"]), item["action"]),
    )


def _fraction(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator > 0 else 0.0
