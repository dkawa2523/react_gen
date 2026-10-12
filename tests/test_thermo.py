"""NASA7 reference conditions and number-density equilibrium dimensions.

The analytical polynomials assign twice the atomic H/RT and S/R to the
diatomic species, giving zero reaction standard Gibbs energy at any T.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from reactgen.chemistry import candidate_state
from reactgen.model import ReactionCandidate, Term
from reactgen.records import StateRecord, Thermo
from reactgen.thermo import (
    AVOGADRO,
    GAS_CONSTANT,
    equilibrium_constant,
    gibbs_energy_eV,
    reverse_rate,
)


def _reaction(left, right) -> ReactionCandidate:
    return ReactionCandidate("test", left, right, "neutral", "association", "mechanical", "test", 1)


def _species() -> dict[str, StateRecord]:
    atomic = Thermo(
        (3.5, 0, 0, 0, 0, 0, 0),
        (3.5, 0, 0, 0, 0, 0, 0),
        200,
        1000,
        6000,
        tier="reviewed",
        phase="gas",
        standard_pressure_Pa=100000,
    )
    diatomic = replace(
        atomic,
        low=tuple(2 * value for value in atomic.low),
        high=tuple(2 * value for value in atomic.high),
    )
    atom = candidate_state({"F": 1}, 0)
    molecule = candidate_state({"F": 2}, 0)
    return {
        atom.id: StateRecord(atom.id, atom, thermo=atomic),
        molecule.id: StateRecord(molecule.id, molecule, thermo=diatomic),
    }


@pytest.mark.parametrize("direction", [-1, 0, 1])
def test_number_density_equilibrium_constant_has_the_delta_nu_exponent(direction: int) -> None:
    if direction == 1:
        reaction = _reaction((Term("F2@ground"),), (Term("F@ground", 2),))
    elif direction == -1:
        reaction = _reaction((Term("F@ground", 2),), (Term("F2@ground"),))
    else:
        reaction = _reaction(
            (Term("F@ground"), Term("F2@ground")), (Term("F@ground"), Term("F2@ground"))
        )
    temperature = 300.0
    reference_number_density = 100000.0 / (GAS_CONSTANT * temperature) * AVOGADRO
    assert gibbs_energy_eV(reaction, _species(), temperature) == pytest.approx(0, abs=1e-12)
    assert equilibrium_constant(reaction, _species(), temperature) == pytest.approx(
        reference_number_density**direction
    )


def test_reversed_reaction_equilibrium_constants_are_reciprocal() -> None:
    forward = _reaction((Term("F2@ground"),), (Term("F@ground", 2),))
    backward = replace(forward, reactants=forward.products, products=forward.reactants)
    first = equilibrium_constant(forward, _species(), 300)
    second = equilibrium_constant(backward, _species(), 300)
    assert first is not None
    assert second is not None
    assert first * second == pytest.approx(1)
    assert reverse_rate(2e-15, forward, _species(), 300) == pytest.approx(2e-15 / first)


@pytest.mark.parametrize(
    "change",
    [
        {"phase": "solid"},
        {"standard_pressure_Pa": None},
        {"standard_pressure_Pa": 101325},
        {"t_min": 400.0},
    ],
)
def test_incompatible_phase_reference_or_temperature_is_not_evaluated(change: dict) -> None:
    reaction = _reaction((Term("F2@ground"),), (Term("F@ground", 2),))
    species = _species()
    record = species["F2@ground"]
    species[record.id] = replace(record, thermo=replace(record.thermo, **change))
    assert gibbs_energy_eV(reaction, species, 300) is None
    assert equilibrium_constant(reaction, species, 300) is None


def test_electron_nonthermal_distribution_is_not_a_nasa_equilibrium_species() -> None:
    reaction = _reaction((Term("e"), Term("F2@ground")), (Term("e"), Term("F@ground", 2)))
    assert equilibrium_constant(reaction, _species(), 300) is None
