from __future__ import annotations

from collections import defaultdict
from typing import Any

from plasma_reactgen.application.dnt_task_builder import infer_ion_neutral_pair
from plasma_reactgen.domain.identifiers import to_file_key
from plasma_reactgen.domain.models import GeneratedReaction, PropertyValue, ReactionNetwork, Species, SpeciesAmount


DNT_PROJECTILE_PROPERTIES = ["mass_amu"]
DNT_TARGET_PROPERTIES = [
    "mass_amu",
    "polarizability_A3",
    "dipole_moment_D",
    "collision_radius_A",
]

PROPERTY_UNITS = {
    "mass_amu": "amu",
    "polarizability_A3": "A3",
    "dipole_moment_D": "D",
    "collision_radius_A": "A",
}

READY_STATUSES = ("ready", "ready_with_warnings", "missing_required_data", "no_dnt_channels")
DEFAULT_ENERGY_GRID_EV = {
    "min": 0.01,
    "max": 100.0,
    "n": 200,
}
DEFAULT_OUTPUT_CROSS_SECTION_UNIT = "cm2"


def build_dnt_inputs(network: ReactionNetwork) -> dict[str, Any]:
    """Build normalized pair-wise DNT+/DNT+DM input payloads.

    The exporter is intentionally calculation-oriented but solver-free. Unknown
    physical values are written as ``None`` and summarized as missing fields
    instead of being replaced with guessed numbers.
    """

    groups: dict[tuple[str, str], list[GeneratedReaction]] = defaultdict(list)
    for rxn in network.reactions:
        if rxn.family != "ion_neutral":
            continue
        pair = infer_ion_neutral_pair(rxn.reactants, network.species)
        if pair is None:
            continue
        groups[pair].append(rxn)

    pairs = [
        _build_pair_payload(network, ion_id, target_id, reactions)
        for (ion_id, target_id), reactions in sorted(
            groups.items(),
            key=lambda item: _pair_id(*item[0]),
        )
    ]

    return {
        "schema_version": 1,
        "pairs": pairs,
        "summary": _summary(pairs),
    }


def _build_pair_payload(
    network: ReactionNetwork,
    ion_id: str,
    target_id: str,
    reactions: list[GeneratedReaction],
) -> dict[str, Any]:
    projectile = network.species.get(ion_id)
    target = network.species.get(target_id)
    dnt_reactions = [rxn for rxn in reactions if rxn.dnt_class]

    missing_required_properties = _missing_required_properties(projectile, target)
    channels = [_channel_payload(rxn) for rxn in dnt_reactions]
    status = _pair_status(missing_required_properties, channels)

    return {
        "schema_version": 1,
        "pair_id": _pair_id(ion_id, target_id),
        "model_variant": _model_variant(target),
        "status": status,
        "projectile": _species_payload(projectile, DNT_PROJECTILE_PROPERTIES),
        "target": _species_payload(target, DNT_TARGET_PROPERTIES),
        "pair_properties": {
            "reduced_mass_amu": _reduced_mass_amu(projectile, target),
            "long_range_model": "ion_induced_dipole",
            "missing_required_properties": missing_required_properties,
        },
        "channels": channels,
        "run_config": _run_config(),
        "provenance": {
            "generated_by": "plasma-reactgen",
            "source_network": "network.reactions.yaml",
        },
    }


def _species_payload(species: Species | None, property_names: list[str]) -> dict[str, Any]:
    if species is None:
        return {
            "id": None,
            "charge": None,
            "mass_amu": None,
            "composition": {},
            "properties": {
                name: _property_payload(None, name)
                for name in property_names
            },
        }

    properties = {
        name: _property_payload(species.properties.get(name), name)
        for name in property_names
    }
    return {
        "id": to_file_key(species.id),
        "charge": species.charge,
        "mass_amu": properties.get("mass_amu", {}).get("value"),
        "composition": species.composition,
        "properties": properties,
    }


def _property_payload(prop: PropertyValue | None, name: str) -> dict[str, Any]:
    if prop is None or prop.value is None:
        return {
            "value": None,
            "unit": PROPERTY_UNITS.get(name),
            "source": "missing",
        }
    return {
        "value": prop.value,
        "unit": prop.unit or PROPERTY_UNITS.get(name),
        "source": prop.source,
    }


def _channel_payload(rxn: GeneratedReaction) -> dict[str, Any]:
    return {
        "reaction_id": rxn.id,
        "type": rxn.type,
        "dnt_class": rxn.dnt_class,
        "products": _amounts_payload(rxn.products),
        "threshold_eV": rxn.threshold_eV,
        "deltaE_products_minus_reactants_eV": rxn.deltaE_products_minus_reactants_eV,
        "status": rxn.data_status.get("reaction"),
        "missing_for_complete_dnt": _channel_missing_for_complete_dnt(rxn),
        "provenance": _channel_provenance(rxn),
    }


def _amounts_payload(amounts: list[SpeciesAmount]) -> list[dict[str, Any]]:
    return [
        {
            "species": to_file_key(amount.species),
            "n": amount.n,
        }
        for amount in amounts
    ]


def _channel_missing_for_complete_dnt(rxn: GeneratedReaction) -> list[str]:
    missing: list[str] = []
    if not rxn.dnt_class:
        missing.append("dnt_class")
    if rxn.threshold_eV is None:
        missing.append("threshold_eV")
    if rxn.deltaE_products_minus_reactants_eV is None:
        missing.append("deltaE_products_minus_reactants_eV")
    return missing


def _channel_provenance(rxn: GeneratedReaction) -> dict[str, Any]:
    provenance = rxn.data.get("provenance")
    if isinstance(provenance, dict):
        return dict(provenance)
    evidence = rxn.data.get("evidence")
    if isinstance(evidence, dict):
        return dict(evidence)
    return {
        "source_type": "registry",
        "source_id": None,
    }


def _run_config() -> dict[str, Any]:
    return {
        "energy_grid_eV": dict(DEFAULT_ENERGY_GRID_EV),
        "output_cross_section_unit": DEFAULT_OUTPUT_CROSS_SECTION_UNIT,
    }


def _missing_required_properties(projectile: Species | None, target: Species | None) -> list[str]:
    missing: list[str] = []

    if projectile is None:
        return [
            "projectile.charge",
            "projectile.mass_amu",
        ]
    if target is None:
        missing.extend(
            [
                "target.mass_amu",
                "target.polarizability_A3",
                "target.dipole_moment_D",
                "target.collision_radius_A",
            ]
        )
        return missing

    if projectile.charge is None:
        missing.append("projectile.charge")
    if _property_value(projectile, "mass_amu") is None:
        missing.append("projectile.mass_amu")

    for name in DNT_TARGET_PROPERTIES:
        if _property_value(target, name) is None:
            missing.append(f"target.{name}")

    return missing


def _pair_status(missing_required_properties: list[str], channels: list[dict[str, Any]]) -> str:
    if missing_required_properties:
        return "missing_required_data"
    if not channels:
        return "no_dnt_channels"
    if any(channel.get("missing_for_complete_dnt") for channel in channels):
        return "ready_with_warnings"
    return "ready"


def _model_variant(target: Species | None) -> str:
    dipole = _property_value(target, "dipole_moment_D") if target is not None else None
    try:
        return "dnt_plus_dm" if dipole is not None and abs(float(dipole)) > 1.0e-12 else "dnt_plus"
    except (TypeError, ValueError):
        return "dnt_plus"


def _reduced_mass_amu(projectile: Species | None, target: Species | None) -> float | None:
    projectile_mass = _as_float(
        _property_value(projectile, "mass_amu") if projectile is not None else None
    )
    target_mass = _as_float(
        _property_value(target, "mass_amu") if target is not None else None
    )
    if projectile_mass is None or target_mass is None:
        return None
    return projectile_mass * target_mass / (projectile_mass + target_mass)


def _property_value(species: Species, name: str):
    prop = species.properties.get(name)
    return None if prop is None else prop.value


def _as_float(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pair_id(ion_id: str, target_id: str) -> str:
    return f"{to_file_key(ion_id)}__{to_file_key(target_id)}"


def _summary(pairs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total_pairs": len(pairs),
        **{status: sum(1 for pair in pairs if pair.get("status") == status) for status in READY_STATUSES},
    }
