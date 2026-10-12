"""Small, source-backed state reviews must retain their independent scope.

NIST ASD 5.12 O I/O II ground-state and level tables were checked on 2026-10-11.
O I 1D2 is also tabulated as 15867.862 cm-1 in the NIST Handbook (MG93).
The O2 NASA7 fit is the neutral gas entry TPIS89 in Cantera v3.2.0 air.yaml;
checking this representation does not establish the source's experimental error.
"""

from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from reactgen.assessment import assess_state, assess_state_thermochemistry
from reactgen.evidence import EvidenceCatalog, registry_state_candidate
from reactgen.model import CandidateSet
from reactgen.registry import Registry
from reactgen.thermo import GAS_CONSTANT, enthalpy_RT, entropy_R, valid_thermo

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def reviewed_states() -> tuple[Registry, EvidenceCatalog]:
    return Registry.load(ROOT / "registry"), EvidenceCatalog.load(ROOT / "registry")


@pytest.mark.parametrize(
    ("species_id", "term", "angular_momentum", "parity", "degeneracy"),
    [("O", "3P", "2", "even", 5), ("O+", "4S", "3/2", "odd", 4), ("O_1D", "1D", "2", "even", 5)],
)
def test_individual_oxygen_identity_review_preserves_the_resolved_level(
    reviewed_states, species_id, term, angular_momentum, parity, degeneracy
) -> None:
    registry, catalog = reviewed_states
    species = registry.species[species_id]
    candidate = registry_state_candidate(species)
    evidence = catalog.state(candidate)
    assert evidence.match == "exact"
    assert (candidate.phase, candidate.state.resolution) == ("gas", "resolved")
    record = evidence.records[0]
    assert (record.term, record.j, record.parity, record.degeneracy) == (
        term,
        angular_momentum,
        parity,
        degeneracy,
    )
    # The level weight is not the weight of the whole term or a population law.
    assert record.degeneracy == 2 * Fraction(record.j) + 1
    assert record.configuration
    assert record.lifetime_s is None
    assert "physics.nist.gov" in record.existence_source
    assert "physics.nist.gov" in record.source["citation"]
    candidates = CandidateSet(states={candidate.id: candidate})
    assert assess_state(candidate, evidence, candidates).verdict == "pass"
    # Reviewing existence and IE did not silently approve the imported enthalpy.
    assert record.properties["enthalpy_formation_eV"].tier == "imported"
    assert assess_state_thermochemistry(candidate, evidence).verdict == "unknown"


def test_oxygen_ground_ionization_energies_keep_their_own_target_and_errors(
    reviewed_states,
) -> None:
    registry, _ = reviewed_states
    first = registry.species["O"].properties["ionization_energy_eV"]
    second = registry.species["O+"].properties["ionization_energy_eV"]
    assert (first.value, first.unit, first.uncertainty.absolute) == (13.618055, "eV", 0.000007)
    assert (second.value, second.unit, second.uncertainty.absolute) == (35.12112, "eV", 0.00006)
    assert "O I ground to O II ground" in first.source
    assert "O II ground to O III ground" in second.source
    assert first.tier == second.tier == "reviewed"
    assert registry.species["O"].properties["electron_affinity_eV"].tier == "imported"


def test_oxygen_1d_energy_is_relative_to_3p2_without_an_invented_error(reviewed_states) -> None:
    registry, _ = reviewed_states
    species = registry.species["O_1D"]
    prop = species.properties["excitation_energy_eV"]
    # E = h c (100 * wavenumber_cm-1) / e, with exact SI h, c and e.
    converted_eV = 6.62607015e-34 * 299792458 * 100 * 15867.862 / 1.602176634e-19
    assert prop.value == species.state.energy_eV == 1.9673642
    assert prop.value == pytest.approx(converted_eV, abs=5e-8)
    assert prop.tier == "reviewed"
    assert prop.unit == "eV"
    assert prop.uncertainty is not None
    assert prop.uncertainty.absolute is prop.uncertainty.relative is prop.uncertainty.factor is None
    assert "blank" in prop.uncertainty.note
    # The legacy fit remains visible, independently imported and ineligible.
    assert species.thermo is not None
    assert species.thermo.tier == "imported"
    assert not valid_thermo(species.thermo)
    assert "enthalpy-only shift" in species.thermo.source
    assert species.properties["ionization_energy_eV"].value is None


def test_oxygen_nasa_fit_review_does_not_approve_all_molecular_properties(reviewed_states) -> None:
    registry, catalog = reviewed_states
    species = registry.species["O2"]
    candidate = registry_state_candidate(species)
    evidence = catalog.state(candidate)
    assert (
        assess_state(candidate, evidence, CandidateSet(states={candidate.id: candidate})).verdict
        == "pass"
    )
    assert assess_state_thermochemistry(candidate, evidence).verdict == "pass"
    thermo = species.thermo
    assert thermo is not None
    assert valid_thermo(thermo)
    assert (thermo.t_min, thermo.t_mid, thermo.t_max) == (200, 1000, 3500)
    assert thermo.standard_pressure_Pa == 101325
    assert thermo.tier == "reviewed"
    assert "v3.2.0/data/air.yaml" in thermo.source
    assert "TPIS89" in thermo.source
    assert species.properties["ionization_energy_eV"].tier == "imported"
    assert species.properties["enthalpy_formation_eV"].tier == "imported"
    for excited_id in ("O2_a1Delta", "O2_b1Sigma"):
        excited = registry.species[excited_id]
        assert excited.thermo is not None
        assert excited.thermo.tier == "imported"


def test_oxygen_nasa_fit_has_the_standard_enthalpy_and_thermal_diatomic_limit(
    reviewed_states,
) -> None:
    registry, _ = reviewed_states
    thermo = registry.species["O2"].thermo
    # Elemental O2 has zero standard formation enthalpy at 298.15 K. This
    # particular fit differs from zero only by its coefficient rounding.
    assert enthalpy_RT(thermo, 298.15) * GAS_CONSTANT * 298.15 == pytest.approx(0, abs=1e-3)
    for temperature in (300.0, 1500.0):
        step = 0.001 * temperature
        lower, upper = temperature - step, temperature + step
        heat_capacity = (
            enthalpy_RT(thermo, upper) * GAS_CONSTANT * upper
            - enthalpy_RT(thermo, lower) * GAS_CONSTANT * lower
        ) / (2 * step)
        entropy_derivative = (entropy_R(thermo, upper) - entropy_R(thermo, lower)) / (2 * step)
        assert heat_capacity > 0
        assert heat_capacity == pytest.approx(
            temperature * GAS_CONSTANT * entropy_derivative, rel=1e-6
        )
        if temperature == 300:
            # Translation plus thermal rotation approaches 7R/2; vibration
            # raises it slightly in this temperature range.
            assert 3.5 < heat_capacity / GAS_CONSTANT < 3.6
    low = replace(thermo, t_mid=1000.0001)
    assert enthalpy_RT(low, 1000) == pytest.approx(enthalpy_RT(thermo, 1000), abs=1e-7)
    assert entropy_R(low, 1000) == pytest.approx(entropy_R(thermo, 1000), abs=1e-7)
