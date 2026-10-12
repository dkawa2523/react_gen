"""Patterns have family/participant scope; missing support is not a denial."""

from dataclasses import replace
from itertools import permutations

import pytest

from reactgen.assessment import assess_consistency
from reactgen.chemistry import candidate_state
from reactgen.generate import candidates
from reactgen.model import CandidateSet, ReactionCandidate, Term, reaction_id


def channel(process: str, products: tuple[Term, ...], **options) -> ReactionCandidate:
    reaction = ReactionCandidate(
        "",
        (Term("e"), Term("Ar@ground")),
        products,
        "electron",
        process,
        "test",
        "test",
        1,
        **options,
    )
    return replace(reaction, id=reaction_id(reaction.key))


def test_unsupported_process_keeps_known_balance_and_unknown_semantics() -> None:
    result = assess_consistency(
        channel("new_process", (Term("e"), Term("Ar@ground"))), candidates(("Ar",))
    )
    assert result.verdict == "unknown"
    assert result.basis == ("element conservation", "charge conservation")
    assert "no defined equation pattern" in result.message


@pytest.mark.parametrize(
    ("products", "basis"),
    [
        ((Term("e"), Term("Ar@ground", 2)), "element conservation"),
        ((Term("Ar@ground"),), "charge conservation"),
    ],
)
def test_unknown_process_cannot_hide_balance_violation(products, basis) -> None:
    result = assess_consistency(channel("new_process", products), candidates(("Ar",)))
    assert result.verdict == "fail"
    assert result.basis == (basis,)


@pytest.mark.parametrize("process", ["ionization", "penning_ionization", "quenching"])
def test_defined_process_mismatch_is_not_missing_support(process) -> None:
    result = assess_consistency(
        channel(process, (Term("e"), Term("Ar@ground"))), candidates(("Ar",))
    )
    assert result.verdict == "fail"
    assert result.basis == ("process equation pattern",)


def test_missing_reference_precedes_unsupported_process() -> None:
    result = assess_consistency(
        channel("new_process", (Term("e"), Term("missing@ground"))), candidates(("Ar",))
    )
    assert result.verdict == "fail"
    assert result.basis == ("state index",)


@pytest.mark.parametrize("resolution", ["resolved", "lumped"])
def test_quenching_to_a_non_ground_target_is_outside_the_template_not_inconsistent(
    resolution: str,
) -> None:
    upper = candidate_state({"Ne": 1}, 0, "resolved", label="upper")
    lower = candidate_state({"Ne": 1}, 0, "electronic", label="lower", resolution=resolution)
    partner = candidate_state({"H": 2}, 0)
    state_set = CandidateSet({state.id: state for state in (upper, lower, partner)})
    reaction = combination_channel(
        "quenching", (Term(upper.id), Term(partner.id)), (Term(lower.id), Term(partner.id))
    )
    result = assess_consistency(reaction, state_set)
    assert result.verdict == "unknown"
    assert result.basis == ("element conservation", "charge conservation")


def test_state_transfer_does_not_treat_a_phase_change_as_ground_state_quenching() -> None:
    upper = candidate_state({"Ne": 1}, 0, "resolved", label="upper")
    lower = candidate_state({"Ne": 1}, 0, phase="solid")
    partner = candidate_state({"H": 2}, 0)
    state_set = CandidateSet({state.id: state for state in (upper, lower, partner)})
    reaction = combination_channel(
        "quenching", (Term(upper.id), Term(partner.id)), (Term(lower.id), Term(partner.id))
    )
    assert assess_consistency(reaction, state_set).verdict == "fail"


@pytest.mark.parametrize("changed", [{"phase": "solid"}, {"structure": "other"}])
def test_state_transfer_preserves_the_partner_physical_identity(changed: dict) -> None:
    upper = candidate_state({"Ne": 1}, 0, "resolved", label="upper")
    lower = candidate_state({"Ne": 1}, 0)
    partner = candidate_state({"H": 2}, 0)
    changed_partner = candidate_state({"H": 2}, 0, **changed)
    state_set = CandidateSet(
        {state.id: state for state in (upper, lower, partner, changed_partner)}
    )
    reaction = combination_channel(
        "quenching", (Term(upper.id), Term(partner.id)), (Term(lower.id), Term(changed_partner.id))
    )
    assert assess_consistency(reaction, state_set).verdict == "fail"


def test_vibrational_relaxation_requires_a_changing_vibrational_donor() -> None:
    excited = candidate_state({"Ne": 1}, 0, "electronic")
    atom = candidate_state({"Ne": 1}, 0)
    vibration = candidate_state({"H": 2}, 0, "vibrational", label="v1")
    molecule = candidate_state({"H": 2}, 0)
    state_set = CandidateSet({state.id: state for state in (excited, atom, vibration, molecule)})
    spectator = combination_channel(
        "v_t_relaxation",
        (Term(excited.id), Term(vibration.id)),
        (Term(atom.id), Term(vibration.id)),
    )
    donor = combination_channel(
        "v_t_relaxation",
        (Term(excited.id), Term(vibration.id)),
        (Term(excited.id), Term(molecule.id)),
    )
    assert assess_consistency(spectator, state_set).verdict == "fail"
    assert assess_consistency(donor, state_set).verdict == "pass"


def combination_channel(
    process: str,
    reactants: tuple[Term, ...],
    products: tuple[Term, ...],
    family: str = "neutral",
    **options,
) -> ReactionCandidate:
    reaction = ReactionCandidate(
        "", reactants, products, family, process, "test", "test", 1, **options
    )
    return replace(reaction, id=reaction_id(reaction.key))


@pytest.fixture(scope="module")
def oxygen_states() -> CandidateSet:
    # Generic physical identities, independent of Registry and generation rules.
    states = [candidate_state({"O": count}, charge) for count in (1, 2, 3) for charge in (0, 1)]
    electron = candidates(("Ar",)).states["e"]
    return CandidateSet({state.id: state for state in (*states, electron)})


@pytest.mark.parametrize("charge", [0, 1])
def test_unimolecular_dissociation_has_a_non_electron_pattern(
    oxygen_states: CandidateSet, charge: int
) -> None:
    # IUPAC D01801: one entity separates into two or more; M03989 alone
    # cannot attest an elementary step or the activation that preceded it.
    suffix = "+" if charge else ""
    reaction = combination_channel(
        "dissociation",
        (Term(f"O3{suffix}@ground"),),
        (Term(f"O2{suffix}@ground"), Term("O@ground")),
        "ion" if charge else "unimolecular",
    )
    result = assess_consistency(reaction, oxygen_states)
    assert result.verdict == "pass"
    assert "process equation pattern" in result.basis
    assert "physical occurrence is undetermined" in result.message
    assert "activation mechanism" in result.message


def test_same_fragments_have_a_distinct_electron_induced_pattern(
    oxygen_states: CandidateSet,
) -> None:
    reaction = combination_channel(
        "dissociation",
        (Term("e"), Term("O3@ground")),
        (Term("e"), Term("O2@ground"), Term("O@ground")),
        "electron",
    )
    assert assess_consistency(reaction, oxygen_states).verdict == "pass"
    mislabeled = replace(reaction, family="neutral")
    result = assess_consistency(mislabeled, oxygen_states)
    assert result.verdict == "fail"
    assert result.basis == ("collision participants",)


@pytest.mark.parametrize("charge", [0, 1])
def test_two_particle_association_does_not_prove_stabilization(
    oxygen_states: CandidateSet, charge: int
) -> None:
    # IUPAC 08184 uses A + B -> AB; the equation is not a rate law review.
    suffix = "+" if charge else ""
    reaction = combination_channel(
        "association",
        (Term(f"O2{suffix}@ground"), Term("O@ground")),
        (Term(f"O3{suffix}@ground"),),
        "ion" if charge else "neutral",
    )
    result = assess_consistency(reaction, oxygen_states)
    assert result.verdict == "pass"
    assert "energy stabilization is unspecified" in result.message
    assert "physical occurrence is undetermined" in result.message
    assert reaction.stabilization is None


def test_association_self_collision_counts_stoichiometry(oxygen_states: CandidateSet) -> None:
    reaction = combination_channel("association", (Term("O@ground", 2),), (Term("O2@ground"),))
    assert assess_consistency(reaction, oxygen_states).verdict == "pass"


@pytest.mark.parametrize(
    ("process", "reactants", "products"),
    [
        ("dissociation", (Term("O2@ground"),), (Term("O2@ground"),)),
        ("association", (Term("O2@ground"),), (Term("O2@ground"),)),
        (
            "association",
            (Term("O2@ground"), Term("O@ground")),
            (Term("O2@ground"), Term("O@ground")),
        ),
        # Existing reactive scattering must not be relaxed to absorb association.
        ("reactive_scattering", (Term("O2@ground"), Term("O@ground")), (Term("O3@ground"),)),
    ],
)
def test_defined_pattern_contradictions_remain_fail(
    oxygen_states: CandidateSet,
    process: str,
    reactants: tuple[Term, ...],
    products: tuple[Term, ...],
) -> None:
    result = assess_consistency(combination_channel(process, reactants, products), oxygen_states)
    assert result.verdict == "fail"
    assert result.basis == ("process equation pattern",)


@pytest.mark.parametrize(
    ("family", "process", "reactants", "products"),
    [
        ("photon", "dissociation", (Term("O3@ground"),), (Term("O2@ground"), Term("O@ground"))),
        (
            "neutral",
            "photon_induced_dissociation",
            (Term("O3@ground"),),
            (Term("O2@ground"), Term("O@ground")),
        ),
        # Two parents do not reveal the inducing mechanism of generic dissociation.
        ("neutral", "dissociation", (Term("O2@ground", 2),), (Term("O@ground", 4),)),
        ("neutral", "association", (Term("O@ground", 3),), (Term("O3@ground"),)),
        # Ionization has a defined electron pattern, but this surface/neutral
        # inducing mechanism is not supplied merely by using that process name.
        ("neutral", "ionization", (Term("O3@ground"),), (Term("O3+@ground"), Term("e"))),
        ("surface", "surface_new_process", (Term("O2@ground"),), (Term("O2@ground"),)),
    ],
)
def test_unsupported_inducing_scope_is_unknown(
    oxygen_states: CandidateSet,
    family: str,
    process: str,
    reactants: tuple[Term, ...],
    products: tuple[Term, ...],
) -> None:
    reaction = combination_channel(
        process, reactants, products, family, **({"surface": "wall"} if family == "surface" else {})
    )
    result = assess_consistency(reaction, oxygen_states)
    assert result.verdict == "unknown"
    assert result.basis == ("element conservation", "charge conservation")
    assert "no defined equation pattern" in result.message


@pytest.mark.parametrize("family", ["neutral", "photon"])
def test_unknown_scope_does_not_hide_a_balance_violation(
    oxygen_states: CandidateSet, family: str
) -> None:
    reaction = combination_channel(
        "photon_induced_dissociation", (Term("O3@ground"),), (Term("O@ground", 2),), family
    )
    result = assess_consistency(reaction, oxygen_states)
    assert result.verdict == "fail"
    assert result.basis == ("element conservation",)


@pytest.mark.parametrize("process", ["association", "dissociation"])
def test_combination_patterns_are_independent_of_term_and_state_order(
    oxygen_states: CandidateSet, process: str
) -> None:
    first, second = (Term("O2@ground"), Term("O@ground")), (Term("O3@ground"),)
    for reverse_states in (False, True):
        indexed = (
            CandidateSet(dict(reversed(list(oxygen_states.states.items()))))
            if reverse_states
            else oxygen_states
        )
        for terms in permutations(first):
            left, right = (terms, second) if process == "association" else (second, terms)
            result = assess_consistency(combination_channel(process, left, right), indexed)
            assert result.verdict == "pass"
