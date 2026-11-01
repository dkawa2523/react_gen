"""Equation agreement includes the represented collision and material context."""

from dataclasses import replace

import pytest

from reactgen.assessment import assess_consistency
from reactgen.chemistry import candidate_state, electron_state
from reactgen.model import CandidateSet, ReactionCandidate, Term


def channel(family: str, **context) -> tuple[ReactionCandidate, CandidateSet]:
    atom = candidate_state({"Ar": 1}, 0)
    ion = candidate_state({"Ar": 1}, 1)
    electron = electron_state()
    if family == "electron":
        terms = (Term(electron.id), Term(atom.id))
    elif family == "ion":
        terms = (Term(ion.id), Term(atom.id))
    else:
        terms = (Term(atom.id, 2),)
    return (
        ReactionCandidate("test", terms, terms, family, "elastic", "test", "test", 0, **context),
        CandidateSet(states={state.id: state for state in (atom, ion, electron)}),
    )


@pytest.mark.parametrize("material", [None, "", " "])
def test_surface_family_requires_an_explicit_material_reservoir(material: str | None) -> None:
    reaction, states = channel("surface", surface=material)
    result = assess_consistency(reaction, states)
    assert result.verdict == "fail"
    assert result.basis == ("collision participants",)


@pytest.mark.parametrize("family", ["electron", "ion", "neutral"])
def test_a_material_reservoir_cannot_silently_change_a_gas_collision_family(family: str) -> None:
    reaction, states = channel(family, surface="wall")
    assert assess_consistency(reaction, states).verdict == "fail"


def test_ion_family_does_not_absorb_an_incident_electron() -> None:
    reaction, states = channel("electron")
    ion = next(state for state in states.states.values() if state.charge == 1)
    terms = (Term("e"), Term(ion.id))
    reaction = replace(reaction, family="ion", reactants=terms, products=terms)
    assert assess_consistency(reaction, states).verdict == "fail"
    assert assess_consistency(replace(reaction, family="electron"), states).verdict == "pass"


@pytest.mark.parametrize("family", ["electron", "ion", "neutral", "surface"])
def test_an_extra_collider_requires_its_own_process_model(family: str) -> None:
    context = {"surface": "wall"} if family == "surface" else {}
    reaction, states = channel(family, **context)
    assert assess_consistency(reaction, states).verdict == "pass"
    result = assess_consistency(replace(reaction, third_body="M"), states)
    assert result.verdict == "unknown"
    assert {item.responsibility for item in result.requirements} == {"external_models"}


def test_extra_collider_does_not_hide_a_defined_process_contradiction() -> None:
    reaction, states = channel("neutral", third_body="M")
    dimer = candidate_state({"Ar": 2}, 0)
    states.states[dimer.id] = dimer
    reaction = replace(reaction, products=(Term(dimer.id),))
    assert assess_consistency(reaction, states).verdict == "fail"


def test_explicit_three_body_association_keeps_its_defined_gas_pattern() -> None:
    # Cantera's documented gas form is A + B + M -> AB + M. Surface
    # participation is a different context, not supplied by this template.
    atom, molecule = candidate_state({"O": 1}, 0), candidate_state({"O": 2}, 0)
    states = CandidateSet(states={state.id: state for state in (atom, molecule)})
    reaction = ReactionCandidate(
        "test",
        (Term(atom.id, 2),),
        (Term(molecule.id),),
        "neutral",
        "three_body_association",
        "test",
        "test",
        0,
        third_body="M",
    )
    assert assess_consistency(reaction, states).verdict == "pass"
    surface = replace(reaction, family="surface", surface="wall")
    assert assess_consistency(surface, states).verdict == "fail"
