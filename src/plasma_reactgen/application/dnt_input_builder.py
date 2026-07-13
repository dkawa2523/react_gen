from __future__ import annotations

from copy import deepcopy
from typing import Any

from plasma_reactgen.application.dnt_task_builder import build_dnt_tasks
from plasma_reactgen.domain.identifiers import to_file_key
from plasma_reactgen.domain.models import PropertyValue, ReactionNetwork, Species


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

    pairs = [
        _build_pair_payload(network, task)
        for task in sorted(build_dnt_tasks(network), key=lambda item: item["pair_id"])
    ]

    return {
        "schema_version": 1,
        "pairs": pairs,
        "summary": _summary(pairs),
    }


def _build_pair_payload(
    network: ReactionNetwork,
    task: dict[str, Any],
) -> dict[str, Any]:
    ion_id = task["ion"]
    target_id = task["neutral"]
    projectile = network.species.get(ion_id)
    target = network.species.get(target_id)
    missing_required_properties = _input_property_names(
        task["pair_property_readiness"].get("missing", {})
    )
    channels = [
        _normalized_channel(channel)
        for channel in task["channels"]
        if channel.get("dnt_class")
    ]
    pair_property_readiness = {
        "status": task["pair_property_readiness"]["status"],
        "scope": "pair_properties",
        "missing": missing_required_properties,
    }
    complete_readiness = deepcopy(task["complete_readiness"])
    complete_readiness["missing_required_properties"] = missing_required_properties

    return {
        "schema_version": 1,
        "pair_id": _pair_id(ion_id, target_id),
        "model_variant": task["model_variant"],
        # ``status`` remains the complete-input status used by the manifest.
        "status": complete_readiness["status"],
        "pair_property_readiness": pair_property_readiness,
        "complete_readiness": complete_readiness,
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
    payload = {
        "value": prop.value,
        "unit": prop.unit or PROPERTY_UNITS.get(name),
        "source": prop.source,
    }
    source_record = getattr(prop, "source_record", None)
    if source_record is not None:
        payload["source_record"] = deepcopy(source_record)
    return payload


def _normalized_channel(channel: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(channel)
    payload["products"] = [
        {**product, "species": to_file_key(product["species"])}
        for product in payload.get("products", [])
    ]
    return payload


def _run_config() -> dict[str, Any]:
    return {
        "energy_grid_eV": dict(DEFAULT_ENERGY_GRID_EV),
        "output_cross_section_unit": DEFAULT_OUTPUT_CROSS_SECTION_UNIT,
    }


def _input_property_names(missing: dict[str, list[str]]) -> list[str]:
    prefixes = {"ion": "projectile", "neutral": "target"}
    return [
        f"{prefixes[side]}.{name}"
        for side in ("ion", "neutral")
        for name in missing.get(side, [])
    ]


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
        "property_ready_pairs": sum(
            1
            for pair in pairs
            if pair.get("pair_property_readiness", {}).get("status") == "ready"
        ),
        "complete_ready_pairs": sum(
            1
            for pair in pairs
            if pair.get("complete_readiness", {}).get("status") == "ready"
        ),
        "complete_ready_with_warnings_pairs": sum(
            1
            for pair in pairs
            if pair.get("complete_readiness", {}).get("status") == "ready_with_warnings"
        ),
        **{status: sum(1 for pair in pairs if pair.get("status") == status) for status in READY_STATUSES},
    }
