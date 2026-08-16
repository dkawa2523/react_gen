"""Extract source-independent data-acquisition targets from a generated network."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from plasma_reactgen.application.reaction_catalog import available_dataset_ids
from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.domain.chemistry import property_needs_acquisition
from plasma_reactgen.domain.models import GeneratedReaction, ReactionNetwork
from plasma_reactgen.infrastructure.file_registry import FileRegistry

PROPERTY_UNITS = {
    "mass_amu": "amu",
    "polarizability_A3": "A3",
    "dipole_moment_D": "D",
    "collision_radius_A": "A",
    "enthalpy_formation_eV": "eV",
    "ionization_energy_eV": "eV",
    "electron_affinity_eV": "eV",
}


def collect_acquisition_targets(
    network: ReactionNetwork,
    registry: FileRegistry,
    *,
    seed_gases: list[str],
    pair_candidates: list[str],
) -> dict[str, list[dict[str, Any]]]:
    """Return exact species, reaction, and pair targets without source policy."""

    states = build_state_list(network, registry)
    return {
        "identities": _identity_targets(network, registry.root),
        "properties": _property_targets(network, registry, states),
        "electron_datasets": _electron_dataset_targets(network, registry),
        "heavy_particle_datasets": _heavy_particle_dataset_targets(network, registry),
        "reaction_pair_candidates": _pair_candidate_targets(pair_candidates, seed_gases),
    }


def _identity_targets(network: ReactionNetwork, registry_root: Path) -> list[dict[str, Any]]:
    known = _existing_pubchem_ids(registry_root)
    targets = []
    for species_id in sorted(network.species_nodes):
        species = network.species[species_id]
        if species_id == "e" or species.charge != 0 or species.state.get("kind") != "ground":
            continue
        if species_id in known:
            continue
        query, reviewed = _identity_query(registry_root, species_id)
        targets.append(
            {
                "id": species_id,
                "query": query,
                "query_review_required": not reviewed,
                "purpose": "identity_formula_synonyms_only",
            }
        )
    return targets


def _property_targets(
    network: ReactionNetwork,
    registry: FileRegistry,
    states: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for state in states:
        for name in state["missing_properties"]:
            _add_property(grouped, state["id"], name, "required_species_role", "P0")
    _add_recommended_properties(grouped, states, network, registry)
    return sorted(
        grouped.values(),
        key=lambda item: (item["priority"], item["species"], item["property"]),
    )


def _add_recommended_properties(
    grouped: dict[tuple[str, str], dict[str, Any]],
    states: list[dict[str, Any]],
    network: ReactionNetwork,
    registry: FileRegistry,
) -> None:
    role_rules = registry.get_role_required_properties().get("roles", {})
    for state in states:
        species = network.species[state["id"]]
        recommended = {
            name
            for role in state["roles"]
            for name in role_rules.get(role, {}).get("recommended", [])
        }
        for name in sorted(recommended):
            if property_needs_acquisition(species, name):
                _add_property(grouped, state["id"], name, "recommended_species_role", "P1")


def _add_property(
    grouped: dict[tuple[str, str], dict[str, Any]],
    species_id: str,
    name: str,
    reason: str,
    priority: str,
) -> None:
    key = (species_id, name)
    record = grouped.setdefault(
        key,
        {
            "species": species_id,
            "property": name,
            "unit": PROPERTY_UNITS.get(name),
            "priority": priority,
            "reasons": [],
        },
    )
    if reason not in record["reasons"]:
        record["reasons"].append(reason)


def _electron_dataset_targets(
    network: ReactionNetwork,
    registry: FileRegistry,
) -> list[dict[str, Any]]:
    targets = []
    for reaction in sorted(network.reactions, key=lambda item: item.id):
        if reaction.family != "electron":
            continue
        if available_dataset_ids(reaction, "cross_section", registry.asset_exists):
            continue
        target = _reaction_target(reaction, "cross_section")
        target["available_related_datasets"] = {
            kind: available_dataset_ids(reaction, kind, registry.asset_exists)
            for kind in ("total_ionization_cross_section", "rate_coefficient")
        }
        targets.append(target)
    return targets


def _heavy_particle_dataset_targets(
    network: ReactionNetwork,
    registry: FileRegistry,
) -> list[dict[str, Any]]:
    targets = []
    for reaction in sorted(network.reactions, key=lambda item: item.id):
        if reaction.family == "electron":
            continue
        accepted = _heavy_dataset_kinds(reaction)
        if any(available_dataset_ids(reaction, kind, registry.asset_exists) for kind in accepted):
            continue
        target = _reaction_target(reaction, "one_of")
        target["accepted_dataset_kinds"] = accepted
        targets.append(target)
    return targets


def _heavy_dataset_kinds(reaction: GeneratedReaction) -> list[str]:
    if reaction.family == "ion_neutral" and reaction.type == "elastic":
        return ["cross_section", "mobility"]
    if reaction.family == "ion_neutral":
        return ["rate_coefficient", "cross_section"]
    if reaction.family == "electron_ion":
        return ["rate_coefficient", "cross_section"]
    return ["rate_coefficient"]


def _reaction_target(reaction: GeneratedReaction, missing_kind: str) -> dict[str, Any]:
    return {
        "reaction_id": reaction.id,
        "pair_key": reaction.source_pair_key,
        "family": reaction.family,
        "process": reaction.type,
        "equation": reaction.equation,
        "target": reaction.source_pair_key.rsplit("|", 1)[-1],
        "products": [item.species for item in reaction.products],
        "threshold_eV": reaction.threshold_eV,
        "missing_dataset_kind": missing_kind,
    }


def _pair_candidate_targets(
    pair_keys: list[str],
    seed_gases: list[str],
) -> list[dict[str, Any]]:
    seeds = set(seed_gases)
    targets = []
    for key in pair_keys:
        family, projectile, target = key.split("|", 2)
        priority = _pair_priority(family, projectile, target, seeds)
        if priority == "P3":
            continue
        targets.append(
            {
                "pair_key": key,
                "family": family,
                "projectile": projectile,
                "target": target,
                "priority": priority,
                "status": "candidate_requires_channel_evidence",
            }
        )
    return targets


def _pair_priority(family: str, projectile: str, target: str, seeds: set[str]) -> str:
    if family in {"electron", "electron_ion"}:
        return "P1"
    if family == "ion_ion":
        return "P1"
    if family == "ion_neutral" and target in seeds:
        return "P1"
    if projectile in seeds or target in seeds:
        return "P2"
    return "P3"


def _identity_query(registry_root: Path, species_id: str) -> tuple[str, bool]:
    path = registry_root / "species" / f"{species_id}.yaml"
    payload = _read_yaml(path)
    aliases = payload.get("aliases", [])
    if isinstance(aliases, list) and aliases:
        return str(aliases[0]), True
    display_name = payload.get("display_name")
    if display_name and display_name != species_id:
        return str(display_name), True
    return species_id, False


def _existing_pubchem_ids(registry_root: Path) -> set[str]:
    snapshot = registry_root.parent / "external_data" / "snapshots" / "pubchem_species.yaml"
    payload = _read_yaml(snapshot)
    records = payload.get("records", [])
    if not isinstance(records, list):
        return set()
    return {
        str(record["species"])
        for record in records
        if isinstance(record, dict) and record.get("species")
    }


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


__all__ = ["collect_acquisition_targets"]
