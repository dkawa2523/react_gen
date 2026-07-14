from __future__ import annotations

from collections import defaultdict

from plasma_reactgen.domain.models import GeneratedReaction, ReactionNetwork


def attach_reaction_lineage(network: ReactionNetwork) -> ReactionNetwork:
    """Attach direct precursor reactions without traversing same-depth cycles."""

    ordered = sorted(network.reactions, key=lambda reaction: (reaction.depth, reaction.id))
    input_species = {
        species_id
        for species_id, node in network.species_nodes.items()
        if "input_gas" in node.roles
    }
    producers: dict[str, list[GeneratedReaction]] = defaultdict(list)

    for reaction in ordered:
        non_input_reactants = sorted(
            {
                amount.species
                for amount in reaction.reactants
                if amount.species != "e" and amount.species not in input_species
            }
        )
        precursor_reactions = sorted(
            {
                producer.id: producer
                for species_id in non_input_reactants
                for producer in producers.get(species_id, [])
                if producer.depth < reaction.depth
            }.values(),
            key=lambda producer: (producer.depth, producer.id),
        )
        reaction.precursor_reaction_ids = [producer.id for producer in precursor_reactions]

        reactant_species = {amount.species for amount in reaction.reactants}
        for product in reaction.products:
            if product.species != "e" and product.species not in reactant_species:
                producers[product.species].append(reaction)

    return network
