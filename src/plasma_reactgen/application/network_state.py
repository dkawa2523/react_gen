"""Initialize and finalize the mutable state used during network expansion."""

from __future__ import annotations

from plasma_reactgen.application.ports import SpeciesRepository
from plasma_reactgen.application.reaction_lineage import attach_reaction_lineage
from plasma_reactgen.domain.chemistry import make_electron_species
from plasma_reactgen.domain.models import (
    CoverageItem,
    GeneratedReaction,
    MissingDataItem,
    NetworkSpeciesNode,
    ReactionNetwork,
    Species,
    TruncationEvent,
)


def initialize_species(
    gases: list[str],
    repository: SpeciesRepository,
) -> tuple[dict[str, Species], dict[str, Species], dict[str, NetworkSpeciesNode]]:
    electron = make_electron_species()
    known = {"e": electron}
    active = {"e": electron}
    nodes: dict[str, NetworkSpeciesNode] = {}
    for gas in gases:
        species = repository.get_species(gas)
        if species is None:
            raise ValueError(f"Input gas species is not registered: {gas}")
        known[gas] = species
        active[gas] = species
        nodes[gas] = NetworkSpeciesNode(
            species_id=gas,
            depth_first_seen=0,
            introduced_by=["input_gas"],
            roles={"input_gas"},
            propagated=True,
        )
    return known, active, nodes


def finalize_network(
    *,
    species: dict[str, Species],
    species_nodes: dict[str, NetworkSpeciesNode],
    reactions: list[GeneratedReaction],
    coverage: list[CoverageItem],
    missing_data: list[MissingDataItem],
    truncations: list[TruncationEvent],
) -> ReactionNetwork:
    return attach_reaction_lineage(
        ReactionNetwork(
            species=species,
            species_nodes=species_nodes,
            reactions=reactions,
            coverage=coverage,
            missing_data=missing_data,
            truncations=truncations,
        )
    )
