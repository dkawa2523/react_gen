"""Narrow source reviews retain temperature, state and model boundaries."""

from math import log
from pathlib import Path

import pytest

from reactgen.assessment import assess_consistency, assess_reaction_evidence, assess_state
from reactgen.case import Conditions
from reactgen.evidence import EvidenceCatalog, registry_reaction_candidate, registry_state_candidate
from reactgen.model import CandidateSet
from reactgen.numeric import data_use
from reactgen.registry import Registry
from reactgen.thermo import enthalpy_RT, entropy_R

ROOT = Path(__file__).resolve().parents[1] / "registry"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(ROOT)


@pytest.fixture(scope="module")
def catalog() -> EvidenceCatalog:
    return EvidenceCatalog.load(ROOT)


@pytest.mark.parametrize(
    ("projectile", "target", "source_rate"),
    [
        ("C2F3", "F", 1e-12),
        ("CF3", "F", 1e-12),
        ("CF2", "F", 4.17e-13),
        ("CF2", "CF2", 5.01e-14),
        ("CF2", "CF", 1e-12),
        ("CF", "F", 5.01e-15),
        ("CFO", "F", 7.94e-11),
        ("CO", "F", 1.29e-11),
    ],
)
def test_model_association_rate_is_limited_to_its_source_temperature(
    registry: Registry, catalog: EvidenceCatalog, projectile: str, target: str, source_rate: float
) -> None:
    # Son et al. 2014, p. 242 and Table 1: heavy-particle rates adopted at 700 K.
    record = registry.channels[("neutral_neutral", projectile, target)][0]
    reaction = registry_reaction_candidate(record, registry.species)
    assert reaction is not None
    evidence = catalog.reaction(reaction)
    value = data_use(reaction, evidence, Conditions(gas_temperature_K=700))
    assert value.status == "coefficient"
    assert value.value == pytest.approx(source_rate * 1e-6, rel=1e-12, abs=0)
    assert value.unit == "m3/s"
    assert evidence.datasets[0].reaction_order == 2
    assert data_use(reaction, evidence, Conditions()).required_inputs == ("gas_temperature",)
    assert data_use(reaction, evidence, Conditions(gas_temperature_K=300)).status == "unavailable"
    assert reaction.stabilization == "unspecified"
    states = {state.id: state for state in map(registry_state_candidate, registry.species.values())}
    judgment = assess_consistency(reaction, CandidateSet(states=states))
    assert judgment.verdict == "pass"  # Equation shape; stabilization remains unspecified.


def test_pooling_equation_does_not_establish_a_lumped_rate(
    registry: Registry, catalog: EvidenceCatalog
) -> None:
    record = registry.channels[("neutral_neutral", "Ar_4s", "Ar_4s")][0]
    reaction = registry_reaction_candidate(record, registry.species)
    assert reaction is not None
    states = {state.id: state for state in map(registry_state_candidate, registry.species.values())}
    assert reaction.process == "penning_ionization"
    assert assess_consistency(reaction, CandidateSet(states=states)).verdict == "pass"
    assert record.delta_e_eV is None
    evidence = catalog.reaction(reaction)
    assert assess_reaction_evidence(reaction, evidence).verdict == "unknown"
    assert data_use(reaction, evidence, Conditions()).value is None
    lumped = registry_state_candidate(registry.species["Ar_4s"])
    assert (
        assess_state(lumped, catalog.state(lumped), CandidateSet(states=states)).verdict
        == "unknown"
    )


@pytest.mark.parametrize(
    ("species_id", "ionization", "uncertainty"),
    [("Ar", 15.7596119, 5e-7), ("Ar+", 27.62967, 0.00012)],
)
def test_ground_level_and_ionization_have_separate_nist_support(
    registry: Registry,
    catalog: EvidenceCatalog,
    species_id: str,
    ionization: float,
    uncertainty: float,
) -> None:
    candidate = registry_state_candidate(registry.species[species_id])
    evidence = catalog.state(candidate)
    assert (
        assess_state(candidate, evidence, CandidateSet(states={candidate.id: candidate})).verdict
        == "pass"
    )
    record = evidence.preferred
    assert record is not None
    assert record.existence_source is not None
    prop = record.properties["ionization_energy_eV"]
    assert prop.value == pytest.approx(ionization)
    assert prop.uncertainty is not None
    assert prop.uncertainty.absolute == pytest.approx(uncertainty)
    assert prop.tier == "reviewed"
    assert record.properties["enthalpy_formation_eV"].tier == "imported"


def test_reviewed_argon_nasa_has_monatomic_heat_capacity_and_explicit_reference(
    registry: Registry,
) -> None:
    thermo = registry.species["Ar"].thermo
    assert thermo is not None
    assert thermo.phase == "gas"
    assert thermo.standard_pressure_Pa == 101325
    assert thermo.tier == "reviewed"
    # Ideal monatomic Cp/R=5/2 and dS/R=dT*(Cp/R)/T, across the region boundary.
    for low, high in ((300, 1000), (1000, 5000)):
        cp_over_r = (high * enthalpy_RT(thermo, high) - low * enthalpy_RT(thermo, low)) / (
            high - low
        )
        assert cp_over_r == pytest.approx(2.5)
        assert entropy_R(thermo, high) - entropy_R(thermo, low) == pytest.approx(
            2.5 * log(high / low)
        )
    assert registry.species["Ar+"].thermo is not None
    assert registry.species["Ar+"].thermo.tier == "imported"
