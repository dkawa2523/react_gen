"""Is the reaction list itself sound?

These checks are about equations: whether a species is known, whether a reaction
conserves what it must, whether the same process was registered twice. They need
no numerical data and never pass, so they run on every registry.

Checks about *data* — cross sections, rates, properties — live in `quality.py`.
"""

from __future__ import annotations

from collections import defaultdict

from reactgen.model import ELECTRON, Gap, Network, Reaction, Species
from reactgen.registry import Registry

MOMENTUM_TRANSFER = {"elastic", "effective", "momentum_transfer"}
ENERGY_TOLERANCE_EV = 0.05

# What an electron-impact channel's onset is called, per process. Elastic and
# superelastic collisions are absent because theirs is zero by definition; every
# name here has to be read off a measured cross section.
ONSET = {
    "excitation": "excitation energy",
    "ionization": "ionization energy",
    "ionization_2": "second ionization energy",
    "ionization_3": "third ionization energy",
    "dissociation": "appearance energy",
    "dissociative_ionization": "appearance energy",
    "attachment": "resonance energy",
}


def audit(registry: Registry, network: Network | None = None) -> list[Gap]:
    """Structural findings for a registry, and for one network when given."""

    reactions = network.reactions if network else _all(registry)
    species = network.species if network else registry.species
    gaps = [
        *_unknown_species(reactions, registry),
        *_energy_consistency(reactions),
        *_duplicate_equations(reactions),
        *_double_counted_transfer(reactions),
        *_double_counted_excitation(reactions, species),
        *_lumped_overlap(species),
        *_unknown_materials(reactions, registry),
        *_missing_threshold(reactions),
        *_excitation_below_ionization(reactions, species),
    ]
    if network is None:
        gaps += _duplicate_ids(registry)
        gaps += _ionization_agreement(registry)
    else:
        gaps += _unreactive_species(network)
        gaps += _dangling_species(network)
    return sorted(gaps, key=Gap.sort_key)


def _all(registry: Registry) -> list[Reaction]:
    return [item for group in registry.channels.values() for item in group]


# --------------------------------------------------------------------------- references


def _unknown_species(reactions: list[Reaction], registry: Registry) -> list[Gap]:
    return [
        Gap("unknown_species", reaction.id, f"product {term.species}", "blocking")
        for reaction in reactions
        for term in reaction.products
        if term.species not in registry.species
    ]


def _unknown_materials(reactions: list[Reaction], registry: Registry) -> list[Gap]:
    """A surface channel naming an unregistered material has no wall to react on."""

    return [
        Gap("unknown_material", reaction.id, str(reaction.surface), "blocking")
        for reaction in reactions
        if reaction.surface and reaction.surface not in registry.materials
    ]


def _duplicate_ids(registry: Registry) -> list[Gap]:
    seen: dict[str, str] = {}
    gaps = []
    for key, channels in sorted(registry.channels.items()):
        for reaction in channels:
            if reaction.id in seen:
                gaps.append(Gap("duplicate_id", reaction.id, seen[reaction.id], "blocking"))
            seen[reaction.id] = "|".join(key)
    return gaps


# --------------------------------------------------------------------------- conservation


def _energy_consistency(reactions: list[Reaction]) -> list[Gap]:
    """An endothermic reaction cannot open below the energy it consumes.

    ``delta_e_eV`` is E(products) - E(reactants), so a positive value is
    endothermic and the threshold must be at least that large.
    """

    gaps = []
    for reaction in reactions:
        threshold, delta = reaction.threshold_eV, reaction.delta_e_eV
        if threshold is None or delta is None or delta <= 0:
            continue
        if threshold < delta - ENERGY_TOLERANCE_EV:
            detail = f"threshold {threshold} eV below the {delta:.3g} eV consumed"
            gaps.append(Gap("energy_inconsistent", reaction.id, detail, "blocking"))
    return gaps


def _ionization_agreement(registry: Registry) -> list[Gap]:
    """An ionization threshold and the species' ionization energy are one quantity.

    Nothing fills one from the other, because a derived copy drifts silently;
    the two are compared instead, and only a disagreement is reported.
    """

    gaps = []
    for (family, _, target), channels in registry.channels.items():
        species = registry.species.get(target) if family == "electron" else None
        energy = species.value("ionization_energy_eV") if species else None
        if energy is None:
            continue
        for reaction in channels:
            threshold = reaction.threshold_eV
            if reaction.type != "ionization" or threshold is None:
                continue
            if abs(threshold - energy) > ENERGY_TOLERANCE_EV:
                detail = f"threshold {threshold} eV but species records {energy} eV"
                gaps.append(Gap("ionization_disagreement", reaction.id, detail, "blocking"))
    return gaps


# --------------------------------------------------------------------------- double counting


def _duplicate_equations(reactions: list[Reaction]) -> list[Gap]:
    """The same equation registered twice is counted twice by any model.

    Same equation with a different type is legitimate — elastic scattering and
    resonant charge exchange move no atoms but are distinct processes — so that
    is reported for confirmation rather than as a fault.
    """

    groups: defaultdict[tuple, list[Reaction]] = defaultdict(list)
    for reaction in reactions:
        groups[reaction.signature].append(reaction)

    gaps = []
    for group in groups.values():
        if len(group) < 2:
            continue
        ids = ", ".join(sorted(item.id for item in group))
        types = sorted({item.type for item in group})
        if len(types) == 1:
            gaps.append(Gap("duplicate_equation", group[0].equation, ids, "blocking"))
        else:
            detail = f"types {types}: {ids}"
            gaps.append(Gap("shared_stoichiometry", group[0].equation, detail, "info"))
    return gaps


def _electron_channels(reactions: list[Reaction]) -> dict[str, list[Reaction]]:
    """Every electron-impact channel, indexed by the heavy species it strikes."""

    by_target: defaultdict[str, list[Reaction]] = defaultdict(list)
    for reaction in reactions:
        if reaction.family != "electron":
            continue
        for term in reaction.reactants:
            if term.species != ELECTRON:
                by_target[term.species].append(reaction)
    return dict(by_target)


def _double_counted_transfer(reactions: list[Reaction]) -> list[Gap]:
    """One momentum-transfer channel per target.

    An elastic and an effective cross section describe the same collision, so
    carrying both makes a swarm calculation lose energy twice.
    """

    gaps = []
    for target, channels in sorted(_electron_channels(reactions).items()):
        transfer = sorted(r.id for r in channels if r.type in MOMENTUM_TRANSFER)
        if len(transfer) > 1:
            detail = f"multiple momentum transfer: {', '.join(transfer)}"
            gaps.append(Gap("double_counted", target, detail, "blocking"))
    return gaps


def _double_counted_excitation(reactions: list[Reaction], species: dict[str, Species]) -> list[Gap]:
    """One resolution per manifold, per target.

    Resolutions only clash inside a manifold. A vibrational ladder and an
    electronic manifold are two processes, not two views of one, so ``O2_v``
    standing beside a resolved ``O2_a1Delta`` counts each excitation once.
    """

    gaps = []
    for target, channels in sorted(_electron_channels(reactions).items()):
        struck = species.get(target)
        if struck is None:
            continue
        seen: defaultdict[str, set[str]] = defaultdict(set)
        for reaction in channels:
            for term in reaction.products:
                item = species.get(term.species)
                # An excited *fragment* says nothing about how finely the target
                # is resolved: `e + CF2 -> e + F2 + C(1D)` breaks a bond, and
                # counting C(1D) as a level of CF2 flagged a mechanism as wrong.
                if item is not None and item.state.kind == "excited" and _same_body(item, struck):
                    seen[item.state.manifold].add(item.state.resolution)
        for manifold, resolutions in sorted(seen.items()):
            if {"lumped", "state_resolved"} <= resolutions:
                detail = f"lumped and state-resolved {manifold} excitation coexist"
                gaps.append(Gap("double_counted", target, detail, "blocking"))
    return gaps


def _same_body(left: Species, right: Species) -> bool:
    """Whether two records describe the same species in different states."""

    return left.composition == right.composition and left.charge == right.charge


def _lumped_overlap(species: dict[str, Species]) -> list[Gap]:
    """A lumped level and the levels it stands for cannot both be tracked."""

    return [
        Gap("double_counted", item.id, f"also tracks {', '.join(present)}", "blocking")
        for item in species.values()
        if (present := sorted(set(item.state.members) & set(species)))
    ]


# --------------------------------------------------------------------------- reachability


def _unreactive_species(network: Network) -> list[Gap]:
    """A neutral with no electron chemistry is a dead end in a discharge.

    What the network holds decides this, not what the registry holds. A
    proposed species carries its channels in the network alone, so reading the
    registry would report every one of them as unreactive.
    """

    struck = {
        term.species
        for reaction in network.reactions
        for term in reaction.reactants
        if any(other.species == ELECTRON for other in reaction.reactants)
    }
    return [
        Gap("missing_electron_chemistry", item.id, "no e + X channel", "data")
        for item in sorted(network.species.values(), key=lambda x: x.id)
        if item.is_neutral and item.id not in struck
    ]


def _missing_threshold(reactions: list[Reaction]) -> list[Gap]:
    """An electron-impact channel whose onset nothing states.

    The list still holds the reaction and its species; what is missing is the
    energy at which it opens. LXCat publishes it alongside the cross section,
    one block per process, which is why the route is named here.
    """

    out = []
    for reaction in reactions:
        if reaction.threshold_eV is not None or reaction.type not in ONSET:
            continue
        wanted = ONSET[reaction.type]
        if reaction.type == "excitation" and any(
            term.species.endswith("_v") for term in reaction.products
        ):
            wanted = "vibrational quantum"
        out.append(
            Gap("missing_threshold", reaction.id, f"{wanted} unknown; LXCat states it", "data")
        )
    return out


def _excitation_below_ionization(
    reactions: list[Reaction], species: dict[str, Species]
) -> list[Gap]:
    """An excitation costing more than ionization would not be an excitation.

    A free check on whatever was acquired: the bound holds for every species,
    and the ionization energy is already recorded.
    """

    out = []
    for reaction in reactions:
        if reaction.type != "excitation" or reaction.threshold_eV is None:
            continue
        for term in reaction.reactants:
            limit = _ionization_of(species.get(term.species))
            if limit is not None and reaction.threshold_eV > limit:
                out.append(
                    Gap(
                        "energy_above_ionization",
                        reaction.id,
                        f"threshold {reaction.threshold_eV:.3f} eV exceeds "
                        f"{term.species} ionization at {limit:.3f} eV",
                        "blocking",
                    )
                )
    return out


def _ionization_of(item: Species | None) -> float | None:
    return None if item is None else item.value("ionization_energy_eV")


def _dangling_species(network: Network) -> list[Gap]:
    """A species that is only ever produced has no loss path in the model."""

    produced = {t.species for r in network.reactions for t in r.products}
    consumed = {t.species for r in network.reactions for t in r.reactants}
    return [
        Gap("no_loss_path", species_id, "produced but never consumed", "info")
        for species_id in sorted(produced - consumed - {ELECTRON})
    ]
