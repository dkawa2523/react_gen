from __future__ import annotations

from pathlib import Path
import json
import yaml
from typing import Any

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.domain.models import MissingDataItem, ReactionNetwork
from plasma_reactgen.infrastructure.serialization import to_plain


def write_yaml_outputs(
    output_dir: str | Path,
    case_config: CaseConfig,
    network: ReactionNetwork,
    states: list[dict],
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_yaml(output_dir / "network.reactions.yaml", _reactions_payload(case_config, network))
    _write_yaml(output_dir / "network.states.yaml", _states_payload(case_config, states))
    _write_yaml(output_dir / "dnt_tasks.yaml", _dnt_tasks_payload(case_config, dnt_tasks))
    _write_yaml(output_dir / "coverage_report.yaml", _coverage_payload(case_config, network))
    _write_yaml(output_dir / "missing_data.yaml", _missing_data_payload(case_config, missing_data))

    summary = _summary_payload(case_config, network, dnt_tasks, missing_data)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_yaml(output_dir / "quality_summary.yaml", _quality_summary_payload(case_config, network, dnt_tasks, missing_data))


def _write_yaml(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _reactions_payload(case_config: CaseConfig, network: ReactionNetwork) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name, "gases": case_config.gases},
        "summary": {
            "n_species": len(network.species_nodes),
            "n_reactions": len(network.reactions),
            "n_electron_reactions": sum(1 for r in network.reactions if r.family == "electron"),
            "n_ion_neutral_reactions": sum(1 for r in network.reactions if r.family == "ion_neutral"),
            "max_depth_reached": max((r.depth for r in network.reactions), default=0),
            "generation_complete": network.generation_complete,
            "n_truncations": len(network.truncations),
        },
        "truncations": _truncations_payload(network),
        "reactions": [to_plain(rxn) for rxn in network.reactions],
    }


def _states_payload(case_config: CaseConfig, states: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "species": states,
    }


def _dnt_tasks_payload(case_config: CaseConfig, dnt_tasks: list[dict]) -> dict:
    property_ready = _count_dnt_status(dnt_tasks, "pair_property_readiness", "ready")
    complete_ready = _count_dnt_status(dnt_tasks, "complete_readiness", "ready")
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "summary": {
            "n_dnt_pairs": len(dnt_tasks),
            # Compatibility alias: historically this meant pair properties only.
            "n_ready_pairs": property_ready,
            "n_property_ready_pairs": property_ready,
            "n_complete_ready_pairs": complete_ready,
            "n_ready_with_warnings_pairs": _count_dnt_status(
                dnt_tasks, "complete_readiness", "ready_with_warnings"
            ),
            "n_pairs_missing_required_data": _count_dnt_status(
                dnt_tasks, "complete_readiness", "missing_required_data"
            ),
            "n_pairs_without_dnt_channels": _count_dnt_status(
                dnt_tasks, "complete_readiness", "no_dnt_channels"
            ),
            "n_pairs_with_missing_properties": len(dnt_tasks) - property_ready,
        },
        "dnt_tasks": dnt_tasks,
    }


def _coverage_payload(case_config: CaseConfig, network: ReactionNetwork) -> dict:
    found = [c for c in network.coverage if c.status == "found"]
    missing = [c for c in network.coverage if c.status == "missing"]
    other = [c for c in network.coverage if c.status not in {"found", "missing"}]
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "summary": {
            "n_pairs_found": len(found),
            "n_pairs_missing": len(missing),
            "n_pairs_other": len(other),
            "generation_complete": network.generation_complete,
            "n_truncations": len(network.truncations),
        },
        "truncations": _truncations_payload(network),
        "pairs": {
            "found": [to_plain(x) for x in found],
            "missing": [to_plain(x) for x in missing],
            "other": [to_plain(x) for x in other],
        },
    }


def _missing_data_payload(case_config: CaseConfig, missing_data: list[MissingDataItem]) -> dict:
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name},
        "missing_data": [to_plain(x) for x in missing_data],
    }


def _summary_payload(
    case_config: CaseConfig,
    network: ReactionNetwork,
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
) -> dict:
    status_counts = _reaction_status_counts(network)
    coverage_counts = _coverage_counts(network)
    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name, "gases": case_config.gases},
        "n_species": len(network.species_nodes),
        "n_reactions": len(network.reactions),
        "n_electron_reactions": sum(1 for r in network.reactions if r.family == "electron"),
        "n_ion_neutral_reactions": sum(1 for r in network.reactions if r.family == "ion_neutral"),
        "n_pairs_found": coverage_counts["found"],
        "n_pairs_missing": coverage_counts["missing"],
        "n_dnt_tasks": len(dnt_tasks),
        "n_missing_data_items": len(missing_data),
        "generation_complete": network.generation_complete,
        "truncations": _truncations_payload(network),
        "n_reactions_with_cross_section_asset": _count_reactions_with_cross_section_asset(network),
        "n_reactions_missing_cross_section": _count_electron_reactions_missing_cross_section(network),
        "n_reactions_with_provenance": _count_reactions_with_provenance(network),
        "n_inferred_reactions": status_counts.get("inferred", 0),
        "n_imported_reactions": status_counts.get("imported", 0),
        "n_literature_supported_reactions": status_counts.get("literature_supported", 0),
        "by_depth": _by_depth_summary(network),
    }


def _quality_summary_payload(
    case_config: CaseConfig,
    network: ReactionNetwork,
    dnt_tasks: list[dict],
    missing_data: list[MissingDataItem],
) -> dict:
    n_reactions = len(network.reactions)
    n_electron = sum(1 for reaction in network.reactions if reaction.family == "electron")
    n_property_ready_dnt = _count_dnt_status(
        dnt_tasks, "pair_property_readiness", "ready"
    )
    complete_dnt_counts = {
        status: _count_dnt_status(dnt_tasks, "complete_readiness", status)
        for status in (
            "ready",
            "ready_with_warnings",
            "missing_required_data",
            "no_dnt_channels",
        )
    }
    n_with_cross_section = _count_reactions_with_cross_section_asset(network)
    n_with_provenance = _count_reactions_with_provenance(network)
    n_inferred = _reaction_status_counts(network).get("inferred", 0)
    cross_section_fraction = _fraction(n_with_cross_section, n_electron)
    provenance_fraction = _fraction(n_with_provenance, n_reactions)
    dnt_missing = len(dnt_tasks) - n_property_ready_dnt

    return {
        "schema_version": 1,
        "case": {"name": case_config.case.name, "gases": case_config.gases},
        "readiness": {
            "mechanism_ready_for_review": bool(
                network.generation_complete
                and n_reactions
                and _validation_error_count(network, missing_data) == 0
            ),
            "generation_complete": network.generation_complete,
            "dnt_ready_pairs": {
                "ready": n_property_ready_dnt,
                "total": len(dnt_tasks),
                "scope": "pair_properties",
            },
            "dnt_complete_readiness": {
                **complete_dnt_counts,
                "total": len(dnt_tasks),
                "scope": "pair_properties_and_channels",
            },
            "cross_section_asset_coverage_fraction": cross_section_fraction,
            "provenance_coverage_fraction": provenance_fraction,
        },
        "top_missing_actions": _top_missing_actions(missing_data),
        "warnings": {
            "generation_truncated": not network.generation_complete,
            "inferred_fraction_high": _fraction(n_inferred, n_reactions) > 0.25,
            "cross_section_coverage_low": bool(n_electron and cross_section_fraction < 0.5),
            "dnt_required_properties_missing": dnt_missing > 0,
            "dnt_channel_inputs_incomplete": bool(
                dnt_tasks
                and complete_dnt_counts["ready"] < len(dnt_tasks)
            ),
        },
        "notes": [
            "Advisory summary only; generation is not blocked by this file.",
            "A truncated generation is never marked mechanism-ready for review.",
            "Cross-section coverage counts electron reactions with registered local asset paths.",
            "DNT pair-property and complete channel-input readiness are reported separately; neither runs a solver.",
        ],
        "truncations": _truncations_payload(network),
    }


def _truncations_payload(network: ReactionNetwork) -> list[dict[str, Any]]:
    return [to_plain(event) for event in network.truncations]


def _coverage_counts(network: ReactionNetwork) -> dict[str, int]:
    return {
        "found": sum(1 for item in network.coverage if item.status == "found"),
        "missing": sum(1 for item in network.coverage if item.status == "missing"),
    }


def _reaction_status_counts(network: ReactionNetwork) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reaction in network.reactions:
        status = str(reaction.data_status.get("reaction", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _count_reactions_with_cross_section_asset(network: ReactionNetwork) -> int:
    return sum(
        1
        for reaction in network.reactions
        if _has_cross_section_asset(reaction.data_status)
    )


def _count_electron_reactions_missing_cross_section(network: ReactionNetwork) -> int:
    return sum(
        1
        for reaction in network.reactions
        if reaction.family == "electron"
        and not _has_cross_section_asset(reaction.data_status)
    )


def _count_reactions_with_provenance(network: ReactionNetwork) -> int:
    return sum(1 for reaction in network.reactions if _has_provenance(reaction.data))


def _has_cross_section_asset(data_status: dict[str, Any]) -> bool:
    return data_status.get("cross_section") == "local_file_registered"


def _has_provenance(data: dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    return any(data.get(key) for key in ("provenance", "source_record", "evidence"))


def _count_dnt_status(dnt_tasks: list[dict], field: str, status: str) -> int:
    count = 0
    for task in dnt_tasks:
        readiness = task.get(field)
        if not isinstance(readiness, dict) and field == "pair_property_readiness":
            readiness = task.get("readiness")
        if isinstance(readiness, dict) and readiness.get("status") == status:
            count += 1
    return count


def _validation_error_count(network: ReactionNetwork, missing_data: list[MissingDataItem]) -> int:
    reaction_errors = sum(
        1
        for reaction in network.reactions
        if any(status == "failed" for status in reaction.validation.values())
    )
    missing_errors = sum(1 for item in missing_data if item.severity == "error")
    return reaction_errors + missing_errors


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


def _top_missing_actions(missing_data: list[MissingDataItem]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for item in missing_data:
        action = _action_for_missing_field(item.field)
        bucket = grouped.setdefault(
            action,
            {
                "action": action,
                "priority": _priority_for_action(action),
                "count": 0,
                "subjects": [],
            },
        )
        bucket["count"] += 1
        if item.subject_id not in bucket["subjects"] and len(bucket["subjects"]) < 10:
            bucket["subjects"].append(item.subject_id)
    return sorted(grouped.values(), key=lambda item: (_priority_sort(item["priority"]), item["action"]))


def _action_for_missing_field(field: str) -> str:
    if field == "registry/species":
        return "seed_species"
    if field in {"data.cross_section", "data.cross_section.path"}:
        return "import_cross_sections"
    if field == "deltaE_products_minus_reactants_eV":
        return "review_reaction_energetics"
    if field in {
        "target.polarizability_A3",
        "target.dipole_moment_D",
        "target.collision_radius_A",
        "neutral.polarizability_A3",
        "neutral.dipole_moment_D",
        "neutral.collision_radius_A",
        "polarizability_A3",
        "dipole_moment_D",
        "collision_radius_A",
        "enthalpy_formation_eV",
    }:
        return "enrich_properties"
    return "manual_review"


def _priority_for_action(action: str) -> str:
    if action in {"seed_species", "enrich_properties", "import_cross_sections"}:
        return "high"
    if action == "review_reaction_energetics":
        return "medium"
    return "low"


def _priority_sort(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 3)


def _fraction(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)
