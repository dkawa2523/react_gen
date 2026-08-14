"""Index direct producer relationships for reaction lineage projection."""

from __future__ import annotations

from plasma_reactgen.domain.models import GeneratedReaction, ReactionNetwork

ProducerIndex = dict[str, list[GeneratedReaction]]


def input_species_ids(network: ReactionNetwork) -> set[str]:
    return {
        species_id
        for species_id, node in network.species_nodes.items()
        if "input_gas" in node.roles
    }


def precursor_reactions(
    reaction: GeneratedReaction,
    input_species: set[str],
    producers: ProducerIndex,
) -> list[GeneratedReaction]:
    non_input_reactants = {
        amount.species
        for amount in reaction.reactants
        if amount.species != "e" and amount.species not in input_species
    }
    direct_producers = {
        producer.id: producer
        for species_id in non_input_reactants
        for producer in producers.get(species_id, [])
        if producer.depth < reaction.depth
    }
    return sorted(
        direct_producers.values(),
        key=lambda producer: (producer.depth, producer.id),
    )


def record_reaction_products(
    reaction: GeneratedReaction,
    producers: ProducerIndex,
) -> None:
    reactant_species = {amount.species for amount in reaction.reactants}
    introduced_products = {
        product.species
        for product in reaction.products
        if product.species != "e" and product.species not in reactant_species
    }
    for species_id in introduced_products:
        producers.setdefault(species_id, []).append(reaction)


__all__ = [
    "ProducerIndex",
    "input_species_ids",
    "precursor_reactions",
    "record_reaction_products",
]
