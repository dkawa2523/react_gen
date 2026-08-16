"""Load and register species introduced during network expansion."""

from __future__ import annotations

from plasma_reactgen.application.config import CaseConfig
from plasma_reactgen.application.network_expansion_state import ExpansionState
from plasma_reactgen.application.ports import SpeciesRepository
from plasma_reactgen.domain.chemistry import is_excited_state, species_has_any_class
from plasma_reactgen.domain.models import (
    MissingDataItem,
    NetworkSpeciesNode,
    ReactionChannel,
    Species,
    SpeciesAmount,
)


def load_registered_product_species(
    channel: ReactionChannel,
    species_repo: SpeciesRepository,
    state: ExpansionState,
) -> None:
    for amount in channel.products:
        species_id = amount.species
        if species_id == "e" or species_id in state.known_species:
            continue
        species = species_repo.get_species(species_id)
        if species is None:
            state.missing_data.append(
                MissingDataItem(
                    subject_kind="species",
                    subject_id=species_id,
                    field="registry/species",
                    required_by=channel.id,
                    severity="required",
                    message="Product species is referenced by a reaction but not registered.",
                )
            )
        else:
            state.known_species[species_id] = species


def new_product_species_ids(
    products: list[SpeciesAmount],
    state: ExpansionState,
) -> list[str]:
    return list(
        dict.fromkeys(
            amount.species
            for amount in products
            if amount.species != "e"
            and amount.species in state.known_species
            and amount.species not in state.species_nodes
        )
    )


def register_product_nodes(
    channel: ReactionChannel,
    depth: int,
    new_frontier: set[str],
    state: ExpansionState,
    config: CaseConfig,
) -> list[str]:
    introduced: list[str] = []
    for amount in channel.products:
        species_id = amount.species
        if species_id == "e" or species_id not in state.known_species:
            continue
        first_seen = species_id not in state.species_nodes
        if first_seen:
            _add_product_node(channel.id, species_id, depth, state, config)
            introduced.append(species_id)
        else:
            _update_product_node(channel.id, state.species_nodes[species_id])
        if first_seen and state.species_nodes[species_id].propagated:
            state.active_species[species_id] = state.known_species[species_id]
            new_frontier.add(species_id)
    return introduced


def _add_product_node(
    channel_id: str,
    species_id: str,
    depth: int,
    state: ExpansionState,
    config: CaseConfig,
) -> None:
    state.species_nodes[species_id] = NetworkSpeciesNode(
        species_id=species_id,
        depth_first_seen=depth + 1,
        introduced_by=[channel_id],
        roles={"reaction_product"},
        propagated=_should_propagate(state.known_species[species_id], config),
    )


def _update_product_node(channel_id: str, node: NetworkSpeciesNode) -> None:
    if channel_id not in node.introduced_by:
        node.introduced_by.append(channel_id)
    node.roles.add("reaction_product")


def _should_propagate(species: Species, config: CaseConfig) -> bool:
    if not species_has_any_class(species, config.expansion.propagate_species_classes):
        return False
    return not (is_excited_state(species) and not config.expansion.propagate_excited_states)
