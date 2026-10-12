"""Explicit derived mass and resolved-level formation-energy offsets.

Composition sums neglect chemical binding mass defects; carrying mass across
excitation additionally neglects E/c^2. Electronic response and transport
properties require their own evidence. No equilibrium populations or excited
NASA partition functions are inferred by this operation.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from math import isfinite

from reactgen.evidence import registry_state_candidate
from reactgen.records import Property, Species
from reactgen.registry import Registry
from reactgen.units import energy_eV as energy_in_eV

ELECTRON_MASS_AMU = 0.000548579909


def element_masses(registry: Registry) -> dict[str, float]:
    """Atomic mass per element, from the registry's own single-atom species."""

    offered: dict[str, set[float]] = {}
    for species in registry.species.values():
        if species.charge or len(species.composition) != 1:
            continue
        ((element, count),) = species.composition.items()
        mass = _mass_amu(species)
        if count == 1 and mass is not None and species.state.kind == "ground":
            offered.setdefault(element, set()).add(mass)
    return {element: next(iter(values)) for element, values in offered.items() if len(values) == 1}


def mass_of(composition: dict[str, int], charge: int, elements: dict[str, float]) -> float | None:
    """Sum atom masses minus missing electrons, neglecting binding mass defects."""

    if not composition or any(element not in elements for element in composition):
        return None
    total = sum(count * elements[element] for element, count in composition.items())
    return round(total - charge * ELECTRON_MASS_AMU, 6)


# Excitation changes electronic response and transport interactions. Only mass
# can be carried with the explicit approximation that the excitation energy's
# relativistic mass contribution is neglected.
CARRIED = ("mass_amu",)


def carried_from(
    parent: Species, energy_eV: float | None, energy_source: str | None = None
) -> dict[str, Property]:
    """The properties a state of `parent` holds, ready to attach to it.

    This is an explicit derived-data operation. Registry loading never inserts
    these values implicitly. A resolved level offset is carried into formation
    enthalpy only at 0 K: finite-T changes in vibrational/rotational thermal
    contributions are not supplied by the electronic level energy.
    """

    out = {
        name: replace(
            parent.properties[name],
            source=f"unchanged from {parent.id} on excitation; "
            f"{(parent.properties[name].source or '').split(';')[0]}",
            tier="derived",
        )
        for name in CARRIED
        if _mass_amu(parent) is not None
    }
    prop = parent.properties.get("enthalpy_formation_eV")
    enthalpy = (
        energy_in_eV(prop.value, prop.unit)
        if prop and prop.value is not None and prop.tier in {"curated", "reviewed", "derived"}
        else None
    )
    if (
        enthalpy is not None
        and energy_eV is not None
        and prop is not None
        and prop.reviewed_for("enthalpy_formation_eV")
        and prop.formation_reference is not None
        and prop.formation_reference.complete
        and prop.formation_reference.temperature_K == 0
        and prop.qualifier is None
    ):
        out["enthalpy_formation_eV"] = Property(
            value=round(enthalpy + energy_eV, 6),
            unit="eV",
            source=f"{parent.id} enthalpy plus the {energy_eV:.4g} eV level energy"
            + (f"; {energy_source}" if energy_source else ""),
            tier="derived",
            formation_reference=prop.formation_reference,
            status="derived",
            method="calculated",
            review_scope=("enthalpy_formation_eV",),
            source_declaration={
                "operation": "resolved_level_formation_offset",
                "parent_species": parent.id,
                "parent_formation_enthalpy": asdict(prop),
                "level_energy_eV": energy_eV,
                "level_source": energy_source,
                "reference_temperature_K": 0.0,
            },
        )
    return out


def _mass_amu(species: Species) -> float | None:
    prop = species.properties.get("mass_amu")
    if prop is None or prop.unit != "amu" or prop.value is None:
        return None
    return prop.value if isfinite(prop.value) and prop.value > 0 else None


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
    elements = element_masses(registry)
    for species in registry.species.values():
        if species.value("mass_amu") is not None:
            continue
        mass = mass_of(species.composition, species.charge, elements)
        if mass is not None:
            properties.setdefault(registry_state_candidate(species).id, {})["mass_amu"] = {
                "value": mass,
                "unit": "amu",
                "source": "sum of atomic masses in the registry, less the electron mass",
                "evidence_tier": "derived",
            }
    for state_id, parent_id in parents(registry).items():
        state, parent = registry.species[state_id], registry.species[parent_id]
        excitation = state.properties.get("excitation_energy_eV")
        energy = (
            energy_in_eV(excitation.value, excitation.unit)
            if state.state.resolution == "resolved"
            and state.phase != "unknown"
            and excitation is not None
            and excitation.value is not None
            and excitation.tier in {"curated", "reviewed"}
            and excitation.qualifier is None
            else None
        )
        for name, prop in carried_from(
            parent, energy, excitation.source if excitation else None
        ).items():
            if state.value(name) is None:
                entry: dict[str, object] = {
                    "value": prop.value,
                    "unit": prop.unit,
                    "source": prop.source,
                    "evidence_tier": "derived",
                }
                if prop.formation_reference is not None:
                    entry["formation_reference"] = asdict(prop.formation_reference)
                    entry["method"] = prop.method
                    entry["review_scope"] = list(prop.review_scope)
                    entry["source_declaration"] = prop.source_declaration
                properties.setdefault(registry_state_candidate(state).id, {})[name] = entry
    return {"properties": properties}


def merged(acquired: dict, filled: dict) -> dict:
    """The acquired overlay with derived entries added where it was silent."""

    for section in ("properties", "thermo"):
        if section in acquired and not isinstance(acquired[section], dict):
            raise ValueError(f"overlay.{section} must be a mapping")
    for state_id, properties in acquired.get("properties", {}).items():
        if not isinstance(properties, dict):
            raise ValueError(f"overlay.properties.{state_id} must be a mapping")
    out = {key: dict(value) for key, value in (acquired or {}).items() if isinstance(value, dict)}
    out.update({key: value for key, value in (acquired or {}).items() if key not in out})
    for section in ("properties", "thermo"):
        target = out.setdefault(section, {})
        for species_id, entry in (filled.get(section) or {}).items():
            if section == "thermo":
                target.setdefault(species_id, entry)
            else:
                held = target.setdefault(species_id, {})
                for name, value in entry.items():
                    held.setdefault(name, value)
    return out
