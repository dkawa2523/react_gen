from __future__ import annotations

from plasma_reactgen.domain.models import GeneratedReaction, ReactionNetwork

__all__ = ["derive_species_roles"]


def derive_species_roles(network: ReactionNetwork) -> dict[str, set[str]]:
    """Return generated roles without mutating the network's species nodes."""

    roles = {species_id: set(node.roles) for species_id, node in network.species_nodes.items()}
    for reaction in network.reactions:
        if reaction.family == "electron":
            _assign_electron_target_roles(reaction, roles)
        elif reaction.family == "ion_neutral":
            _assign_ion_neutral_roles(reaction, network, roles)
    return roles


def _assign_electron_target_roles(
    reaction: GeneratedReaction,
    roles: dict[str, set[str]],
) -> None:
    for reactant in reaction.reactants:
        if reactant.species != "e" and reactant.species in roles:
            roles[reactant.species].add("electron_target")


def _assign_ion_neutral_roles(
    reaction: GeneratedReaction,
    network: ReactionNetwork,
    roles: dict[str, set[str]],
) -> None:
    for reactant in reaction.reactants:
        species_id = reactant.species
        species = network.species.get(species_id)
        if species_id == "e" or species_id not in roles or species is None:
            continue
        if species.charge == 0:
            roles[species_id].update({"ion_neutral_target", "dnt_neutral"})
        else:
            roles[species_id].update({"ion_neutral_projectile", "dnt_ion"})
