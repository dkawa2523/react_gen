from __future__ import annotations

from plasma_reactgen.application.state_builder import build_state_list
from plasma_reactgen.domain.models import (
    GeneratedReaction,
    NetworkSpeciesNode,
    ReactionNetwork,
    Species,
    SpeciesAmount,
)


class _Rules:
    @staticmethod
    def get_role_required_properties() -> dict:
        return {
            "roles": {
                "electron_target": {"required": ["composition"]},
                "ion_neutral_target": {"required": ["composition"]},
                "ion_neutral_projectile": {"required": ["charge"]},
                "dnt_neutral": {"required": ["mass_amu"]},
                "dnt_ion": {"required": ["mass_amu"]},
            }
        }


def test_state_roles_are_derived_from_reaction_family_without_mutating_nodes() -> None:
    species = {
        "e": Species("e", {}, -1, {"electron"}),
        "Ar": Species("Ar", {"Ar": 1}, 0, {"neutral"}),
        "Ar+": Species("Ar+", {"Ar": 1}, 1, {"ion"}),
        "F": Species("F", {"F": 1}, 0, {"neutral"}),
    }
    nodes = {
        species_id: NetworkSpeciesNode(species_id, 0, roles={"input_gas"}) for species_id in species
    }
    network = ReactionNetwork(
        species,
        nodes,
        [
            _reaction("electron", ["e", "Ar"]),
            _reaction("ion_neutral", ["Ar+", "Ar"]),
            _reaction("ion_neutral", ["e", "F", "missing"]),
        ],
        [],
    )

    states = {state["id"]: state for state in build_state_list(network, _Rules())}

    assert states["Ar"]["roles"] == [
        "dnt_neutral",
        "electron_target",
        "input_gas",
        "ion_neutral_target",
    ]
    assert states["Ar"]["missing_properties"] == ["mass_amu"]
    assert states["Ar+"]["roles"] == ["dnt_ion", "input_gas", "ion_neutral_projectile"]
    assert states["F"]["roles"] == ["dnt_neutral", "input_gas", "ion_neutral_target"]
    assert states["e"]["roles"] == ["input_gas"]
    assert all(node.roles == {"input_gas"} for node in nodes.values())


def _reaction(family: str, reactants: list[str]) -> GeneratedReaction:
    return GeneratedReaction(
        id=f"{family}_{'_'.join(reactants)}",
        depth=0,
        family=family,
        type="test",
        equation="test",
        reactants=[SpeciesAmount(species_id) for species_id in reactants],
        products=[],
        source_pair_key="test",
        source_pair_label="test",
        introduced_species=[],
        validation={},
        data_status={},
    )
