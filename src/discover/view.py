"""Read the registry the ways discovery needs it.

Discovery asks structural questions the generator never asks — which formula
carries which charge, what energy a level sits at — so the projections live
here rather than growing the registry or the command.

Questions *about one species in relation to another* — which ion a neutral
becomes, what an excited state falls back to — belong to `relations` instead,
and are not answered twice. A second copy of `cations` lived here once and
did not know that ionizing a metastable leaves the ground-state ion.
"""

from __future__ import annotations

from reactgen.registry import Registry

Structure = tuple[tuple[tuple[str, int], ...], int]


def _key(composition: dict[str, int], charge: int) -> Structure:
    return (tuple(sorted(composition.items())), charge)


def known(registry: Registry) -> dict[Structure, str]:
    """Every registered species, found by its formula and charge.

    The ground state wins where several states share a formula. A fragment is
    named from its composition alone, so without this the last file loaded
    decides: oxygen came back as ``O_1D`` and argon as ``Ar_4s``, and every
    dissociation then wrote an excited fragment where it meant a ground one.
    """

    found: dict[Structure, str] = {}
    for species in registry.species.values():
        if not species.composition:
            continue
        key = _key(species.composition, species.charge)
        if key not in found or species.state.kind == "ground":
            found[key] = species.id
    return found


def species_view(registry: Registry) -> dict[str, dict]:
    """The plain composition and charge of each species, for evidence checks."""

    return {
        species.id: {"charge": species.charge, "composition": dict(species.composition)}
        for species in registry.species.values()
    }


def ionization(registry: Registry) -> dict[str, float]:
    """Ionization energy per neutral, from the property or the channel threshold.

    The two are the same quantity recorded in two places; `reactgen.audit`
    reports any disagreement, so either may be read here.
    """

    energies = {
        species.id: species.value("ionization_energy_eV")
        for species in registry.species.values()
        if species.value("ionization_energy_eV")
    }
    for (family, _, target), channels in registry.channels.items():
        if family != "electron":
            continue
        for reaction in channels:
            if reaction.type == "ionization" and reaction.threshold_eV:
                energies.setdefault(target, reaction.threshold_eV)
    found = {name: value for name, value in energies.items() if value}
    _excited_from_ground(registry, found, -1)  # excitation is a head start
    return found


def _excited_from_ground(registry: Registry, base: dict[str, float], sign: int) -> None:
    """Carry a ground-state value onto the levels above it.

    Exact, not estimated. An excited state sits its excitation energy above the
    ground state, so its formation enthalpy is that much higher and its
    ionization energy that much lower — Hf(X*) = Hf(X) + E, IE(X*) = IE(X) - E.
    Nothing is written where the level energy itself is unknown.
    """

    ground = {
        _key(item.composition, item.charge): item.id
        for item in registry.species.values()
        if item.state.kind == "ground"
    }
    for item in registry.species.values():
        if item.state.kind != "excited" or item.state.energy_eV is None:
            continue
        parent = ground.get(_key(item.composition, item.charge))
        if parent is not None and parent in base and item.id not in base:
            base[item.id] = base[parent] + sign * item.state.energy_eV


def affinity(registry: Registry) -> dict[str, float]:
    """Electron affinity per species, in eV, where the registry records one."""

    return {
        species.id: value
        for species in registry.species.values()
        if (value := species.value("electron_affinity_eV")) is not None
    }


def enthalpy(registry: Registry) -> dict[str, float]:
    """Formation enthalpy per species, in eV, where the registry records one."""

    found = {
        species.id: value
        for species in registry.species.values()
        if (value := species.value("enthalpy_formation_eV")) is not None
    }
    _excited_from_ground(registry, found, +1)  # the level sits that much higher
    return found


# What `acquire asd` records against a ground-state atom, under the name of the
# excited species a proposer would invent from it.
LEVEL = {
    "metastable": "metastable_energy_eV",
    "resonant": "resonant_energy_eV",
    "lumped": "excitation_energy_eV",
}


def excitation(registry: Registry) -> dict[str, dict[str, float]]:
    """Excitation energy per species, by the kind of level it belongs to.

    Vibrational levels are absent by construction: no atomic database carries
    one, and the manifold a molecule gets is not a level at all.
    """

    out: dict[str, dict[str, float]] = {}
    for species in registry.species.values():
        levels = {
            kind: value
            for kind, name in LEVEL.items()
            if (value := species.value(name)) is not None
        }
        if levels:
            out[species.id] = levels
    return out


def vibration(registry: Registry) -> dict[str, float]:
    """Effective vibrational quantum per species, where one has been fitted.

    The manifold a proposer invents as ``X_v`` sits this far above the ground
    state, so without it the relaxation channel carries no energy at all.
    """

    return {
        species.id: value
        for species in registry.species.values()
        if (value := species.value("vibrational_quantum_eV")) is not None
    }
