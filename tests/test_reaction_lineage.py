from plasma_reactgen.application.reaction_lineage import attach_reaction_lineage
from plasma_reactgen.domain.models import (
    GeneratedReaction,
    NetworkSpeciesNode,
    ReactionNetwork,
    SpeciesAmount,
)


def test_multistep_lineage_is_deterministic_and_acyclic():
    network = _network()

    attach_reaction_lineage(network)

    by_id = {reaction.id: reaction for reaction in network.reactions}
    assert by_id["r0_a"].depth == 0
    assert by_id["r0_a"].precursor_reaction_ids == []
    assert by_id["r1"].precursor_reaction_ids == ["r0_a", "r0_b"]
    assert by_id["r2"].precursor_reaction_ids == ["r1"]
    first = {reaction.id: list(reaction.precursor_reaction_ids) for reaction in network.reactions}
    attach_reaction_lineage(network)
    assert {reaction.id: reaction.precursor_reaction_ids for reaction in network.reactions} == first


def test_same_depth_producer_cannot_create_a_cycle():
    network = _network()
    network.reactions.append(_reaction("same_depth", 1, "C", "B"))

    attach_reaction_lineage(network)

    by_id = {reaction.id: reaction for reaction in network.reactions}
    assert by_id["same_depth"].precursor_reaction_ids == []


def _network() -> ReactionNetwork:
    reactions = [
        _reaction("r0_b", 0, "A", "B"),
        _reaction("r0_a", 0, "A", "B"),
        _reaction("r1", 1, "B", "C"),
        _reaction("r2", 2, "C", "D"),
    ]
    return ReactionNetwork(
        species={},
        species_nodes={
            "A": NetworkSpeciesNode(
                species_id="A",
                depth_first_seen=0,
                introduced_by=["input_gas"],
                roles={"input_gas"},
            )
        },
        reactions=reactions,
        coverage=[],
    )


def _reaction(reaction_id: str, depth: int, reactant: str, product: str) -> GeneratedReaction:
    return GeneratedReaction(
        id=reaction_id,
        depth=depth,
        family="electron",
        type="dissociation",
        equation=f"e + {reactant} -> e + {product}",
        reactants=[SpeciesAmount("e"), SpeciesAmount(reactant)],
        products=[SpeciesAmount("e"), SpeciesAmount(product)],
        source_pair_key=f"electron|e|{reactant}",
        source_pair_label=f"e + {reactant}",
        introduced_species=[product],
        validation={"charge_balance": "ok", "element_balance": "ok"},
        data_status={"reaction": "curated"},
    )
