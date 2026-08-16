"""Attach deterministic direct precursor IDs to generated reactions."""

from __future__ import annotations

from plasma_reactgen.application.reaction_lineage_index import (
    ProducerIndex,
    input_species_ids,
    precursor_reactions,
    record_reaction_products,
)
from plasma_reactgen.domain.models import ReactionNetwork


def attach_reaction_lineage(network: ReactionNetwork) -> ReactionNetwork:
    """Attach direct precursors while excluding input species and same-depth cycles."""

    producers: ProducerIndex = {}
    inputs = input_species_ids(network)
    ordered_reactions = sorted(
        network.reactions,
        key=lambda reaction: (reaction.depth, reaction.id),
    )
    for reaction in ordered_reactions:
        reaction.precursor_reaction_ids = [
            producer.id for producer in precursor_reactions(reaction, inputs, producers)
        ]
        record_reaction_products(reaction, producers)
    return network


__all__ = ["attach_reaction_lineage"]
