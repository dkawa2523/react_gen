"""Source-based regressions for reviewed energy and kinetics declarations."""

from __future__ import annotations

from math import exp
from pathlib import Path

import pytest

from reactgen import export
from reactgen.assessment import assess_consistency, assess_reaction_evidence
from reactgen.case import Case, Conditions, Limits
from reactgen.evidence import (
    EvidenceCatalog,
    ReactionEvidence,
    registry_reaction_candidate,
    registry_state_candidate,
)
from reactgen.model import CandidateSet
from reactgen.numeric import DataUse, data_use
from reactgen.pipeline import analyze
from reactgen.records import RegistryReaction, dataset_payload, normalized_dataset
from reactgen.registry import Registry

ROOT = Path(__file__).resolve().parents[1] / "registry"
JPL_CHANNELS = (
    "O1D_O2_quenching_O2_b1Sigma_O3P_term",
    "O1D_O2_quenching_O2_a1Delta_O3P_term",
)
TOTAL_PROCESS_CHANNELS = (
    "e_O2p_dissociative_recombination",
    "Arp_O2_charge_transfer",
    "O2a_O2_self_quenching",
)


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(ROOT)


@pytest.fixture(scope="module")
def catalog() -> EvidenceCatalog:
    return EvidenceCatalog.load(ROOT)


def _channel(registry: Registry, channel_id: str) -> RegistryReaction:
    return next(
        channel
        for channels in registry.channels.values()
        for channel in channels
        if channel.id == channel_id
    )


def _use(registry: Registry, channel_id: str, conditions: Conditions) -> DataUse:
    channel = _channel(registry, channel_id)
    candidate = registry_reaction_candidate(channel, registry.species)
    assert candidate is not None
    return data_use(
        candidate, ReactionEvidence(overlay_datasets=tuple(channel.datasets)), conditions
    )


def test_ground_oxygen_dissociation_and_ionization_use_distinct_endpoint_energies(
    registry: Registry, catalog: EvidenceCatalog
) -> None:
    case = Case(
        "oxygen screening",
        ("O2",),
        Conditions(
            collision_energy_eV=6,
            collision_energy_frame="com",
            projectile_state="e",
            target_state="O2@ground",
        ),
        limits=Limits(max_atoms=2, max_depth=1),
        supplies=("e",),
    )
    result = analyze(case, catalog).evaluation
    # Wang et al. (2024) D0 in cm^-1, and the NIST SRD69 adiabatic IE in eV.
    for channel_id, endpoint, verdict in (
        ("e_O2_dissociation_O_O", 41269.19 * 1.239841984e-4, "pass"),
        ("e_O2_ionization", 12.0697, "fail"),
    ):
        channel = registry_reaction_candidate(_channel(registry, channel_id), registry.species)
        assert channel is not None
        assert result.reaction_assessments[channel.id]["energy"].verdict == verdict
        margin = result.thermochemical_calculations[channel.id]["collision_energy_margin_eV"]
        assert margin.value == pytest.approx(6 - endpoint)


def test_fluorocarbon_oxidation_uses_four_same_reference_ground_energies(
    registry: Registry, catalog: EvidenceCatalog
) -> None:
    case = Case(
        "fluorocarbon oxidation",
        ("CF3",),
        Conditions(
            collision_energy_eV=0.1,
            collision_energy_frame="com",
            projectile_state="CF3@ground",
            target_state="O@ground",
        ),
        limits=Limits(max_atoms=4, max_depth=1, max_reactions=100),
        supplies=("O",),
    )
    result = analyze(case, catalog)
    branch = registry_reaction_candidate(_channel(registry, "CF3_O_to_CF2O_F"), registry.species)
    assert branch is not None
    assessment = result.evaluation.reaction_assessments[branch.id]["energy"]
    difference = result.evaluation.thermochemical_calculations[branch.id][
        "state_energy_difference_eV"
    ]
    # ATcT v1.228 ΔfH°(0 K), kJ/mol for COF2, F, CF3 and O.
    assert difference.value == pytest.approx((-603.33 + 77.284 + 465.11 - 246.843) / 96.48533212)
    assert {term["target"] for term in difference.inputs} == {
        "CF3@ground",
        "O@ground",
        "COF2@ground",
        "F@ground",
    }
    assert all(term["provider"] == "ATcT" for term in difference.inputs)
    assert not difference.alternatives
    assert assessment.verdict == "pass"
    for state in ("CF3@ground", "COF2@ground"):
        assert result.evaluation.state_assessments[state]["state"].verdict == "pass"


@pytest.mark.parametrize("temperature", [100.0, 298.0, 400.0])
def test_jpl_nominal_channel_sum_and_dimensions_match_the_evaluated_total(
    registry: Registry,
    temperature: float,
) -> None:
    # NASA/JPL 25-1 Table 1A / Note A3: 3.3e-11 exp(55/T) cm3/s,
    # term-summed yields 0.8 and 0.2; recommended range 100--400 K.
    values = [
        _use(registry, channel_id, Conditions(gas_temperature_K=temperature))
        for channel_id in JPL_CHANNELS
    ]
    assert all(value.status == "coefficient" for value in values)
    assert all(value.unit == "m3/s" for value in values)
    first, second = values[0].value, values[1].value
    assert first is not None
    assert second is not None
    total = 3.3e-11 * 1e-6 * exp(55 / temperature)
    assert first + second == pytest.approx(total, rel=1e-12, abs=0)
    assert first / total == pytest.approx(0.8)
    assert second / total == pytest.approx(0.2)
    if temperature == 298:
        # Table k(298 K) is reported separately and rounded from the fit.
        assert total == pytest.approx(3.95e-17, rel=0.01, abs=0)


@pytest.mark.parametrize("temperature", [99.0, 401.0])
def test_jpl_channels_do_not_extrapolate_beyond_the_evaluated_data_range(
    registry: Registry,
    temperature: float,
) -> None:
    for channel_id in JPL_CHANNELS:
        result = _use(registry, channel_id, Conditions(gas_temperature_K=temperature))
        assert result.status == "unavailable"
        assert result.datasets[0].status == "out_of_range"
        assert result.value is None


def test_jpl_rate_needs_gas_temperature_not_electron_temperature(registry: Registry) -> None:
    result = _use(registry, JPL_CHANNELS[0], Conditions(electron_temperature_eV=1))
    assert result.status == "needs_input"
    assert result.required_inputs == ("gas_temperature",)
    assert result.value is None


def test_source_branching_declarations_survive_without_invented_combined_errors(
    registry: Registry,
) -> None:
    first, second = (_channel(registry, channel_id).datasets[0] for channel_id in JPL_CHANNELS)
    assert first.params["branching_fraction"] + second.params["branching_fraction"] == 1
    assert first.params["branching_fraction_uncertainty"] == 0.2
    assert second.params["branching_fraction_minimum"] == 0
    assert second.params["branching_fraction_maximum"] == 0.4
    for dataset in (first, second):
        assert dataset.tier == "derived"
        assert dataset.params["A"] == pytest.approx(
            dataset.params["source_total_A"] * 1e-6 * dataset.params["branching_fraction"],
            rel=1e-12,
            abs=0,
        )
        assert dataset.parameter_units["source_total_A"] == "cm3/s"
        assert dataset.params["b"] == 0
        assert dataset.params["Ea"] == -55
        assert dataset.parameter_units["Ea"] == "K"
        assert dataset.reaction_order == 2
        assert dataset.uncertainty is not None
        assert dataset.uncertainty.bounds(dataset.params["A"]) is None
        assert normalized_dataset(dataset_payload(dataset)) == dataset


def test_self_quenching_preserves_the_reported_absolute_error_and_original_units(
    registry: Registry,
) -> None:
    # Wildt et al. 1988, DOI 10.1016/0301-0104(88)80027-2, primary abstract.
    dataset = _channel(registry, "O2a_O2_self_quenching").datasets[0]
    assert dataset.params["value"] == pytest.approx(
        dataset.params["source_value"] * 1e-6, rel=1e-12, abs=0
    )
    assert dataset.uncertainty is not None
    assert dataset.uncertainty.absolute == pytest.approx(
        dataset.params["source_uncertainty"] * 1e-6, rel=1e-12, abs=0
    )
    assert dataset.uncertainty.bounds(dataset.params["value"]) == pytest.approx(
        (1.3e-24, 1.7e-24), rel=1e-12, abs=0
    )
    assert dataset.parameter_units["source_value"] == "cm3/s"
    assert dataset.parameter_units["source_uncertainty"] == "cm3/s"
    assert normalized_dataset(dataset_payload(dataset)) == dataset


@pytest.mark.parametrize(
    "conditions",
    [Conditions(), Conditions(gas_temperature_K=700)],
)
def test_unknown_product_scope_precedes_missing_measurement_temperature(
    registry: Registry,
    conditions: Conditions,
) -> None:
    result = _use(registry, "O2a_O2_self_quenching", conditions)
    assert result.status == "unavailable"
    assert result.required_inputs == ()
    assert result.value is None
    assert result.datasets[0].reason == "total data do not determine this product channel"
    dataset = _channel(registry, "O2a_O2_self_quenching").datasets[0]
    assert dataset.validity is not None
    assert dataset.validity.minimum is None
    assert dataset.validity.maximum is None
    assert "not verified" in dataset.source["applicability_review"]


@pytest.mark.parametrize("channel_id", TOTAL_PROCESS_CHANNELS)
def test_primary_abstract_total_rates_do_not_attest_exact_state_products(
    registry: Registry, catalog: EvidenceCatalog, channel_id: str
) -> None:
    # Gaucherel/Rowe 1977 abstracts report species-level products; Wildt 1988
    # obtains a-state self-quenching from fluorescence decay, not product
    # state-resolved detection. These boundaries remain after user inputs.
    channel = _channel(registry, channel_id)
    candidate = registry_reaction_candidate(channel, registry.species)
    assert candidate is not None
    states = {state.id: state for state in map(registry_state_candidate, registry.species.values())}
    assert assess_consistency(candidate, CandidateSet(states=states)).verdict == "pass"
    evidence = catalog.reaction(candidate)
    assert assess_reaction_evidence(candidate, evidence).verdict == "unknown"
    assert channel.status == "needs_review"
    dataset = channel.datasets[0]
    assert dataset.status == "literature_supported"
    assert dataset.reviewed  # Independent numerical transcription qualification.
    assert dataset.channel_scope == "total_process"
    assert dataset.reaction_order == 2
    assert dataset.observable == "reaction_rate"
    result = data_use(candidate, evidence, Conditions(gas_temperature_K=700))
    assert result.status == "unavailable"
    assert result.dataset_id is None
    assert result.value is None
    assert result.datasets[0].reason == "total data do not determine this product channel"


def test_total_rate_declarations_survive_canonical_result_roundtrip(
    registry: Registry, catalog: EvidenceCatalog, tmp_path: Path
) -> None:
    # Preserve the two primary-abstract cm3/s declarations and Wildt's error;
    # unknown source applicability is not supplied by a 700 K analysis case.
    original_values = {
        "e_O2p_dissociative_recombination": 8.2e-9,
        "Arp_O2_charge_transfer": 6.3e-11,
        "O2a_O2_self_quenching": 1.5e-18,
    }
    case = Case(
        "source scope",
        ("Ar", "O2"),
        Conditions(gas_temperature_K=700),
        # Supply the exact entrances here to test the record roundtrip directly.
        supplies=("e", "Ar+", "O2+", "O2@a1dg"),
        limits=Limits(max_depth=1, max_atoms=2, max_reactions=300),
    )
    result = analyze(case, catalog)
    export.write(tmp_path, result)
    saved = export.read(tmp_path, verify_views=True)
    for channel_id, source_value in original_values.items():
        channel = _channel(registry, channel_id)
        candidate = registry_reaction_candidate(channel, registry.species)
        assert candidate is not None
        dataset = channel.datasets[0]
        assert dataset.params["source_value"] == pytest.approx(source_value, rel=1e-12, abs=0)
        assert dataset.parameter_units["source_value"] == "cm3/s"
        assert dataset.params["value"] == pytest.approx(source_value * 1e-6, rel=1e-12, abs=0)
        assert dataset.unit == "m3/s"
        assert (
            "sciencedirect.com/science/article/abs/pii/" in dataset.source["primary_abstract_url"]
        )
        assert dataset.source["measurement"]
        assert dataset.source["applicability_review"]
        assert normalized_dataset(dataset_payload(dataset)) == dataset
        reaction = next(item for item in saved["reactions"] if item["id"] == candidate.id)
        declaration = next(
            item
            for record in reaction["evidence"]["records"]
            for item in record["datasets"]
            if item["id"] == dataset.id
        )
        assert normalized_dataset(declaration) == dataset
        assert reaction["assessments"]["reaction_evidence"]["verdict"] == "unknown"
        assert reaction["data_use"]["status"] == "unavailable"
        assert reaction["data_use"]["value"] is None
