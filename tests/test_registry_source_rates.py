"""Source review distinguishes model rates from unresolved physical scope."""

from math import exp
from pathlib import Path

import pytest

from reactgen.assessment import assess_consistency, assess_reaction_evidence
from reactgen.case import Conditions
from reactgen.evidence import (
    EvidenceCatalog,
    ReactionEvidence,
    registry_reaction_candidate,
    registry_state_candidate,
)
from reactgen.model import CandidateSet
from reactgen.numeric import data_use
from reactgen.records import RegistryReaction, dataset_payload, normalized_dataset
from reactgen.registry import Registry
from reactgen.selection import DataSelection

ROOT = Path(__file__).resolve().parents[1] / "registry"
PATEAU = "doi:10.1116/1.4853675"
SON = "doi:10.1007/s11090-013-9513-1"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return Registry.load(ROOT)


def _source_channels(registry: Registry, source: str) -> list[RegistryReaction]:
    return [
        channel
        for group in registry.channels.values()
        for channel in group
        if channel.source.get("source_id") == source
    ]


def test_two_to_one_source_model_equations_do_not_claim_scattering_or_stabilization(
    registry: Registry,
) -> None:
    states = {state.id: state for state in map(registry_state_candidate, registry.species.values())}
    matched = []
    for channel in _source_channels(registry, PATEAU):
        reaction = registry_reaction_candidate(channel, registry.species)
        assert reaction is not None
        if reaction.family != "neutral" or sum(x.n for x in reaction.products) != 1:
            continue
        matched.append(reaction)
        assert reaction.process == "association"
        assert reaction.stabilization == "unspecified"
        assert assess_consistency(reaction, CandidateSet(states=states)).verdict == "pass"
    assert matched


@pytest.mark.parametrize(
    ("reactant", "record_id", "rate"),
    [("SO", "R130", 1.4e-13), ("SF2", "R135", 1e-10)],
)
def test_oxygen_state_footnote_retains_both_explicit_source_model_channels(
    registry: Registry, reactant: str, record_id: str, rate: float
) -> None:
    # Pateau author proof Table VII, p. 7: footnote a means O(3P) or O(1D).
    # It establishes the source model rule, not measured state-resolved rates.
    for oxygen in ("O", "O_1D"):
        channel = next(
            item
            for item in registry.channels[("neutral_neutral", reactant, oxygen)]
            if item.source.get("record_id") == record_id
        )
        assert channel.type == "association"
        dataset = channel.datasets[0]
        assert dataset.params["source_value"] == pytest.approx(rate, rel=1e-12, abs=0)
        assert dataset.params["value"] == pytest.approx(rate * 1e-6, rel=1e-12, abs=0)
        assert dataset.reaction_order == 2
        assert "footnote a" in dataset.source["source_table"]


def test_tabulated_constants_keep_unknown_applicability_after_user_conditions(
    registry: Registry,
) -> None:
    # Tables III and VII check numerical transcription and source-model order.
    # Their reactor simulation inputs do not supply elementary-rate validity.
    examined = []
    for channel in _source_channels(registry, PATEAU):
        reaction = registry_reaction_candidate(channel, registry.species)
        assert reaction is not None
        for dataset in channel.datasets:
            if dataset.source.get("source_id") != PATEAU:
                continue
            examined.append(dataset)
            assert dataset.reaction_order == 2
            assert dataset.observable == "reaction_rate"
            assert dataset.validity is None
            assert dataset.params["value"] == pytest.approx(
                dataset.params["source_value"] * 1e-6, rel=1e-12, abs=0
            )
            assert normalized_dataset(dataset_payload(dataset)) == dataset
            for conditions in (Conditions(), Conditions(gas_temperature_K=700)):
                value = data_use(
                    reaction, ReactionEvidence(overlay_datasets=(dataset,)), conditions
                )
                assert value.status == "needs_input"
                assert value.required_inputs == ("dataset_applicability_conditions",)
                assert "not specified" in dataset.source["applicability_review"]
    assert examined


def test_reviewed_son_heavy_particle_constants_are_only_the_declared_model_point(
    registry: Registry,
) -> None:
    # Son p. 242 explicitly assigns R21-R60 to 700 K. The matching Table 1
    # expressions and constants were checked separately before adding scope.
    channels = _source_channels(registry, SON)
    assert channels
    for channel in channels:
        reaction = registry_reaction_candidate(channel, registry.species)
        assert reaction is not None
        for dataset in channel.datasets:
            if dataset.source.get("source_id") != SON:
                continue
            assert dataset.reaction_order == 2
            assert dataset.validity is not None
            assert dataset.validity.minimum == dataset.validity.maximum == 700
            evidence = ReactionEvidence(overlay_datasets=(dataset,))
            scoped = data_use(reaction, evidence, Conditions(gas_temperature_K=700))
            assert scoped.status == "coefficient"
            assert scoped.unit == "m3/s"
            assert scoped.value == pytest.approx(
                dataset.params["source_value"] * 1e-6, rel=1e-12, abs=0
            )
            assert data_use(reaction, evidence, Conditions()).required_inputs == (
                "gas_temperature",
            )
            assert (
                data_use(reaction, evidence, Conditions(gas_temperature_K=300)).status
                == "unavailable"
            )
            assert normalized_dataset(dataset_payload(dataset)) == dataset


def test_one_reactant_source_table_entry_does_not_infer_a_first_order_coefficient(
    registry: Registry,
) -> None:
    # Pateau Table VII uses a shared cm3/s header for R138's one-reactant
    # equation. Reading a number does not resolve that dimensional ambiguity.
    channel = next(
        item for item in _source_channels(registry, PATEAU) if item.source["record_id"] == "R138"
    )
    reaction = registry_reaction_candidate(channel, registry.species)
    assert reaction is not None
    assert sum(x.n for x in reaction.reactants) == 1
    assert not channel.datasets
    assert data_use(reaction, ReactionEvidence(), Conditions()).status == "unavailable"


@pytest.mark.parametrize(
    ("target", "a_cm3_s", "activation_K", "low_K", "high_K", "k298_cm3_s"),
    [
        ("N2", 2.15e-11, -110.0, 100.0, 675.0, 3.1e-11),
        ("CO2", 7.5e-11, -115.0, 200.0, 354.0, 1.1e-10),
    ],
)
def test_evaluated_quenching_rates_use_source_term_scope_and_explicit_temperature(
    registry: Registry,
    target: str,
    a_cm3_s: float,
    activation_K: float,
    low_K: float,
    high_K: float,
    k298_cm3_s: float,
) -> None:
    # JPL Evaluation 20, Table 1A and full Notes A7 / A12: rates for the
    # O(3P) term, not individual J branches. A7 explicitly recommends
    # 100--675 K; A12 adoption is restricted to its explicit fit-data window.
    channel = registry.channels[("neutral_neutral", "O_1D", target)][0]
    reaction = registry_reaction_candidate(channel, registry.species)
    assert reaction is not None
    states = {state.id: state for state in map(registry_state_candidate, registry.species.values())}
    assert assess_consistency(reaction, CandidateSet(states=states)).verdict == "unknown"
    catalog = EvidenceCatalog.load(registry.root)
    assert assess_reaction_evidence(reaction, catalog.reaction(reaction)).verdict == "pass"
    dataset = channel.datasets[0]
    assert dataset.provenance.provider == "NASA_JPL"
    assert dataset.provenance.collection == "evaluated_gas_kinetics"
    assert dataset.provenance.release == "25-1"
    assert dataset.method == "evaluated"
    assert normalized_dataset(dataset_payload(dataset)) == dataset
    evidence = ReactionEvidence(overlay_datasets=(dataset,))
    selection = DataSelection.from_document(
        {"quantities": {"rate_coefficient": {"mode": "only", "providers": ["NASA_JPL"]}}}
    )
    for temperature in (low_K, 298.0, high_K):
        value = data_use(reaction, evidence, Conditions(gas_temperature_K=temperature), selection)
        assert value.status == "coefficient"
        assert value.unit == "m3/s"
        assert value.value == pytest.approx(
            a_cm3_s * 1e-6 * exp(-activation_K / temperature), rel=1e-12, abs=0
        )
        if temperature == 298:
            assert value.value == pytest.approx(k298_cm3_s * 1e-6, rel=0.01, abs=0)
    for temperature in (low_K - 1, high_K + 1):
        value = data_use(reaction, evidence, Conditions(gas_temperature_K=temperature), selection)
        assert value.status == "unavailable"
        assert value.datasets[0].status == "out_of_range"
    missing = data_use(reaction, evidence, Conditions(electron_temperature_eV=1), selection)
    assert missing.status == "needs_input"
    assert missing.required_inputs == ("gas_temperature",)
    assert (
        states[registry_state_candidate(registry.species["O_3P"]).id].state.resolution == "lumped"
    )


def test_term_summed_source_does_not_supply_an_individual_fine_structure_rate(
    registry: Registry,
) -> None:
    level = registry_state_candidate(registry.species["O"])
    term = registry_state_candidate(registry.species["O_3P"])
    assert level.key != term.key
    assert term.state.resolution == "lumped"
    assert term.state.label == "3p"
    assert registry.species["O_3P"].state.energy_eV is None
    assert registry.species["O_3P"].thermo is None
    assert not registry.species["O_3P"].properties
    for channel in registry.channels[("neutral_neutral", "O_1D", "O2")]:
        reaction = registry_reaction_candidate(channel, registry.species)
        assert reaction is not None
        result = data_use(
            reaction,
            ReactionEvidence(overlay_datasets=tuple(channel.datasets)),
            Conditions(gas_temperature_K=298),
        )
        if any(product.species == level.id for product in reaction.products):
            assert result.status == "unavailable"
            assert result.value is None
            assert result.datasets[0].reason == "total data do not determine this product channel"
        else:
            assert any(product.species == term.id for product in reaction.products)
            assert result.status == "coefficient"
