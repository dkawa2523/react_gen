"""Formula-only candidate generation and its physical invariants."""

from __future__ import annotations

from collections import Counter

import pytest

from reactgen.assessment import assess_consistency
from reactgen.case import Limits
from reactgen.chemistry import (
    electronic_character,
    formula_scope,
    neutral_reactive_candidate,
)
from reactgen.generate import candidates


@pytest.mark.parametrize("gas", ["Ar", "O2", "CF4", "SF6", "SiH4"])
def test_supported_feed_formulas_generate_without_a_registry(gas: str) -> None:
    generated = candidates((gas,))
    assert generated.states
    assert generated.reactions
    assert f"{gas}@ground" in generated.states


@pytest.mark.parametrize("written", ["argon", "Ar+", "O2(v=1)", "O0", "not-a-formula", 3])
def test_feed_must_be_a_neutral_ground_state_formula(written: object) -> None:
    with pytest.raises(ValueError, match="formula|neutral ground-state"):
        candidates((written,))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "gases",
    [("Ar", "O2"), ("Ar", "CF4"), ("SF6",), ("Ar", "SF6", "O2")],
)
def test_every_mechanical_reaction_conserves_elements_and_charge(
    gases: tuple[str, ...],
) -> None:
    generated = candidates(gases)
    assert {
        assess_consistency(reaction, generated).verdict for reaction in generated.reactions.values()
    } == {"pass"}


def test_electron_ion_and_neutral_templates_participate_in_the_frontier() -> None:
    generated = candidates(("SF6",))
    by_family = Counter(reaction.family for reaction in generated.reactions.values())
    assert all(by_family[family] for family in ("electron", "ion", "neutral"))
    assert any(reaction.depth == 4 for reaction in generated.reactions.values())
    deep_states = {
        state.id
        for state in generated.states.values()
        if state.depth >= 3 and ("fragment" in state.classes or "ion" in state.classes)
    }
    assert deep_states
    assert any(
        reaction.depth >= 4
        and deep_states.intersection(
            term.species for term in (*reaction.reactants, *reaction.products)
        )
        for reaction in generated.reactions.values()
    )


def test_generation_does_not_grow_beyond_the_largest_feed() -> None:
    generated = candidates(("Ar", "SF6", "O2"))
    assert max(sum(state.composition.values()) for state in generated.states.values()) <= 7


def test_formula_roles_do_not_claim_that_every_fragment_is_a_radical() -> None:
    generated = candidates(("SF6", "O2"))
    assert all("radical" not in state.classes for state in generated.states.values())
    assert electronic_character({"F": 2}, 0) == "closed_shell"
    assert electronic_character({"S": 1, "F": 5}, 0) == "open_shell"
    assert electronic_character({"C": 1, "F": 2}, 0) == "unknown"


def test_neutral_grammar_is_bounded_and_avoids_neutral_noble_exchange() -> None:
    generated = candidates(("Ar", "SF6", "O2"))
    assert generated.complete
    assert len(generated.reactions) < generated.limits["max_reactions"]
    assert "ArO@ground" not in generated.states
    assert any(
        reaction.process == "three_body_association" and reaction.third_body == "M"
        for reaction in generated.reactions.values()
    )
    assert not [
        reaction
        for reaction in generated.reactions.values()
        if reaction.process == "radical_abstraction" and reaction.reactants == reaction.products
    ]


def test_ion_grammar_keeps_resonant_transport_and_bounded_ligand_transfer() -> None:
    generated = candidates(("Ar", "CF4"))
    resonant = [
        reaction
        for reaction in generated.reactions.values()
        if reaction.process == "resonant_charge_exchange"
    ]
    assert resonant
    assert all("momentum_transfer" in reaction.kinetic_effects for reaction in resonant)
    assert "ArF+@ground" in generated.states
    assert "complex_ion" in generated.states["ArF+@ground"].classes
    assert "ArF@ground" not in generated.states
    assert any(
        reaction.process == "ligand_transfer" and "ArF+@ground" in reaction.equation
        for reaction in generated.reactions.values()
    )


def test_formula_scope_does_not_infer_a_multicentre_structure() -> None:
    assert formula_scope({"C": 1, "F": 4}) == "central_ligand"
    assert formula_scope({"N": 2, "O": 1}) == "formula_only"
    assert formula_scope({"C": 2, "H": 6, "O": 1}) == "formula_only"
    generated = candidates(("C2H6O",))
    assert not [
        reaction
        for reaction in generated.reactions.values()
        if reaction.process
        in {"dissociation", "radical_abstraction", "ligand_transfer", "reactive_scattering"}
    ]


def test_valence_deficient_etch_and_deposition_fragments_remain_reactive() -> None:
    assert neutral_reactive_candidate({"C": 1, "F": 2})
    assert neutral_reactive_candidate({"Si": 1, "H": 2})
    assert not neutral_reactive_candidate({"C": 1, "F": 4})
    assert not neutral_reactive_candidate({"Si": 1, "H": 4})
    assert not neutral_reactive_candidate({"C": 1, "O": 2})

    expected = {
        "CF4": ("CF2@ground", "CF2@ground + CF4@ground -> 2 CF3@ground"),
        "SiH4": ("SiH2@ground", "SiH2@ground + SiH4@ground -> 2 SiH3@ground"),
    }
    for feed, (fragment, equation) in expected.items():
        generated = candidates((feed,))
        assert "reactive_candidate" in generated.states[fragment].classes
        assert any(
            reaction.process == "radical_abstraction" and reaction.equation == equation
            for reaction in generated.reactions.values()
        )


def test_generation_grammar_has_no_same_sign_ion_collision_or_fast_species() -> None:
    generated = candidates(("SF6",))
    for reaction in generated.reactions.values():
        charged = [
            generated.states[term.species].charge
            for term in reaction.reactants
            if generated.states[term.species].charge and term.species != "e"
        ]
        assert not (len(charged) > 1 and all(charge > 0 for charge in charged))
        assert not (len(charged) > 1 and all(charge < 0 for charge in charged))
    assert not [state_id for state_id in generated.states if "fast" in state_id.lower()]
    assert any(
        "fast_product" in reaction.kinetic_effects for reaction in generated.reactions.values()
    )


def test_safety_limit_reports_an_incomplete_candidate_set() -> None:
    generated = candidates(("SF6",), Limits(max_depth=1))
    assert not generated.complete
    assert generated.stop_reason == "max_depth=1"


def test_reaction_ids_and_order_are_deterministic() -> None:
    first = candidates(("CF4",))
    second = candidates(("CF4",))
    assert list(first.states) == list(second.states)
    assert list(first.reactions) == list(second.reactions)
    assert all(
        reaction_id.startswith("rxn_") and len(reaction_id) == 16 for reaction_id in first.reactions
    )
