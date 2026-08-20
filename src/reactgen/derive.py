"""Properties an excited state inherits from the species it is a state of.

Half the registry is states rather than substances: `CF4_v`, `Ar_4s`, `O2_a1Delta`
are argon and oxygen and carbon tetrafluoride, in a different level. No
compilation tabulates them, and none should -- they are the same molecule.

Which properties carry over is a physical question with different answers:

    polarizability, dipole moment,     unchanged to the accuracy anything here
    collision radius, well depth       needs. Vibrational excitation moves the
                                       nuclei within one electronic state, and
                                       a low-lying metastable leaves the charge
                                       distribution close to the ground state.

    formation enthalpy                 shifts by the level energy, since the
                                       state is the substance holding that much
                                       more energy. Most of the registry's
                                       states carry it already; the rule is
                                       here so none is left out.

    ionization energy, affinity        shift by the level energy with the
                                       opposite sign, and the registry carries
                                       those where they are known.

Nothing is inherited across a charge change. A cation is smaller and less
polarizable than its neutral and an anion is larger, by tens of percent, so
`CF3+` may not take `CF3`'s polarizability -- and that is exactly the case a
naive "same composition" rule would get wrong.

The output is an overlay rather than a registry edit, so a derived value stays
labelled as derived and a curated one is never overwritten.
"""

from __future__ import annotations

from dataclasses import replace

from reactgen.model import Property, Species
from reactgen.registry import Registry

ELECTRON_MASS_AMU = 0.000548579909


def element_masses(registry: Registry) -> dict[str, float]:
    """Atomic mass per element, from the registry's own single-atom species."""

    found = {}
    for species in registry.species.values():
        if species.charge or len(species.composition) != 1:
            continue
        ((element, count),) = species.composition.items()
        mass = species.value("mass_amu")
        if count == 1 and mass is not None and species.state.kind == "ground":
            found[element] = mass
    return found


def mass_of(composition: dict[str, int], charge: int, elements: dict[str, float]) -> float | None:
    """Mass from the atoms present, less the electrons the charge stands for.

    Arithmetic, not a lookup: a mass that cannot be stated leaves a species with
    no reduced mass, and every collision rate and wall loss in the run is formed
    from one. The electron term is 0.0005 amu and matters to nothing here, but
    leaving it out would make `Ar+` and `Ar` the same number, which they are not.
    """

    if not composition or any(element not in elements for element in composition):
        return None
    total = sum(count * elements[element] for element, count in composition.items())
    return round(total - charge * ELECTRON_MASS_AMU, 6)


# Unchanged between a species and its own excited or vibrational levels. Mass is
# first because it is the one a proposed state cannot do without: without it
# there is no reduced mass, so no collision rate and no wall loss either.
CARRIED = (
    "mass_amu",
    "polarizability_A3",
    "dipole_moment_D",
    "collision_radius_A",
    "well_depth_K",
)


def carried_from(parent: Species, energy_eV: float | None) -> dict[str, Property]:
    """The properties a state of `parent` holds, ready to attach to it.

    Shared with the proposer, which invents `SF4_v` while the run is walking and
    cannot come back for an overlay afterwards. Same rule in both places, so a
    state invented during a walk and one sitting in the registry answer alike.
    """

    out = {
        name: replace(
            parent.properties[name],
            source=f"unchanged from {parent.id} on excitation; "
            f"{(parent.properties[name].source or '').split(';')[0]}",
        )
        for name in CARRIED
        if parent.properties.get(name) is not None and parent.value(name) is not None
    }
    enthalpy = parent.value("enthalpy_formation_eV")
    if enthalpy is not None and energy_eV is not None:
        out["enthalpy_formation_eV"] = Property(
            value=round(enthalpy + energy_eV, 6),
            unit="eV",
            source=f"{parent.id} enthalpy plus the {energy_eV:.4g} eV level energy",
        )
    return out


def parents(registry: Registry) -> dict[str, str]:
    """Each non-ground state mapped to the ground state of the same substance."""

    ground: dict[tuple[tuple[tuple[str, int], ...], int], str] = {}
    for species in registry.species.values():
        if species.state.kind == "ground":
            ground.setdefault(
                (tuple(sorted(species.composition.items())), species.charge), species.id
            )
    found = {}
    for species in registry.species.values():
        if species.state.kind == "ground":
            continue
        key = (tuple(sorted(species.composition.items())), species.charge)
        parent = ground.get(key)
        if parent is not None and parent != species.id:
            found[species.id] = parent
    return found


def overlay(registry: Registry) -> dict:
    """An overlay filling every state property its ground state already answers."""

    properties: dict[str, dict] = {}
    thermo: dict[str, dict] = {}
    elements = element_masses(registry)
    for species in registry.species.values():
        if species.value("mass_amu") is not None:
            continue
        mass = mass_of(species.composition, species.charge, elements)
        if mass is not None:
            properties.setdefault(species.id, {})["mass_amu"] = {
                "value": mass,
                "unit": "amu",
                "source": "sum of atomic masses in the registry, less the electron mass",
            }
    for state_id, parent_id in parents(registry).items():
        state, parent = registry.species[state_id], registry.species[parent_id]
        energy = state.state.energy_eV
        for name, prop in carried_from(parent, energy).items():
            if state.value(name) is None:
                properties.setdefault(state_id, {})[name] = {
                    "value": prop.value,
                    "unit": prop.unit,
                    "source": prop.source,
                }
        if state.thermo is None and parent.thermo is not None and energy is not None:
            thermo[state_id] = _shifted(parent, parent_id, energy)
    return {"properties": properties, "thermo": thermo}


def merged(acquired: dict, filled: dict) -> dict:
    """The acquired overlay with derived entries added where it was silent."""

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


def _shifted(parent, parent_id: str, energy_eV: float) -> dict:
    """The parent's polynomial with the level energy folded into the enthalpy term.

    In a NASA fit H(T)/RT carries its constant as a6/T, so a level sitting
    `energy` above the ground state raises a6 by energy/R in kelvin. Cp and S
    are untouched: the manifold has the parent's heat capacity, which is the
    whole reason a state can borrow its polynomial at all.
    """

    kelvin = energy_eV * 11604.518
    low = list(parent.thermo.low)
    high = list(parent.thermo.high)
    low[5] += kelvin
    high[5] += kelvin
    return {
        "low": low,
        "high": high,
        "t_min": parent.thermo.t_min,
        "t_mid": parent.thermo.t_mid,
        "t_max": parent.thermo.t_max,
        "source": (
            f"{parent_id} polynomial with the {energy_eV:.4g} eV level energy "
            f"added to the enthalpy constant"
        ),
    }
