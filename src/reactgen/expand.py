"""Grow a reaction network outward from the input gases.

One pass per depth: take the species discovered in the previous pass, find every
registered pair they complete, accept the channels that balance, and let their
products form the next frontier. The walk stops when no new species appear.

A ``Proposer`` may be supplied to answer for species the registry does not
cover. The hook is defined here and implemented nowhere in this package: the
generator stays registry-only unless a caller deliberately hands it something
else, and whatever that something else proposes still has to balance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from reactgen.balance import imbalance
from reactgen.case import Case
from reactgen.model import ELECTRON, Gap, Network, Reaction
from reactgen.registry import PairKey, Registry
from reactgen.thermo import formation_delta

# Given the frontier and everything active, return further channels to consider.
Proposer = Callable[[set[str], set[str]], list[Reaction]]


def expand(
    registry: Registry, case: Case, propose: Proposer | None = None
) -> tuple[Network, list[Gap]]:
    network = Network(species={}, reactions=[])
    active, gaps = _seed(registry, case, network)

    frontier, seen, depth = set(active), set[PairKey](), 0
    while frontier and _depth_allowed(case, network, depth):
        found = _collect(registry, case, frontier, active, seen)
        if propose is not None:
            found += _proposed(propose, frontier, active, seen)
        # A family the case did not ask for is not collected at all. Dropping it
        # later would report it as rejected, which reads as a defect in the data.
        found = [item for item in found if case.accepts(item.type)]
        accepted, rejected = _accept(found, registry, depth)
        gaps += rejected

        accepted = _cap_reactions(network, case, accepted)
        discovered = {t.species for r in accepted for t in r.products} - active
        if not _species_allowed(network, case, active, discovered):
            break

        _record(network, registry, accepted, discovered, depth + 1)
        active |= discovered
        frontier, depth = discovered, depth + 1

    _link_precursors(network, case)
    return network, gaps + _unstartable_gases(registry, case, network)


# --------------------------------------------------------------------------- steps


def _seed(registry: Registry, case: Case, network: Network) -> tuple[set[str], list[Gap]]:
    active, gaps = {ELECTRON}, []
    for gas in case.gases:
        species_id = registry.resolve(gas)
        if species_id is None:
            gaps.append(Gap("input_gas", gas, "not registered as a species", "blocking"))
        else:
            active.add(species_id)
    _record(network, registry, [], active, depth=0)
    return active, gaps


def _collect(
    registry: Registry,
    case: Case,
    frontier: set[str],
    active: set[str],
    seen: set[PairKey],
) -> list[Reaction]:
    """Every acceptable channel newly reachable from this frontier."""

    keys = [key for key in registry.pairs_touching(active, frontier) if key not in seen]
    keys += [key for key in _surface_keys(registry, case, frontier) if key not in seen]
    seen.update(keys)
    return [
        reaction
        for key in keys
        for reaction in registry.channels[key]
        if reaction.status in case.accept_status
    ]


def _proposed(
    propose: Proposer, frontier: set[str], active: set[str], seen: set[PairKey]
) -> list[Reaction]:
    """Channels a proposer offers, minus anything the registry already gave."""

    offered = propose(frontier, active)
    fresh = []
    for reaction in offered:
        key: PairKey = ("proposed", reaction.id, "")
        if key not in seen:
            seen.add(key)
            fresh.append(reaction)
    return fresh


def _surface_keys(registry: Registry, case: Case, frontier: set[str]) -> list[PairKey]:
    return [
        key
        for key in registry.channels
        if key[0] == "surface" and key[1] in frontier and key[2] in case.surfaces
    ]


def _accept(
    found: list[Reaction], registry: Registry, depth: int
) -> tuple[list[Reaction], list[Gap]]:
    accepted, rejected = [], []
    for reaction in found:
        reason = imbalance(reaction, registry.species)
        if reason:
            rejected.append(Gap("rejected_reaction", reaction.id, reason, "blocking"))
        else:
            accepted.append(_with_energy(replace(reaction, depth=depth), registry))
    return accepted, rejected


def _with_energy(reaction: Reaction, registry: Registry) -> Reaction:
    """Fill the reaction enthalpy where the species carry one and it is absent.

    A curated channel records the threshold it was measured at, not the energy
    it costs, so without this the thermochemistry layer could say nothing about
    the very reactions a source stands behind.
    """

    if reaction.delta_e_eV is not None:
        return reaction
    energy = formation_delta(reaction, registry.species)
    return reaction if energy is None else replace(reaction, delta_e_eV=energy)


def _record(
    network: Network,
    registry: Registry,
    reactions: list[Reaction],
    species_ids: set[str],
    depth: int,
) -> None:
    network.reactions.extend(reactions)
    for reaction in reactions:
        for term in reaction.products:
            network.origin.setdefault(term.species, []).append(reaction.id)
    for species_id in species_ids:
        species = registry.species.get(species_id)
        if species is not None:
            network.species[species_id] = species
            network.depth.setdefault(species_id, depth)


def _link_precursors(network: Network, case: Case) -> None:
    """Attach the earlier reactions that made each reaction reachable."""

    inputs = set(case.gases) | {ELECTRON}
    producers: dict[str, list[str]] = {}
    for reaction in network.reactions:
        needed = {term.species for term in reaction.reactants} - inputs
        reaction.precursors = sorted(
            {rid for species in needed for rid in producers.get(species, ())}
        )
        for term in reaction.products:
            producers.setdefault(term.species, []).append(reaction.id)


# --------------------------------------------------------------------------- limits


def _depth_allowed(case: Case, network: Network, depth: int) -> bool:
    if network.truncated:
        return False
    if case.limits.max_depth is not None and depth > case.limits.max_depth:
        network.truncated.append(f"max_depth={case.limits.max_depth}")
        return False
    return True


def _cap_reactions(network: Network, case: Case, accepted: list[Reaction]) -> list[Reaction]:
    room = case.limits.max_reactions - len(network.reactions)
    if len(accepted) <= room:
        return accepted
    network.truncated.append(f"max_reactions={case.limits.max_reactions}")
    return accepted[: max(room, 0)]


def _species_allowed(network: Network, case: Case, active: set[str], discovered: set[str]) -> bool:
    if len(active) + len(discovered) <= case.limits.max_species:
        return True
    network.truncated.append(f"max_species={case.limits.max_species}")
    return False


def _unstartable_gases(registry: Registry, case: Case, network: Network) -> list[Gap]:
    """Input gases with no electron chemistry at all cannot start a network.

    A proposer may have supplied the channels the registry lacks, so the network
    decides, not the registry: reporting a gas as unstartable while its channels
    sit in the very list being returned would be false.
    """

    started = {
        term.species
        for reaction in network.reactions
        if reaction.family == "electron"
        for term in reaction.reactants
        if term.species != ELECTRON
    }
    return [
        Gap("unregistered_pair", f"e + {species_id}", "no electron channels", "blocking")
        for gas in case.gases
        if (species_id := registry.resolve(gas)) and species_id not in started
    ]
