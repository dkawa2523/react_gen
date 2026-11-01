"""Stoichiometric scale never turns different physical states into spectators."""

from dataclasses import replace
from math import log

import pytest

from reactgen.assessment import evaluate
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.records import FormationReference, Property, StateRecord, Thermo
from reactgen.thermo import net_stoichiometry


def inputs(scale: float = 1.0):
    atom, molecule = candidate_state({"O": 1}, 0), candidate_state({"O": 2}, 0)
    reaction = ReactionCandidate(
        "scaled-reaction",
        (Term(molecule.id, scale),),
        (Term(atom.id, 2 * scale),),
        "neutral",
        "dissociation",
        "test",
        "test",
        0,
    )
    return reaction, CandidateSet(
        states={state.id: state for state in (atom, molecule)}, reactions={reaction.id: reaction}
    )


@pytest.mark.parametrize("scale", [1e-10, 1e-100])
def test_small_nonzero_contributors_still_require_their_own_physical_data(scale: float) -> None:
    reaction, candidates = inputs(scale)
    assert net_stoichiometry(reaction) == {"O2@ground": -scale, "O@ground": 2 * scale}
    evaluation = evaluate(candidates, EvidenceCatalog(), Conditions())
    calculations = evaluation.thermochemical_calculations[reaction.id]
    assert {value.status for value in calculations.values()} == {"unavailable"}
    assert all(value.value is None for value in calculations.values())


def test_fractional_scale_changes_gibbs_enthalpy_and_equilibrium_exponent_consistently() -> None:
    base, candidates = inputs()
    reference = FormationReference(298.15, "standard_elements", 100000)
    nasa = Thermo(
        (3.5, 0, 0, 0, 0, 0, 0),
        (3.5, 0, 0, 0, 0, 0, 0),
        200,
        1000,
        6000,
        tier="reviewed",
        phase="gas",
        standard_pressure_Pa=100000,
    )
    records = tuple(
        StateRecord(
            state.id,
            state,
            thermo=nasa,
            properties={
                "enthalpy_formation_eV": Property(
                    value, "eV", tier="reviewed", formation_reference=reference
                )
            },
        )
        for state, value in (
            (candidates.states["O@ground"], 1),
            (candidates.states["O2@ground"], 3),
        )
    )
    catalog = EvidenceCatalog(state_records=records)
    full = evaluate(candidates, catalog, Conditions(gas_temperature_K=300))
    scale = 1e-10
    scaled, scaled_candidates = inputs(scale)
    small = evaluate(scaled_candidates, catalog, Conditions(gas_temperature_K=300))
    actual = small.thermochemical_calculations[scaled.id]
    expected = full.thermochemical_calculations[base.id]
    assert {value.status for value in actual.values()} == {"computed"}
    for quantity in ("delta_h_eV", "delta_g_eV"):
        assert actual[quantity].value == pytest.approx(
            scale * expected[quantity].value, rel=1e-12, abs=0
        )
    constant = "equilibrium_constant_number_density"
    assert log(actual[constant].value) == pytest.approx(
        scale * log(expected[constant].value), rel=1e-6
    )
    assert actual[constant].conditions["equilibrium_constant_density_power"] == scale


@pytest.mark.parametrize("exponent", [0, -10, -200, 100])
def test_opposing_declared_totals_for_the_same_state_cancel(exponent: int) -> None:
    reaction, _ = inputs()
    atom = "O@ground"
    cancelled = replace(
        reaction,
        reactants=(Term(atom, float(f"0.1e{exponent}")), Term(atom, float(f"0.2e{exponent}"))),
        products=(Term(atom, float(f"0.3e{exponent}")),),
    )
    assert net_stoichiometry(cancelled) == {}


@pytest.mark.parametrize("residual", [1e-12, 1e-20, 1e-100])
def test_a_small_residual_of_the_same_state_is_not_an_exact_cancellation(residual: float) -> None:
    reaction, _ = inputs()
    changed = replace(
        reaction,
        reactants=(Term("O@ground"),),
        products=(Term("O@ground"), Term("O@ground", residual)),
    )
    assert net_stoichiometry(changed) == {"O@ground": residual}
