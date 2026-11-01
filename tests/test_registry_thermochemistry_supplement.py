"""NASA source fits retain their reference and narrow scientific qualification."""

from pathlib import Path

import pytest

from reactgen.records import Thermo
from reactgen.registry import Registry
from reactgen.thermo import (
    AVOGADRO,
    GAS_CONSTANT,
    JOULE_PER_EV,
    enthalpy_RT,
    entropy_R,
)

REGISTRY = Path(__file__).resolve().parents[1] / "registry"


def nasa_fit(registry: Registry, species_id: str) -> Thermo:
    species = registry.species[species_id]
    fits = [species.thermo, *(record.thermo for record in species.records)]
    return next(
        fit for fit in fits if fit is not None and fit.provenance.collection == "NASA_TM_4513_gas"
    )


@pytest.mark.parametrize(
    ("species_id", "source_h_over_r"),
    [("CH4", -8972.26656), ("H2O", -29084.8168)],
)
def test_formation_model_reproduces_primary_report_reference(
    species_id: str, source_h_over_r: float
) -> None:
    # NASA TM-4513 Table II, printed pp.19/32 (PDF pp.23/36), final
    # H(298.15)/R column. Check the original assigned reference in K before
    # applying the current SI gas constant; this is not a measurement error.
    registry = Registry.load(REGISTRY)
    fit = nasa_fit(registry, species_id)
    assert 298.15 * enthalpy_RT(fit, 298.15) == pytest.approx(source_h_over_r, abs=1e-4)
    record = next(
        record
        for record in registry.species[species_id].records
        if record.provenance.collection == "NASA_TM_4513_gas"
    )
    prop = record.properties["enthalpy_formation_eV"]
    assert prop.value == pytest.approx(
        source_h_over_r * GAS_CONSTANT / (AVOGADRO * JOULE_PER_EV), abs=1e-8
    )
    assert prop.method == "calculated"
    assert prop.tier == "derived"
    assert prop.reviewed_for("enthalpy_formation_eV")
    assert prop.formation_reference is not None
    assert prop.formation_reference.temperature_K == 298.15
    assert prop.formation_reference.standard_pressure_Pa == 100000


def test_nasa_model_review_keeps_domain_and_other_claims_independent() -> None:
    registry = Registry.load(REGISTRY)
    for species in registry.species.values():
        fits = [species.thermo, *(record.thermo for record in species.records)]
        for fit in fits:
            if fit is None or fit.provenance.collection != "NASA_TM_4513_gas":
                continue
            assert fit.standard_pressure_Pa == 100000
            assert not fit.reviewed_for("state_existence")
            assert not fit.reviewed_for("channel_assertion")
            for temperature in (
                fit.t_min + (fit.t_max - fit.t_min) * index / 20 for index in range(21)
            ):
                step = 1e-4 * temperature
                if not fit.t_min + step < temperature < fit.t_max - step:
                    continue
                if abs(temperature - fit.t_mid) <= step:
                    continue
                cp_over_r = (
                    (temperature + step) * enthalpy_RT(fit, temperature + step)
                    - (temperature - step) * enthalpy_RT(fit, temperature - step)
                ) / (2 * step)
                assert cp_over_r > 0
                assert temperature * (
                    entropy_R(fit, temperature + step) - entropy_R(fit, temperature - step)
                ) / (2 * step) == pytest.approx(cp_over_r, rel=2e-6)


def test_nasa_ions_and_outside_reference_temperature_are_not_promoted() -> None:
    registry = Registry.load(REGISTRY)
    for species in registry.species.values():
        fits = [species.thermo, *(record.thermo for record in species.records)]
        for fit in fits:
            if fit is None or fit.provenance.collection != "NASA_TM_4513_gas":
                continue
            if species.charge:
                assert fit.tier == "imported"
                assert not fit.reviewed_for("thermochemical_model")
        for record in species.records:
            if record.provenance.collection != "NASA_TM_4513_gas":
                continue
            prop = record.properties.get("enthalpy_formation_eV")
            if prop is not None:
                assert species.charge == 0
                fit = prop.source_declaration["parent_thermo"]
                assert fit["t_min"] <= 298.15 <= fit["t_max"]
    assert registry.species["H2O"].state.existence == "unknown"
    assert registry.species["OH"].state.existence == "unknown"
