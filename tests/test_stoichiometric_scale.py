"""Conservation and canonical keys use declared counts independently of scale."""

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen import export
from reactgen.balance import conservation, imbalance
from reactgen.case import Case
from reactgen.chemistry import candidate_state, electron_state, parse_equation
from reactgen.evidence import EvidenceCatalog
from reactgen.model import Term, side_key
from reactgen.pipeline import analyze
from reactgen.records import ReactionRecord, RegistryReaction


@pytest.mark.parametrize("scale", [1.0, 1e-10, 1e-100])
def test_small_element_or_charge_losses_are_not_treated_as_conservation(scale: float) -> None:
    atom, molecule = candidate_state({"O": 1}, 0), candidate_state({"O": 2}, 0)
    ion = candidate_state({"O": 1}, 1)
    states = {state.id: state for state in (atom, molecule, ion)}
    balanced = conservation((Term(molecule.id, scale),), (Term(atom.id, 2 * scale),), states)
    assert balanced.elements_conserved
    lost_atom = conservation((Term(molecule.id, scale),), (Term(atom.id, scale),), states)
    assert not lost_atom.elements_conserved
    assert lost_atom.element_differences == {"O": -scale}
    lost_charge = conservation((Term(ion.id, scale),), (Term(atom.id, scale),), states)
    assert lost_charge.elements_conserved
    assert not lost_charge.charge_conserved
    assert lost_charge.charge_difference == -scale


@pytest.mark.parametrize("residual", [1e-12, 1e-20, 1e-100])
def test_a_tiny_additional_term_survives_large_equal_spectators(residual: float) -> None:
    atom, electron = candidate_state({"O": 1}, 0), electron_state()
    states = {state.id: state for state in (atom, electron)}
    left = (Term(atom.id), Term(electron.id))
    right = (*left, Term(atom.id, residual), Term(electron.id, residual))
    result = conservation(left, right, states)
    assert not result.elements_conserved
    assert not result.charge_conserved
    assert result.element_differences == {"O": residual}
    assert result.charge_difference == -residual
    record = RegistryReaction("extra", "electron", "elastic", list(left), list(right))
    assert imbalance(record, states) is not None


def test_fractional_atom_multiplication_and_duplicate_terms_share_canonical_arithmetic() -> None:
    atom, molecule = candidate_state({"O": 1}, 0), candidate_state({"O": 3}, 0)
    states = {state.id: state for state in (atom, molecule)}
    left = (Term(molecule.id, 0.1),)
    right = (Term(atom.id, 0.3),)
    assert conservation(left, right, states).elements_conserved
    assert side_key((Term(atom.id, 0.1), Term(atom.id, 0.2))) == side_key(right)
    record = RegistryReaction("fractional", "neutral", "dissociation", list(left), list(right))
    assert imbalance(record, states) is None
    assert imbalance(replace(record, products=[*right, Term(atom.id, 1e-20)]), states) is not None


def test_fractional_source_equation_retains_identity_through_result_storage(tmp_path: Path) -> None:
    parsed = parse_equation("0.1 Ar + 0.2 Ar -> 0.3 Ar")
    assert parsed is not None
    equation, states = parsed
    assert equation[2] == equation[3] == (("Ar@ground", 0.3),)
    record = ReactionRecord("fractional", equation, "neutral", "elastic", states)
    result = analyze(
        Case("fractional source", ("Ar",)), EvidenceCatalog(reaction_records=(record,))
    )
    target = next(
        reaction
        for reaction in result.candidates.reactions.values()
        if reaction.equation_key == equation
    )
    export.write(tmp_path / "result", result)
    document = export.read(tmp_path / "result", verify_views=True)
    saved = next(reaction for reaction in document["reactions"] if reaction["id"] == target.id)
    assert saved["reactants"] == saved["products"] == [{"species": "Ar@ground", "n": 0.3}]
    assert saved["thermochemical_calculations"]["equilibrium_constant_number_density"]["value"] == 1
