"""Formula-only candidate generation and its physical invariants."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from reactgen.assessment import assess_consistency
from reactgen.case import Limits
from reactgen.chemistry import (
    candidate_state,
    electronic_character,
    formula_scope,
    neutral_reactive_candidate,
    parse_state_id,
)
from reactgen.generate import _Generator, candidates

FULL_SCOPE = Limits(max_depth=16, max_reactions=20000)


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
    generated = candidates(("Ar", "SF6", "O2"), FULL_SCOPE)
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


@pytest.mark.parametrize("gases", [("O", "O2"), ("Ar", "CF4"), ("Ar", "SF6", "O2")])
def test_seed_order_and_duplicates_do_not_change_candidates(gases: tuple[str, ...]) -> None:
    forward = candidates(gases, FULL_SCOPE)
    reordered = candidates((*reversed(gases), gases[0]), FULL_SCOPE)
    assert forward.complete
    assert reordered.complete
    assert forward.states == reordered.states
    assert forward.reactions == reordered.reactions


@pytest.mark.parametrize(("seed", "extra"), [("O", "O2"), ("F", "F2"), ("CF2", "CF4")])
def test_adding_a_seed_keeps_existing_candidates(seed: str, extra: str) -> None:
    original = candidates((seed,), FULL_SCOPE)
    expanded = candidates((seed, extra), FULL_SCOPE)
    assert original.complete
    assert expanded.complete
    assert original.states.keys() <= expanded.states.keys()
    assert original.reactions.keys() <= expanded.reactions.keys()
    assert f"{seed}@electronic" in expanded.states


@pytest.mark.parametrize("gases", [("CF4",), ("Ar", "CF4"), ("SF6", "O2")])
def test_complete_means_reapplying_the_same_rules_adds_nothing(gases: tuple[str, ...]) -> None:
    generated = candidates(gases, FULL_SCOPE)
    assert generated.complete
    generator = _Generator(FULL_SCOPE)
    generator.result = generated
    generator.feed = {
        state.id for state in generated.states.values() if "input" in state.introduced_by
    }
    generator._state_keys = {state.key: state.id for state in generated.states.values()}
    generator._reaction_keys = {reaction.key for reaction in generated.reactions.values()}
    before_states = set(generated.states)
    before_reactions = set(generated.reactions)
    snapshot = tuple(state for state in generated.states.values() if state.id != "e")
    generator._electron(snapshot, 20)
    generator._ion(snapshot, 20)
    generator._neutral(snapshot, 20)
    assert set(generated.states) == before_states
    assert set(generated.reactions) == before_reactions


def test_origin_classes_do_not_change_generation_eligibility() -> None:
    original = candidates(("Ar", "CF4"), FULL_SCOPE)
    assert original.complete
    generator = _Generator(FULL_SCOPE)
    generator.result = original
    generator.feed = {"Ar@ground", "CF4@ground"}
    generator.result.states = {
        state.id: replace(state, classes=state.classes | {"fragment", "rearranged"})
        for state in original.states.values()
    }
    generator._state_keys = {state.key: state.id for state in original.states.values()}
    generator._reaction_keys = {reaction.key for reaction in original.reactions.values()}
    before = set(original.reactions)
    snapshot = tuple(state for state in original.states.values() if state.id != "e")
    generator._electron(snapshot, 20)
    generator._ion(snapshot, 20)
    generator._neutral(snapshot, 20)
    assert set(original.reactions) == before


def test_new_ion_pair_splits_both_collision_partners() -> None:
    generated = candidates(("CF4",), FULL_SCOPE)
    pair = {"CF3+@ground", "CF4@ground"}
    processes = {
        reaction.process
        for reaction in generated.reactions.values()
        if {term.species for term in reaction.reactants} == pair
    }
    assert {"collision_induced_dissociation", "projectile_dissociation"} <= processes


def test_complex_projectile_can_dissociate_without_a_neutral_complex() -> None:
    generated = candidates(("Ar", "CF4"), FULL_SCOPE)
    assert "ArF@ground" not in generated.states
    assert any(
        reaction.process == "projectile_dissociation"
        and {term.species for term in reaction.reactants} == {"ArF+@ground", "CF4@ground"}
        and {term.species for term in reaction.products} == {"Ar+@ground", "F@ground", "CF4@ground"}
        for reaction in generated.reactions.values()
    )


def test_self_collision_uses_existing_relaxation_without_inventing_pooling() -> None:
    generated = candidates(("Ar",), FULL_SCOPE)
    assert any(
        reaction.process == "quenching"
        and len(reaction.reactants) == 1
        and reaction.reactants[0].species == "Ar@metastable"
        and reaction.reactants[0].n == 2
        for reaction in generated.reactions.values()
    )
    assert not any(reaction.process == "pooling" for reaction in generated.reactions.values())


def test_three_body_association_has_exactly_two_explicit_reactants() -> None:
    generated = candidates(("CF4",), replace(FULL_SCOPE, max_leaving_atoms=3))
    assert generated.complete
    associations = [
        reaction
        for reaction in generated.reactions.values()
        if reaction.process == "three_body_association"
    ]
    assert associations
    assert all(sum(term.n for term in reaction.reactants) == 2 for reaction in associations)
    assert all(reaction.third_body == "M" for reaction in associations)


def test_input_species_must_fit_the_limit_before_exploration() -> None:
    with pytest.raises(ValueError, match="cannot retain.*use at least 2"):
        candidates(("Ar",), Limits(max_species=1))
    with pytest.raises(ValueError, match="cannot retain.*use at least 3"):
        candidates(("Ar", "O2"), Limits(max_species=2))
    truncated = candidates(("Ar", "Ar"), Limits(max_species=2))
    assert not truncated.complete
    assert {"e", "Ar@ground"} <= truncated.states.keys()


@pytest.mark.parametrize("composition", [{"Ar": 1}, {"Ar": 2}, {"S": 1, "F": 5}])
@pytest.mark.parametrize("charge", [-3, -2, -1, 0, 1, 2, 3])
def test_state_id_round_trip_keeps_atom_counts_and_charge(
    composition: dict[str, int],
    charge: int,
) -> None:
    state = candidate_state(composition, charge, resolution="resolved")
    parsed = parse_state_id(state.id)
    assert parsed is not None
    assert parsed.key == state.key
    assert parsed.id == state.id


@pytest.mark.parametrize(
    ("phase", "structure"),
    [("gas", None), ("solid", None), ("unknown", "source:structure/1;tag=2")],
)
def test_state_identity_round_trip_preserves_phase_and_structure(
    phase: str,
    structure: str | None,
) -> None:
    state = candidate_state({"C": 2, "H": 6, "O": 1}, 0, phase=phase, structure=structure)
    parsed = parse_state_id(state.id)
    assert parsed is not None
    assert parsed.key == state.key
    assert parsed.phase == phase
    assert parsed.structure == structure


def test_completion_reports_only_the_mechanical_scope() -> None:
    generated = candidates(("Ar",))
    assert generated.completion == {"mechanical": True}
    stopped = candidates(("Ar",), Limits(max_depth=1))
    assert stopped.completion == {"mechanical": False}
    assert all(
        reaction.stabilization == "unspecified"
        for reaction in generated.reactions.values()
        if reaction.process in {"attachment", "recombination"}
    )


@pytest.mark.parametrize(
    ("kind", "label", "resolution"),
    [
        ("ground", "", "resolved"),
        ("ground", "", "lumped"),
        ("electronic", "", "lumped"),
        ("electronic", "4s", "lumped"),
        ("electronic", "4s", "resolved"),
        ("vibrational", "v1", "resolved"),
        ("metastable", "3P2", "resolved"),
        ("resolved", "1D", "resolved"),
        ("resolved", "ground", "resolved"),
        ("resolved", "term;level=2", "resolved"),
        ("resolved", "2Σ+ % term", "resolved"),
    ],
)
def test_identity_signature_keeps_kind_label_and_resolution(
    kind: str,
    label: str,
    resolution: str,
) -> None:
    state = candidate_state(
        {"Ar": 1},
        2,
        kind,
        label=label,
        resolution=resolution,
        phase="unknown",
        structure="identity/source;1",
    )
    parsed = parse_state_id(state.id)
    assert parsed is not None
    assert parsed.key == state.key
    assert parsed.state == state.state
    assert parsed.id == state.id


def test_different_resolution_has_a_distinct_identity() -> None:
    lumped = candidate_state({"Ar": 1}, 0, "electronic", label="4s", resolution="lumped")
    resolved = candidate_state({"Ar": 1}, 0, "electronic", label="4s", resolution="resolved")
    assert lumped.id != resolved.id
    assert lumped.key != resolved.key
