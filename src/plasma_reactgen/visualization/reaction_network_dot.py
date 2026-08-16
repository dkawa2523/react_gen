from __future__ import annotations

from typing import Any

from plasma_reactgen.visualization.graphviz_dot import (
    GraphEdge,
    reaction_edge_attributes,
    render_species_graph,
)
from plasma_reactgen.visualization.graphviz_edges import (
    mapped_species_edges,
    non_electron_species,
    reaction_changes_species,
)
from plasma_reactgen.visualization.graphviz_options import GraphvizOptions
from plasma_reactgen.visualization.models import VisualizationDataset


def build_reaction_network_dot(
    dataset: VisualizationDataset,
    *,
    options: GraphvizOptions,
) -> str:
    states_by_id = {str(state.get("id")): state for state in dataset.states}
    edges = _network_edges(dataset.reactions, states_by_id, options)
    node_ids = set(states_by_id)
    for source, target, _ in edges:
        node_ids.update((source, target))
    case_name = str(dataset.case.get("name", "case"))
    return render_species_graph(
        graph_name="reaction_network",
        title=f"Reaction network: {case_name}",
        states_by_id=states_by_id,
        node_ids=node_ids,
        edges=edges,
        concentrate=False,
        arrow_size="0.7",
    )


def _network_edges(
    reactions: list[dict[str, Any]],
    states_by_id: dict[str, dict[str, Any]],
    options: GraphvizOptions,
) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    considered = 0
    for reaction in reactions:
        if options.max_reactions is not None and considered >= options.max_reactions:
            break
        added = _reaction_edges(reaction, states_by_id, options)
        edges.extend(added)
        considered += bool(added)
    return edges


def _reaction_edges(
    reaction: dict[str, Any],
    states_by_id: dict[str, dict[str, Any]],
    options: GraphvizOptions,
) -> list[GraphEdge]:
    reactants = non_electron_species(reaction.get("reactants"))
    products = non_electron_species(reaction.get("products"))
    if not reactants or not products:
        return []
    if not options.include_non_expanding and not reaction_changes_species(
        reactants,
        products,
    ):
        return []
    mapped = mapped_species_edges(
        reaction=reaction,
        reactants=reactants,
        products=products,
        states_by_id=states_by_id,
    )
    return [
        (source, target, reaction_edge_attributes(reaction))
        for source, target in mapped
        if options.include_self_loops or source != target
    ]


__all__ = ["build_reaction_network_dot"]
