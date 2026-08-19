"""Is the numerical data behind the reaction list usable?

Separate from `audit.py` because these questions only arise once data exists.
Each group returns nothing at all when the registry holds none of its kind, so
an unpopulated capability produces one note instead of a backlog of findings.
"""

from __future__ import annotations

from collections import defaultdict

from reactgen.case import Case
from reactgen.model import ELECTRON, Gap, Network
from reactgen.physics import applicability
from reactgen.registry import Registry

# Properties each role needs. The ion-neutral neutral target set is the DNT+ input.
# Screening an ion-neutral channel is one enthalpy difference, so the formation
# enthalpy is as much a requirement as the transport parameters, and its absence
# is as worth reporting. Ionization energy carries the ion enthalpies with it:
# Hf(A+) = Hf(A) + IE(A).
SCREENING = ("enthalpy_formation_eV",)
TRANSPORT = ("mass_amu", "polarizability_A3", "dipole_moment_D", "collision_radius_A")

REQUIRED_PROPERTIES = {
    "electron_target": ("mass_amu",),
    "ion": ("mass_amu", *SCREENING),
    "dnt_neutral": (*TRANSPORT, *SCREENING, "ionization_energy_eV"),
}
MOMENTUM_TRANSFER = {"elastic", "effective", "momentum_transfer"}
REVERSIBLE_FAMILIES = {"neutral_neutral", "three_body"}


def quality(network: Network, case: Case, registry: Registry) -> list[Gap]:
    held = registry.capabilities
    gaps = [
        *_missing_properties(network),
        *_conflicting_forms(network),
        *_conditions(network, case),
        *_out_of_scope(held),
    ]
    if "cross_section" in held:
        gaps += _cross_sections(network)
    if "thermochemistry" in held:
        gaps += _reverse(network)
    if "surface_chemistry" in held:
        gaps += _sticking(network)
    if "uncertainty" in held:
        gaps += _uncertainty(network)
    gaps += _out_of_range(network, case)
    gaps += _competing(network)
    return sorted(gaps, key=Gap.sort_key)


DEFERRED = {
    "cross_section": "electron cross sections",
    "thermochemistry": "NASA polynomials and reverse rates",
    "surface_chemistry": "wall sticking coefficients",
    "uncertainty": "declared dataset uncertainty",
}


def _out_of_scope(held: frozenset[str]) -> list[Gap]:
    """One note per capability the registry has no data for at all."""

    return [
        Gap("out_of_scope", name, f"{label} are not in this registry yet", "info")
        for name, label in sorted(DEFERRED.items())
        if name not in held
    ]


# --------------------------------------------------------------------------- data


def _cross_sections(network: Network) -> list[Gap]:
    gaps = [
        Gap("missing_cross_section", reaction.id, reaction.family, "data")
        for reaction in network.reactions
        if reaction.rate_form == "cross_section" and reaction.best("cross_section") is None
    ]
    targets: defaultdict[str, list[str]] = defaultdict(list)
    for reaction in network.reactions:
        if reaction.family != "electron":
            continue
        for term in reaction.reactants:
            if term.species != ELECTRON and reaction.type in MOMENTUM_TRANSFER:
                targets[term.species].append(reaction.id)
    electron_targets = {
        term.species
        for reaction in network.reactions
        if reaction.family == "electron"
        for term in reaction.reactants
        if term.species != ELECTRON
    }
    gaps += [
        Gap("incomplete_set", target, "no momentum-transfer channel", "data")
        for target in sorted(electron_targets - set(targets))
    ]
    return gaps


def _sticking(network: Network) -> list[Gap]:
    return [
        Gap("missing_sticking_coefficient", reaction.id, str(reaction.surface), "data")
        for reaction in network.reactions
        if reaction.surface and reaction.best("sticking_coefficient") is None
    ]


def _uncertainty(network: Network) -> list[Gap]:
    """Reported once for the set: it is a convention gap, not N findings."""

    usable = [d for r in network.reactions for d in r.datasets if d.usable]
    bare = [d for d in usable if d.uncertainty is None]
    if not bare:
        return []
    detail = f"{len(bare)} of {len(usable)} usable datasets declare no uncertainty"
    return [Gap("no_uncertainty", "datasets", detail, "info")]


def _conflicting_forms(network: Network) -> list[Gap]:
    """A cross section and a ready-made rate for one reaction double count."""

    gaps = []
    for reaction in network.reactions:
        other = "rate_coefficient" if reaction.rate_form == "cross_section" else "cross_section"
        if reaction.best(reaction.rate_form) and reaction.best(other):
            detail = f"declares {reaction.rate_form} but also carries a usable {other}"
            gaps.append(Gap("conflicting_rate_form", reaction.id, detail, "blocking"))
    return gaps


def _competing(network: Network) -> list[Gap]:
    """More than one usable dataset for one quantity needs a human choice."""

    gaps = []
    for reaction in network.reactions:
        for kind in ("cross_section", "rate_coefficient", "mobility"):
            usable = [item for item in reaction.data(kind) if item.usable]
            if len(usable) > 1 and sum(item.preferred for item in usable) != 1:
                names = ", ".join(sorted(item.id for item in usable))
                gaps.append(Gap("competing_datasets", reaction.id, names, "info"))
    return gaps


def _out_of_range(network: Network, case: Case) -> list[Gap]:
    gaps = []
    for reaction in network.reactions:
        for dataset in reaction.datasets:
            window = dataset.validity
            if window is None or applicability(dataset, case.conditions) != "out_of_range":
                continue
            detail = f"{window.quantity} outside [{window.minimum}, {window.maximum}] {window.unit}"
            gaps.append(Gap("out_of_range", dataset.id, detail, "info"))
    return gaps


# --------------------------------------------------------------------------- species


def _missing_properties(network: Network) -> list[Gap]:
    gaps = []
    for species_id, roles in _roles(network).items():
        species = network.species[species_id]
        needed = {name for role in roles for name in REQUIRED_PROPERTIES.get(role, ())}
        gaps += [
            Gap("missing_property", species_id, name, "data")
            for name in sorted(needed)
            if species.value(name) is None
        ]
    return gaps


def _roles(network: Network) -> dict[str, set[str]]:
    """What each species is asked to be, and so what it has to carry.

    The ion and neutral roles follow from being in the network at all, not from
    a reaction naming the species. Every ion meets every neutral and
    `reactgen.dnt` hands that whole product to DNT+ as work, so the properties
    that work needs are required of every one of them. Deriving the roles from
    reactions instead asked for nothing on behalf of the pairs that have no
    reaction yet — which is most of them.
    """

    roles: defaultdict[str, set[str]] = defaultdict(set)
    for reaction in network.reactions:
        if reaction.family == "electron":
            for term in reaction.reactants:
                if term.species != ELECTRON:
                    roles[term.species].add("electron_target")
    for item in network.species.values():
        if item.id != ELECTRON:
            roles[item.id].add("ion" if item.charge else "dnt_neutral")
    return roles


def _reverse(network: Network) -> list[Gap]:
    """Reversible chemistry needs a declaration once the polynomials exist."""

    return [
        Gap("undeclared_reverse", reaction.id, reaction.family, "data")
        for reaction in network.reactions
        if reaction.family in REVERSIBLE_FAMILIES and reaction.reverse is None
    ]


def _conditions(network: Network, case: Case) -> list[Gap]:
    gaps = []
    if case.surfaces and case.conditions.area_to_volume is None:
        detail = "surfaces requested but volume_m3 / surface_area_m2 are unset"
        gaps.append(Gap("missing_condition", "geometry", detail, "data"))
    if not case.conditions.electron_density_m3 and any(
        reaction.family == "electron" for reaction in network.reactions
    ):
        detail = "electron_density_m3 is unset, so electron reactions cannot be ranked"
        gaps.append(Gap("missing_condition", "electron_density", detail, "info"))
    return gaps
