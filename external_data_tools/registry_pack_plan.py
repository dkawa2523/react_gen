"""Analyze registry coverage for a requested gas set.

The historical public name still mentions a registry pack.  The analysis is
also used by the data-acquisition planner and therefore reports reusable
species/reaction gaps rather than assuming that a gas mixture must be stored
as a pre-built pack.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plasma_reactgen.application.config import CaseConfig, CaseInfo, ExpansionConfig
from plasma_reactgen.application.diagnostics import build_missing_data
from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.application.network_builder import (
    NetworkBuilderDependencies,
    ReactionNetworkBuilder,
)
from plasma_reactgen.application.reaction_catalog import available_dataset_ids
from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.domain.models import CollisionPair, ReactionNetwork
from plasma_reactgen.infrastructure.file_registry import FileRegistry


def plan_registry_pack(
    *,
    seed_gases: list[str],
    max_depth: int,
    registry_root: str | Path,
) -> dict[str, Any]:
    plan, _, _ = analyze_registry_pack(seed_gases, max_depth, Path(registry_root))
    return plan


def analyze_registry_pack(
    seed_gases: list[str],
    max_depth: int | None,
    registry_root: Path,
) -> tuple[dict[str, Any], ReactionNetwork, FileRegistry]:
    registry = FileRegistry(registry_root)
    config = CaseConfig(
        case=CaseInfo(name="registry_pack_plan"),
        gases=list(seed_gases),
        expansion=ExpansionConfig(max_depth=max_depth),
    )
    network = ReactionNetworkBuilder(
        NetworkBuilderDependencies(registry, registry, registry)
    ).generate(config)
    states = build_state_list(network, registry)
    tasks = build_dnt_tasks(network, asset_exists=registry.asset_exists)
    missing = build_missing_data(network, states, dnt_tasks=tasks)
    missing_pairs = _missing_pairs(network.species, registry)
    missing_cross_sections = _missing_datasets(network, registry, "cross_section")
    missing_rates = _missing_datasets(network, registry, "rate_coefficient")
    missing_properties = _missing_task_properties(tasks)
    plan = {
        "schema_version": 1,
        "seed_gases": list(seed_gases),
        "max_depth": max_depth,
        "registry": str(registry_root),
        "missing_reaction_pairs": missing_pairs,
        "generated_species": _generated_species(network, seed_gases),
        "reactions_missing_cross_sections": missing_cross_sections,
        "reactions_missing_rate_coefficients": missing_rates,
        "ion_neutral_pairs_missing_existing_data": _missing_task_datasets(tasks),
        "dnt_properties_missing": missing_properties,
        "missing_data": [
            {
                "subject_kind": item.subject_kind,
                "subject_id": item.subject_id,
                "field": item.field,
                "severity": item.severity,
            }
            for item in missing
        ],
        "summary": {
            "n_species": len(network.species_nodes),
            "n_reactions": len(network.reactions),
            "n_missing_reaction_pairs": len(missing_pairs),
            "n_reactions_missing_cross_sections": len(missing_cross_sections),
            "n_reactions_missing_rate_coefficients": len(missing_rates),
            "n_dnt_properties_missing": len(missing_properties),
        },
    }
    return plan, network, registry


def _missing_datasets(
    network: ReactionNetwork,
    registry: FileRegistry,
    kind: str,
) -> list[str]:
    return sorted(
        reaction.id
        for reaction in network.reactions
        if _dataset_kind_applies(reaction.family, kind)
        if not available_dataset_ids(reaction, kind, registry.asset_exists)
    )


def _dataset_kind_applies(family: str, kind: str) -> bool:
    """Avoid requiring every numerical representation for every reaction."""

    if kind == "cross_section":
        return family == "electron"
    if kind == "rate_coefficient":
        return family != "electron"
    return False


def _missing_task_datasets(tasks: list[dict[str, Any]]) -> list[str]:
    return sorted(
        task["pair_id"]
        for task in tasks
        if not any(
            item["available"]
            for datasets in task["existing_datasets"].values()
            for item in datasets
        )
    )


def _missing_task_properties(tasks: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            f"{task['pair_id']}:{side}.{name}"
            for task in tasks
            for side, properties in task["required_properties"].items()
            for name, prop in properties.items()
            if not prop["available"]
        }
    )


def _generated_species(network: ReactionNetwork, seed_gases: list[str]) -> list[str]:
    seeds = set(seed_gases)
    return sorted(
        species_id
        for species_id, node in network.species_nodes.items()
        if "reaction_product" in node.roles and species_id not in seeds
    )


def _missing_pairs(species: dict[str, Any], registry: FileRegistry) -> list[str]:
    candidates = _electron_pairs(species)
    candidates.update(_heavy_particle_pairs(species))
    return sorted(pair.key for pair in candidates.values() if not registry.has_pair(pair))


def _electron_pairs(species: dict[str, Any]) -> dict[str, CollisionPair]:
    pairs: dict[str, CollisionPair] = {}
    for species_id, item in species.items():
        if species_id == "e":
            continue
        family = "electron" if item.charge == 0 else "electron_ion"
        pair = CollisionPair(family, "e", species_id)
        pairs[pair.key] = pair
    return pairs


def _heavy_particle_pairs(species: dict[str, Any]) -> dict[str, CollisionPair]:
    pairs: dict[str, CollisionPair] = {}
    ids = sorted(species_id for species_id in species if species_id != "e")
    for index, left_id in enumerate(ids):
        for right_id in ids[index + 1 :]:
            pair = _heavy_particle_pair(left_id, right_id, species)
            if pair is not None:
                pairs[pair.key] = pair
    return pairs


def _heavy_particle_pair(
    left_id: str,
    right_id: str,
    species: dict[str, Any],
) -> CollisionPair | None:
    left = species[left_id]
    right = species[right_id]
    if left.charge == 0 and right.charge == 0:
        return CollisionPair("neutral_neutral", left_id, right_id)
    if left.charge != 0 and right.charge != 0:
        if left.charge * right.charge > 0:
            return None
        return CollisionPair("ion_ion", left_id, right_id)
    ion_id, neutral_id = (left_id, right_id) if left.charge != 0 else (right_id, left_id)
    return CollisionPair("ion_neutral", ion_id, neutral_id)
