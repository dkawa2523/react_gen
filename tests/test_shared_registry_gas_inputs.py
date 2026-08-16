from pathlib import Path

import pytest

from plasma_reactgen.application.config import case_config_from_dict
from plasma_reactgen.application.network_builder import (
    NetworkBuilderDependencies,
    ReactionNetworkBuilder,
)
from plasma_reactgen.infrastructure.file_registry import FileRegistry

ROOT = Path(__file__).resolve().parents[1]


def test_ar_o2_is_assembled_from_reusable_reaction_pairs() -> None:
    network = _generate(["Ar", "O2"])
    reactions = {reaction.id: reaction for reaction in network.reactions}

    assert {
        "e_O2_dissociation_O_O",
        "e_O2_attachment_Om_O",
        "Arp_O2_charge_transfer",
        "Arp_O2_dissociative_charge_transfer_Op_O",
        "e_O2p_dissociative_recombination",
        "e_O_ionization",
        "e_O_excitation_O_1D",
        "e_O2_excitation_O2_a1Delta",
        "e_O2_excitation_O2_b1Sigma",
        "O1D_O2_quenching_O2_b1Sigma",
        "O1D_O2_quenching_O2_a1Delta",
        "O2a_O2_self_quenching",
        "Op_O2_charge_transfer",
    } <= reactions.keys()
    assert reactions["Arp_O2_charge_transfer"].depth == 1
    assert reactions["e_O2p_dissociative_recombination"].depth == 1
    assert reactions["e_O_ionization"].depth == 1
    assert reactions["O1D_O2_quenching_O2_b1Sigma"].depth == 1
    assert reactions["O1D_O2_quenching_O2_a1Delta"].depth == 1
    assert reactions["Op_O2_charge_transfer"].depth == 2
    assert network.species_nodes["O_1D"].propagated is True
    assert network.species_nodes["O2_a1Delta"].propagated is True
    assert network.species_nodes["O2_b1Sigma"].propagated is True
    b1_rate = reactions["O1D_O2_quenching_O2_b1Sigma"].datasets[0]
    a1_rate = reactions["O1D_O2_quenching_O2_a1Delta"].datasets[0]
    assert b1_rate.parameters["branching_fraction"] == pytest.approx(0.8)
    assert a1_rate.parameters["branching_fraction"] == pytest.approx(0.2)
    assert b1_rate.parameters["A"] + a1_rate.parameters["A"] == pytest.approx(3.3e-17)
    _assert_complete_and_balanced(network)


def test_ar_sf6_o2_reaches_secondary_fragments_without_a_mixture_pack() -> None:
    network = _generate(["Ar", "SF6", "O2"])
    reactions = {reaction.id: reaction for reaction in network.reactions}

    assert {
        "e_SF6_attachment_parent",
        "e_SF6_attachment_Fm_SF5",
        "e_SF6_dissociation_SF5_F",
        "e_SF5_ionization",
        "e_SF5_dissociative_attachment_Fm_SF4",
        "Arp_SF6_dissociative_charge_transfer_SF5p_F",
        "Arp_O2_charge_transfer",
    } <= reactions.keys()
    assert reactions["e_SF5_ionization"].depth == 1
    assert reactions["e_SF5_dissociative_attachment_Fm_SF4"].depth == 1
    assert reactions["Arp_SF6_dissociative_charge_transfer_SF5p_F"].depth == 1
    assert reactions[
        "Arp_SF6_dissociative_charge_transfer_SF5p_F"
    ].deltaE_products_minus_reactants_eV == pytest.approx(-0.439612)
    assert "SF5" in network.species
    assert "SF5+" in network.species
    _assert_complete_and_balanced(network)


def test_shared_registry_expansion_is_deterministic() -> None:
    first = _generate(["Ar", "SF6", "O2"])
    second = _generate(["Ar", "SF6", "O2"])

    def signature(network):
        return [
            (reaction.id, reaction.depth, reaction.precursor_reaction_ids)
            for reaction in network.reactions
        ]

    assert signature(first) == signature(second)


def test_excited_state_follow_up_reactions_remain_opt_in() -> None:
    network = _generate(["O2"], propagate_excited_states=False)
    reaction_ids = {reaction.id for reaction in network.reactions}

    assert network.species_nodes["O2_a1Delta"].propagated is False
    assert network.species_nodes["O2_b1Sigma"].propagated is False
    assert network.species_nodes["O_1D"].propagated is False
    assert "O2a_O2_self_quenching" not in reaction_ids
    assert "O1D_O2_quenching_O2_b1Sigma" not in reaction_ids


def _generate(gases: list[str], *, propagate_excited_states: bool = True):
    registry = FileRegistry(ROOT / "registry")
    config = case_config_from_dict(
        {
            "case": {"name": "shared_registry_test"},
            "gases": gases,
            "expansion": {
                "max_depth": None,
                "propagate_excited_states": propagate_excited_states,
            },
            "data_policy": {"allowed_status": ["curated", "literature_supported"]},
        }
    )
    dependencies = NetworkBuilderDependencies(registry, registry, registry)
    return ReactionNetworkBuilder(dependencies).generate(config)


def _assert_complete_and_balanced(network) -> None:
    assert network.generation_complete
    assert all(item.status != "missing" for item in network.coverage)
    assert all(
        reaction.validation
        == {"species_reference": "ok", "charge_balance": "ok", "element_balance": "ok"}
        for reaction in network.reactions
    )
