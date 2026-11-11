"""Explicit derived mass and resolved-level formation-energy offsets.

Composition sums neglect chemical binding mass defects; carrying mass across
excitation additionally neglects E/c^2. Electronic response and transport
properties require their own evidence. No equilibrium populations or excited
NASA partition functions are inferred by this operation.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict
from math import isfinite
from pathlib import Path
from typing import cast

from reactgen.evidence import registry_state_candidate
from reactgen.records import (
    Property,
    Species,
    energy_declarations_agree,
    normalized_dataset,
    property_has_point_qualifier,
    relocated_asset_payload,
)
from reactgen.registry import Registry
from reactgen.units import energy_eV as energy_in_eV

ELECTRON_MASS_AMU = 0.000548579909


def _atomic_mass_inputs(registry: Registry) -> dict[str, list[tuple[str, Property]]]:
    offered: dict[str, list[tuple[str, Property]]] = {}
    for species in registry.species.values():
        if species.charge or len(species.composition) != 1:
            continue
        ((element, count),) = species.composition.items()
        if count == 1 and species.state.kind == "ground":
            offered.setdefault(element, []).extend(
                (species.id, prop) for prop in _mass_properties(species)
            )
    return {
        element: sorted(properties, key=lambda item: (item[0], _property_key(item[1])))
        for element, properties in offered.items()
        if properties and len({prop.value for _, prop in properties}) == 1
    }


def mass_of(composition: dict[str, int], charge: int, elements: dict[str, float]) -> float | None:
    """Pure nominal-mass arithmetic; qualification belongs to the caller.

    Chemical binding and excitation mass defects are omitted. Missing element
    inputs return None; invalid supplied numbers are input errors.
    """
    if type(charge) is not int or any(
        type(count) is not int or count <= 0 for count in composition.values()
    ):
        raise ValueError("mass calculation requires integer charge and positive atom counts")
    if not composition or any(element not in elements for element in composition):
        return None
    if any(
        isinstance(elements[element], bool)
        or not isinstance(elements[element], int | float)
        or not isfinite(elements[element])
        or elements[element] <= 0
        for element in composition
    ):
        raise ValueError("mass calculation requires finite positive atomic point masses")
    total = sum(count * elements[element] for element, count in composition.items())
    mass = total - charge * ELECTRON_MASS_AMU
    return round(mass, 6) if isfinite(mass) and mass > 0 else None


def carried_from(parent: Species, excitation: Property | None) -> dict[str, Property]:
    """Nominal mass carry and qualified 0 K resolved-energy offset for `parent`.

    This is an explicit derived-data operation. Registry loading never inserts
    these values implicitly. A resolved level offset is carried into formation
    enthalpy only at 0 K: finite-T changes in vibrational/rotational thermal
    contributions are not supplied by the electronic level energy.
    The Property must describe the identified resolved excitation; its review,
    qualifier and complete declaration are retained rather than accepting a
    bare energy scalar. Mass is independent of whether excitation is available.
    """

    if excitation is not None and not isinstance(excitation, Property):
        raise ValueError("excitation must be a Property record or None")
    out = {}
    masses = _mass_properties(parent)
    if masses and len({prop.value for prop in masses}) == 1:
        out["mass_amu"] = _derived_property(
            "mass_amu",
            masses[0].value,
            "amu",
            f"mass carried from {parent.id}; excitation mass defect is neglected",
            {
                "operation": "excited_mass_approximation",
                "parent_species": parent.id,
                "parent_mass_properties": [asdict(prop) for prop in masses],
                "approximation": "excitation contribution E/c^2 is neglected",
            },
        )
    formation = _zero_k_formation_properties(parent)
    energy_eV = _excitation_value(excitation)
    if formation and excitation is not None and energy_eV is not None:
        prop = formation[0]
        enthalpy = cast(float, energy_in_eV(cast(float, prop.value), prop.unit))
        value = enthalpy + energy_eV
        if not isfinite(value):
            return out
        out["enthalpy_formation_eV"] = Property(
            value=round(value, 6),
            unit="eV",
            source=f"{parent.id} 0 K enthalpy plus the reviewed {energy_eV:.4g} eV level energy",
            tier="derived",
            formation_reference=prop.formation_reference,
            status="derived",
            method="calculated",
            review_scope=("enthalpy_formation_eV",),
            source_declaration={
                "operation": "resolved_level_formation_offset",
                "parent_species": parent.id,
                "parent_formation_enthalpy": asdict(prop),
                "parent_formation_properties": [asdict(item) for item in formation],
                "level_energy_eV": energy_eV,
                "level_property": asdict(excitation),
                "reference_temperature_K": 0.0,
                "uncertainty_propagation": "not evaluated; original declarations are retained",
            },
        )
    return out


def _point_properties(species: Species, quantity: str) -> tuple[Property, ...]:
    """Select independent active declarations without upgrading their review."""
    offered = []
    if (species.state.status or species.status) not in {"rejected", "conflicting"} and (
        prop := species.properties.get(quantity)
    ):
        offered.append(prop)
    target = registry_state_candidate(species).key
    offered.extend(
        record.properties[quantity]
        for record in species.records
        if record.candidate.key == target
        and record.status not in {"rejected", "conflicting"}
        and quantity in record.properties
    )
    return tuple(
        sorted(
            (
                prop
                for prop in offered
                if prop.reviewed_for(quantity) and property_has_point_qualifier(prop) and prop.known
            ),
            key=_property_key,
        )
    )


def _property_key(prop: Property) -> str:
    return json.dumps(asdict(prop), sort_keys=True, default=str)


def _mass_properties(species: Species) -> tuple[Property, ...]:
    return tuple(
        prop
        for prop in _point_properties(species, "mass_amu")
        if prop.unit == "amu" and prop.value is not None and prop.value > 0
    )


def _zero_k_formation_properties(species: Species) -> tuple[Property, ...]:
    offered = tuple(
        prop
        for prop in _point_properties(species, "enthalpy_formation_eV")
        if prop.value is not None
        and energy_in_eV(prop.value, prop.unit) is not None
        and prop.formation_reference is not None
        and prop.formation_reference.complete
        and prop.formation_reference.temperature_K == 0
    )
    pressures = {
        prop.formation_reference.standard_pressure_Pa
        for prop in offered
        if prop.formation_reference is not None
    }
    return offered if len(pressures) == 1 and energy_declarations_agree(offered) else ()


def _excitation_value(prop: Property | None) -> float | None:
    if (
        prop is None
        or prop.value is None
        or not prop.reviewed_for("excitation_energy_eV")
        or not property_has_point_qualifier(prop)
        or not prop.known
    ):
        return None
    value = energy_in_eV(prop.value, prop.unit)
    return value if value is not None and isfinite(value) and value >= 0 else None


def _derived_property(
    quantity: str, value: float | None, unit: str, source: str, declaration: dict
) -> Property:
    return Property(
        value=value,
        unit=unit,
        source=source,
        tier="derived",
        status="derived",
        method="calculated",
        review_scope=(quantity,),
        source_declaration=declaration,
    )


def parents(registry: Registry) -> dict[str, str]:
    """Each non-ground state mapped to the ground state of the same substance."""

    ground: dict[tuple, list[str]] = {}
    for species in registry.species.values():
        if species.state.kind == "ground":
            key = (
                tuple(sorted(species.composition.items())),
                species.charge,
                species.phase,
                species.structure,
            )
            ground.setdefault(key, []).append(species.id)
    found = {}
    for species in registry.species.values():
        if species.state.kind == "ground":
            continue
        key = (
            tuple(sorted(species.composition.items())),
            species.charge,
            species.phase,
            species.structure,
        )
        matches = ground.get(key, [])
        if len(matches) == 1 and matches[0] != species.id:
            found[species.id] = matches[0]
    return found


def overlay(registry: Registry) -> dict:
    """Derive mass gaps and individually resolved formation-energy offsets."""

    properties: dict[str, dict] = {}
    atomic_inputs = _atomic_mass_inputs(registry)
    elements = {
        element: cast(float, inputs[0][1].value) for element, inputs in atomic_inputs.items()
    }
    for species in registry.species.values():
        if _declares_value(species, "mass_amu"):
            continue
        mass = mass_of(species.composition, species.charge, elements)
        if mass is not None:
            prop = _derived_property(
                "mass_amu",
                mass,
                "amu",
                "sum of qualified nominal atomic masses, less the electron mass",
                {
                    "operation": "composition_mass_approximation",
                    "composition": dict(species.composition),
                    "charge": species.charge,
                    "electron_mass_amu": ELECTRON_MASS_AMU,
                    "atomic_mass_inputs": {
                        element: [
                            {"species": species_id, "property": asdict(point)}
                            for species_id, point in atomic_inputs[element]
                        ]
                        for element in sorted(species.composition)
                    },
                    "approximation": "chemical binding and excitation mass defects are neglected",
                    "uncertainty_propagation": "not evaluated; original declarations are retained",
                },
            )
            properties.setdefault(registry_state_candidate(species).id, {})["mass_amu"] = asdict(
                prop
            )
    for state_id, parent_id in parents(registry).items():
        state, parent = registry.species[state_id], registry.species[parent_id]
        excitation = _resolved_excitation(state)
        for name, prop in carried_from(parent, excitation).items():
            if not _declares_value(state, name):
                properties.setdefault(registry_state_candidate(state).id, {})[name] = asdict(prop)
    return {"properties": properties}


def _declares_value(species: Species, quantity: str) -> bool:
    target = registry_state_candidate(species).key
    return species.value(quantity) is not None or any(
        record.properties[quantity].value is not None
        for record in species.records
        if record.candidate.key == target and quantity in record.properties
    )


def _resolved_excitation(species: Species) -> Property | None:
    if species.state.resolution != "resolved" or species.phase == "unknown":
        return None
    offered = tuple(
        prop
        for prop in _point_properties(species, "excitation_energy_eV")
        if _excitation_value(prop) is not None
    )
    return offered[0] if offered and energy_declarations_agree(offered) else None


def merged(acquired: dict, filled: dict) -> dict:
    """Fill missing property entries in the acquired overlay."""
    declarations = acquired.get("properties", {})
    if not isinstance(declarations, dict):
        raise ValueError("overlay.properties must be a mapping")
    combined = {}
    for state_id, properties in declarations.items():
        if not isinstance(properties, dict):
            raise ValueError(f"overlay.properties.{state_id} must be a mapping")
        combined[state_id] = dict(properties)
    for state_id, properties in filled["properties"].items():
        existing = combined.setdefault(state_id, {})
        for name, value in properties.items():
            existing.setdefault(name, value)
    return acquired | {"properties": combined}


def relocated_assets(acquired: dict, source_base: Path, destination_base: Path) -> dict:
    """Keep an overlay's numerical assets at the same locations after saving.

    Observe unsaved input references relative to their original file once;
    retain saved observations, author checksums and complete raw declarations.
    No values, source qualifications or missing assets are repaired here.
    """
    out = deepcopy(acquired)
    datasets = out.get("datasets")
    if datasets is None:
        return out
    if not isinstance(datasets, dict):
        raise ValueError("overlay.datasets must be a mapping")
    for entries in datasets.values():
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise ValueError("overlay.datasets entries must be lists of numeric records")
        for entry in entries:
            dataset = normalized_dataset(entry, base=source_base)
            if dataset.asset is not None:
                entry.update(
                    id=dataset.id,
                    asset=relocated_asset_payload(dataset.asset, source_base, destination_base),
                    source_declaration=deepcopy(dataset.source_declaration),
                )
    return out
