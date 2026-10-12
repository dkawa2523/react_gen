"""General proposition boundaries and order-independent numerical use."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from reactgen.assessment import (
    assess_consistency,
    assess_kinetics,
    assess_reaction_evidence,
    assess_state,
    assess_thermochemistry,
    evaluate,
)
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog, ReactionEvidence, StateEvidence
from reactgen.generate import candidates
from reactgen.model import CandidateSet, ReactionCandidate, Term, reaction_id
from reactgen.records import (
    NumericDataset,
    Property,
    ReactionRecord,
    StateRecord,
    Uncertainty,
    normalized_dataset,
)
from reactgen.units import EV_PER_K, JOULE_PER_EV

FIXTURE = Path(__file__).parent / "fixtures" / "mini"


def _reaction(
    process: str = "elastic",
    left: tuple[Term, ...] = (Term("e"), Term("Ar@ground")),
    right: tuple[Term, ...] = (Term("e"), Term("Ar@ground")),
    family: str = "electron",
    **kwargs: object,
) -> ReactionCandidate:
    reaction = ReactionCandidate(
        "", left, right, family, process, "mechanical", "test", 1, **kwargs
    )
    return replace(reaction, id=reaction_id(reaction.key))


def _rate(value: float = 1e-15, **changes: object) -> NumericDataset:
    data = {
        "id": "rate",
        "kind": "rate_coefficient",
        "form": "constant",
        "unit": "m3/s",
        "independent_variable": "gas_temperature",
        "observable": "reaction_rate",
        "parameters": {"value": value},
        "validity": {
            "quantity": "gas_temperature",
            "minimum": 300.0,
            "maximum": 1000.0,
            "unit": "K",
        },
        "status": "reviewed",
    }
    data.update(changes)
    return normalized_dataset(data)


def _use(*datasets: NumericDataset, conditions: Conditions | None = None):
    return assess_kinetics(
        _reaction(),
        ReactionEvidence(overlay_datasets=datasets),
        conditions if conditions is not None else Conditions(gas_temperature_K=300),
    )


def _state_evidence(state, **changes: object) -> StateEvidence:
    record = StateRecord(
        state.id,
        state,
        existence="confirmed",
        existence_source="test identity",
        tier="reviewed",
        status="reviewed",
        **changes,
    )
    return StateEvidence("exact", (record,))


def _energy_record(reaction: ReactionCandidate, threshold: float) -> ReactionEvidence:
    record = ReactionRecord(
        "source",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (),
        energy_properties={"threshold_eV": Property(threshold, "eV", tier="reviewed")},
        status="reviewed",
        tier="reviewed",
    )
    return ReactionEvidence((record,))


def test_state_identity_stays_exact_when_existence_assertions_conflict() -> None:
    generated = candidates(("Ar", "O2"))
    exact = EvidenceCatalog.load(FIXTURE)
    assert exact.state(generated.states["Ar@ground"]).match == "exact"
    assert exact.state(generated.states["O2@ground"]).match == "none"
    argon = replace(
        next(record for record in exact.state_records if record.id == "Ar"),
        existence="confirmed",
        existence_source="test identity",
    )
    catalog = replace(
        exact,
        state_records=(argon, replace(argon, id="duplicate", existence="unbound")),
    )
    state = generated.states["Ar@ground"]
    evidence = catalog.state(state)
    assert evidence.match == "exact"
    existence = assess_state(state, evidence, generated)
    assert existence.verdict == "unknown"
    assert "existence assertions conflict" in existence.message


def test_reviewed_mass_does_not_establish_anion_existence(tmp_path: Path) -> None:
    path = tmp_path / "overlay.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "properties": {
                    "CF4-@ground": {"mass_amu": {"value": 88, "evidence_tier": "reviewed"}}
                }
            }
        ),
        encoding="utf-8",
    )
    generated = candidates(("CF4",))
    result = evaluate(generated, EvidenceCatalog.load(None, overlay=path), Conditions())
    assert result.state_assessments["CF4-@ground"]["state"].verdict == "unknown"


@pytest.mark.parametrize(
    "process", ["ionization", "attachment", "dissociation", "penning_ionization"]
)
def test_process_label_cannot_turn_an_elastic_equation_into_a_valid_channel(process: str) -> None:
    generated = candidates(("Ar",))
    assert assess_consistency(_reaction(process), generated).verdict == "fail"


def test_mechanical_equations_match_their_process_patterns() -> None:
    generated = candidates(("Ar", "O2"))
    failed = [
        (reaction.process, str(reaction.reactants), str(reaction.products))
        for reaction in generated.reactions.values()
        if assess_consistency(reaction, generated).verdict == "fail"
    ]
    assert failed == []


def test_self_collision_quenching_preserves_classification() -> None:
    generated = candidates(("Ar",))
    reaction = _reaction(
        "quenching",
        (Term("Ar@metastable", 2),),
        (Term("Ar@ground"), Term("Ar@metastable")),
        "neutral",
    )
    assert assess_consistency(reaction, generated).verdict == "pass"


def test_surface_charge_reservoir_is_explicit_in_the_conclusion() -> None:
    generated = candidates(("Ar",))
    reaction = _reaction(
        "surface_neutralization",
        (Term("Ar+@ground"),),
        (Term("Ar@ground"),),
        "surface",
        surface="wall",
    )
    result = assess_consistency(reaction, generated)
    assert result.verdict == "pass"
    assert "surface charge reservoir:wall" in result.basis
    assert "charge conservation" not in result.basis


def test_state_existence_does_not_depend_on_unrelated_resolved_candidates() -> None:
    generated = candidates(("Ar",))
    state = generated.states["Ar@metastable"]
    evidence = _state_evidence(state)
    before = assess_state(state, evidence, generated)
    four_p = candidate_state(
        {"Ar": 1}, charge=0, kind="resolved", label="4p", resolution="resolved"
    )
    changed = replace(generated, states=generated.states | {four_p.id: four_p})
    assert before.verdict == "pass"
    assert assess_state(state, evidence, changed) == before


@pytest.mark.parametrize(
    ("unit", "value", "expected"),
    [
        ("eV", 0.5, "pass"),
        ("J", 0.5 * JOULE_PER_EV, "pass"),
        ("unknown", 0.5, "unknown"),
        ("eV", 0.0, "unknown"),
        ("eV", -0.5, "fail"),
    ],
)
def test_affinity_inference_uses_declared_units_and_strictly_positive_binding(
    unit: str, value: float, expected: str
) -> None:
    generated = candidates(("Ar",))
    state = generated.states["Ar-@ground"]
    parent = generated.states["Ar@ground"]
    prop = Property(value, unit, tier="reviewed")
    all_evidence = {parent.id: _state_evidence(parent, properties={"electron_affinity_eV": prop})}
    assert (
        assess_state(state, StateEvidence("none", ()), generated, all_evidence).verdict == expected
    )


def test_conflicting_state_properties_are_not_selected_by_input_order() -> None:
    generated = candidates(("Ar",))
    state, parent = generated.states["Ar-@ground"], generated.states["Ar@ground"]
    records = tuple(
        _state_evidence(
            parent, properties={"electron_affinity_eV": Property(value, "eV", tier="reviewed")}
        ).records[0]
        for value in (0.5, 1.0)
    )
    for ordering in (records, tuple(reversed(records))):
        evidence = {parent.id: StateEvidence("exact", ordering)}
        assert (
            assess_state(state, StateEvidence("none", ()), generated, evidence).verdict == "unknown"
        )


def test_ground_ionization_threshold_is_checked_against_the_ie_lower_bound() -> None:
    generated = candidates(("Ar",))
    reaction = _reaction("ionization", right=(Term("e", 2), Term("Ar+@ground")))
    parent = generated.states["Ar@ground"]
    states = {
        parent.id: _state_evidence(
            parent,
            properties={
                "ionization_energy_eV": Property(15.0 * JOULE_PER_EV, "J", tier="reviewed")
            },
        )
    }
    result, values = assess_thermochemistry(
        reaction, generated, states, _energy_record(reaction, 1.0), Conditions()
    )
    assert result.verdict == "fail"
    assert values["ionization_energy_eV"] == pytest.approx(15.0)


def test_parent_affinity_does_not_reject_dissociative_attachment() -> None:
    generated = candidates(("CF4",))
    parent = generated.states["CF4@ground"]
    states = {
        parent.id: _state_evidence(
            parent, properties={"electron_affinity_eV": Property(-1.0, "eV", tier="reviewed")}
        )
    }
    reaction = next(
        item
        for item in generated.reactions.values()
        if item.process == "dissociative_attachment"
        and any(term.species == parent.id for term in item.reactants)
    )
    result, _ = assess_thermochemistry(
        reaction, generated, states, _energy_record(reaction, 4.7), Conditions()
    )
    assert result.verdict == "unknown"
    assert "unbound parent" not in result.message


@pytest.mark.parametrize(
    ("tier", "resolution"),
    [("imported", "resolved"), ("reviewed", "lumped"), ("reviewed", "resolved")],
)
def test_penning_deficit_is_not_an_unconditional_prohibition(tier: str, resolution: str) -> None:
    excited = candidate_state({"Ar": 1}, 0, kind="electronic", label="level", resolution=resolution)
    target = candidate_state({"O": 2}, 0)
    ion = candidate_state({"O": 2}, charge=1)
    ground = candidate_state({"Ar": 1}, 0)
    generated = CandidateSet({state.id: state for state in (excited, target, ion, ground)}, {})
    reaction = _reaction(
        "penning_ionization",
        (Term(excited.id), Term(target.id)),
        (Term(ground.id), Term(ion.id), Term("e")),
        "neutral",
    )
    record = StateRecord(excited.id, excited, energy_eV=10.0, tier=tier)
    states = {
        excited.id: StateEvidence("exact", (record,)),
        target.id: _state_evidence(
            target, properties={"ionization_energy_eV": Property(12.0, "eV", tier="reviewed")}
        ),
    }
    result, _ = assess_thermochemistry(
        reaction, generated, states, ReactionEvidence(), Conditions()
    )
    assert result.verdict == "unknown"


def test_elastic_zero_energy_does_not_claim_an_energy_loss_model() -> None:
    generated = candidates(("Ar",))
    result = evaluate(generated, EvidenceCatalog.load(None), Conditions())
    reaction = next(item for item in generated.reactions.values() if item.process == "elastic")
    assert result.reaction_assessments[reaction.id]["thermochemistry"].verdict == "pass"
    assert (
        "translational energy transfer is undetermined"
        in result.reaction_assessments[reaction.id]["thermochemistry"].message
    )
    assert not hasattr(result, "thermo_capabilities")


def test_same_dataset_id_with_different_content_is_order_independent_conflict() -> None:
    correct = _rate()
    incorrect = replace(correct, unit="s-1")
    for datasets in ((correct, incorrect), (incorrect, correct)):
        assessed, use = _use(*datasets)
        assert assessed.verdict == "unknown"
        assert use.status == "conflict"
        assert use.dataset_id is None


def test_same_dataset_content_is_deduplicated() -> None:
    result, use = _use(_rate(), _rate())
    assert result.verdict == "pass"
    assert len(use.datasets) == 1
    assert use.value == pytest.approx(1e-15)


def test_invalid_higher_quality_source_does_not_hide_valid_data() -> None:
    valid = _rate(id="valid")
    invalid = replace(_rate(id="invalid"), tier="curated", unit="s-1")
    result, use = _use(invalid, valid)
    assert result.verdict == "pass"
    assert use.dataset_id == "valid"
    assert {item.status for item in use.datasets} == {"invalid", "valid"}


@pytest.mark.parametrize("values", [(0.0, 1.0), (1.0, 100.0)])
def test_overlapping_constant_values_including_zero_cannot_be_arbitrarily_selected(
    values: tuple[float, float],
) -> None:
    first = _rate(values[0], id="first")
    second = _rate(
        values[1],
        id="second",
        validity={"quantity": "gas_temperature", "minimum": 200.0, "maximum": 400.0, "unit": "K"},
    )
    result, use = _use(first, second)
    assert result.verdict == "unknown"
    assert use.status == "conflict"


def test_rate_units_are_normalized_before_value_comparison() -> None:
    first = _rate(1e-15, id="SI")
    second = _rate(1e-9, id="cm", unit="cm3/s")
    result, use = _use(first, second)
    assert result.verdict == "pass"
    assert use.value == pytest.approx(1e-15)
    assert use.unit == "m3/s"


def test_undeclared_constant_applicability_does_not_produce_a_ready_coefficient() -> None:
    result, use = _use(_rate(validity=None, independent_variable=None))
    assert result.verdict == "unknown"
    assert use.status == "needs_input"
    assert "dataset_applicability_conditions" in use.required_inputs


def test_temperature_quantity_and_temperature_unit_are_separate() -> None:
    raw = _rate(
        independent_variable="electron_temperature",
        validity={
            "quantity": "electron_temperature",
            "minimum": 300.0,
            "maximum": 300.0,
            "unit": "K",
        },
    )
    result, _ = _use(raw, conditions=Conditions(gas_temperature_K=300, electron_temperature_eV=3))
    assert result.verdict == "fail"
    result, use = _use(raw, conditions=Conditions(electron_temperature_eV=300 * EV_PER_K))
    assert result.verdict == "pass"
    assert use.status == "coefficient"


def test_sticking_is_a_bounded_probability_requiring_flux_conversion() -> None:
    reaction = _reaction(
        "surface_recombination",
        (Term("Ar@ground"),),
        (Term("Ar@ground"),),
        "surface",
        surface="wall",
    )
    data = replace(
        _rate(1.5), kind="sticking_coefficient", observable="sticking_probability", unit="1"
    )
    result, use = assess_kinetics(
        reaction, ReactionEvidence(overlay_datasets=(data,)), Conditions(gas_temperature_K=300)
    )
    assert result.verdict == "fail"
    assert use.status == "unavailable"
    result, use = assess_kinetics(
        reaction,
        ReactionEvidence(overlay_datasets=(replace(data, params={"value": 0.5}),)),
        Conditions(gas_temperature_K=300),
    )
    assert result.verdict == "unknown"
    assert use.value == 0.5
    assert use.unit == "1"
    assert "surface_incident_flux_model" in use.required_inputs
    assert "surface_flux_conversion" in use.required_transforms


def test_cross_section_needs_distribution_and_integration_even_when_te_is_given(
    tmp_path: Path,
) -> None:
    path = tmp_path / "curve.csv"
    path.write_text("energy,cross_section\n1,1e-20\n10,2e-20\n", encoding="utf-8")
    data = normalized_dataset(
        {
            "id": "curve",
            "kind": "cross_section",
            "form": "table",
            "unit": "m2",
            "observable": "elastic",
            "independent_variable": "electron_energy",
            "validity": {"quantity": "electron_energy", "minimum": 1, "maximum": 10, "unit": "eV"},
            "asset": path.name,
            "status": "reviewed",
        },
        base=tmp_path,
    )
    result, use = _use(data, conditions=Conditions(electron_temperature_eV=3))
    assert result.verdict == "unknown"
    assert use.status == "needs_input"
    assert use.required_inputs == ("electron_energy_distribution",)
    assert use.required_transforms == ("eedf_integration",)


def test_arrhenius_declared_convention_is_evaluated() -> None:
    data = replace(
        _rate(),
        form="arrhenius",
        params={"A": 2e-15, "b": 1.0, "Ea": 0.0},
        reference_temperature_K=300,
        parameter_units={"Ea": "eV"},
    )
    result, use = _use(data, conditions=Conditions(gas_temperature_K=600))
    assert result.verdict == "pass"
    assert use.value == pytest.approx(4e-15)
    missing_convention, missing = _use(replace(data, parameter_units={}))
    assert missing_convention.verdict == "fail"
    assert missing.datasets[0].status == "invalid"


def test_total_process_reference_does_not_attest_a_product_channel() -> None:
    reaction = _reaction()
    record = replace(_energy_record(reaction, 0).records[0], channel_scope="total")
    assert assess_reaction_evidence(reaction, ReactionEvidence((record,))).verdict == "unknown"


def test_zero_measurement_absolute_uncertainty_is_converted_with_its_unit() -> None:
    first = replace(_rate(0.0, id="zero", unit="cm3/s"), uncertainty=Uncertainty(absolute=2e-9))
    second = _rate(1e-15, id="positive")
    result, use = _use(first, second)
    assert result.verdict == "pass"
    assert use.status == "coefficient"


def test_affinity_uncertainty_crossing_zero_cannot_decide_binding() -> None:
    generated = candidates(("Ar",))
    state, parent = generated.states["Ar-@ground"], generated.states["Ar@ground"]
    affinity = Property(0.5, "eV", tier="reviewed", uncertainty=Uncertainty(absolute=1.0))
    evidence = {parent.id: _state_evidence(parent, properties={"electron_affinity_eV": affinity})}
    assert assess_state(state, StateEvidence("none", ()), generated, evidence).verdict == "unknown"


@pytest.mark.parametrize(
    "uncertainty",
    [
        Uncertainty(factor=-1),
        Uncertainty(factor=0),
        Uncertainty(factor=0.5),
        Uncertainty(factor=float("nan")),
        Uncertainty(factor=float("inf")),
        Uncertainty(relative=-0.1),
        Uncertainty(relative=float("nan")),
        Uncertainty(relative=float("inf")),
        Uncertainty(absolute=-0.1),
        Uncertainty(absolute=float("nan")),
        Uncertainty(absolute=float("inf")),
        Uncertainty(absolute=0, factor=-1),
    ],
)
def test_invalid_uncertainty_cannot_change_binding_or_support_a_rate(
    uncertainty: Uncertainty,
) -> None:
    generated = candidates(("Ar",))
    state, parent = generated.states["Ar-@ground"], generated.states["Ar@ground"]
    affinity = Property(0.5, "eV", tier="reviewed", uncertainty=uncertainty)
    evidence = {parent.id: _state_evidence(parent, properties={"electron_affinity_eV": affinity})}
    assert assess_state(state, StateEvidence("none", ()), generated, evidence).verdict == "unknown"
    result, use = _use(replace(_rate(), uncertainty=uncertainty))
    assert result.verdict == "fail"
    assert use.datasets[0].status == "invalid"
    assert "uncertainty" in use.datasets[0].reason


def test_uncertainty_limits_are_ordered_for_signed_values_and_include_zero_width() -> None:
    assert Uncertainty(factor=2).bounds(-0.5) == (-1.0, -0.25)
    assert Uncertainty(relative=0.5).bounds(-0.5) == (-0.75, -0.25)
    assert Uncertainty(relative=2).bounds(-0.5) == (-1.5, 0.5)
    for uncertainty in (Uncertainty(factor=1), Uncertainty(relative=0), Uncertainty(absolute=0)):
        assert uncertainty.bounds(-0.5) == (-0.5, -0.5)
        assert _use(replace(_rate(), uncertainty=uncertainty))[0].verdict == "pass"


def test_overflowing_uncertainty_bounds_are_invalid_instead_of_resolving_conflict() -> None:
    result, use = _use(replace(_rate(1e308), uncertainty=Uncertainty(factor=2)))
    assert result.verdict == "fail"
    assert use.datasets[0].status == "invalid"
    assert "uncertainty bounds" in use.datasets[0].reason


def test_missing_temperature_does_not_use_overflowing_uncertainty_samples() -> None:
    data = replace(
        _rate(),
        form="arrhenius",
        params={"A": 1e307, "b": 1.0, "Ea": 0.0},
        reference_temperature_K=300,
        parameter_units={"Ea": "eV"},
        uncertainty=Uncertainty(factor=10),
    )
    result, use = _use(data, replace(data, id="other"), conditions=Conditions())
    assert result.verdict == "unknown"
    assert use.status == "needs_input"
    assert use.value is None


def test_table_and_arrhenius_values_are_compared_at_the_supplied_condition(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    path.write_text("T,k\n300,3e-15\n1000,3e-15\n", encoding="utf-8")
    table = replace(
        _rate(id="table"),
        form="table",
        asset=normalized_dataset({"asset": path.name}, base=tmp_path).asset,
    )
    arrhenius = replace(
        _rate(id="arrhenius"),
        form="arrhenius",
        params={"A": 1e-15, "b": 0.0, "Ea": 0.0},
        reference_temperature_K=300,
        parameter_units={"Ea": "eV"},
    )
    result, use = _use(table, arrhenius)
    assert result.verdict == "unknown"
    assert use.status == "conflict"


def test_explicit_empirical_reaction_order_controls_coefficient_dimensions() -> None:
    result, use = _use(replace(_rate(), reaction_order=1.5, unit="m1.5/s"))
    assert result.verdict == "pass"
    assert use.unit == "m1.5/s"


def test_table_numeric_errors_are_not_silently_skipped(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("T,k\n300,1e-15\n400,bad\n1000,2e-15\n", encoding="utf-8")
    dataset = replace(
        _rate(), form="table", asset=normalized_dataset({"asset": path.name}, base=tmp_path).asset
    )
    result, use = _use(dataset)
    assert result.verdict == "fail"
    assert use.datasets[0].status == "invalid"


@pytest.mark.parametrize(
    ("quantity", "conditions"),
    [
        ("ion_temperature", Conditions(ion_temperature_K=600)),
        ("surface_temperature", Conditions(surface_temperature_K=600)),
    ],
)
def test_supported_temperature_inputs_resolve_their_own_numeric_quantity(
    quantity: str, conditions: Conditions
) -> None:
    dataset = _rate(
        independent_variable=quantity,
        validity={"quantity": quantity, "minimum": 300, "maximum": 1000, "unit": "K"},
    )
    result, use = _use(dataset, conditions=conditions)
    assert result.verdict == "pass"
    assert use.status == "coefficient"
    unresolved, missing = _use(dataset, conditions=Conditions(gas_temperature_K=600))
    assert unresolved.verdict == "unknown"
    assert quantity in missing.required_inputs


def test_unspecified_temperature_is_source_repair_not_an_input_request() -> None:
    result, use = _use(
        _rate(
            independent_variable="arbitrary_temperature",
            validity={
                "quantity": "arbitrary_temperature",
                "minimum": 300,
                "maximum": 1000,
                "unit": "K",
            },
        )
    )
    assert result.verdict == "fail"
    assert use.datasets[0].status == "invalid"
    assert "unspecified or unsupported" in use.datasets[0].reason


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_threshold_is_rejected_at_the_quantity_boundary(value: float) -> None:
    reaction = _reaction("ionization", right=(Term("e", 2), Term("Ar+@ground")))
    with pytest.raises(ValueError, match="threshold_eV must be finite"):
        _energy_record(reaction, value)


def test_multivalent_step_ionization_is_a_valid_attested_process() -> None:
    first = candidate_state({"Ar": 1}, 1)
    second = candidate_state({"Ar": 1}, 2)
    electron = candidates(("Ar",)).states["e"]
    reaction = _reaction("ionization", (Term("e"), Term(first.id)), (Term("e", 2), Term(second.id)))
    generated = CandidateSet({state.id: state for state in (first, second, electron)}, {})
    assert assess_consistency(reaction, generated).verdict == "pass"


def test_state_excitation_is_not_charge_exchange() -> None:
    ion = candidate_state({"Ar": 1}, 1)
    excited_ion = candidate_state({"Ar": 1}, 1, "electronic")
    target = candidate_state({"O": 2}, 0)
    reaction = _reaction(
        "charge_exchange",
        (Term(ion.id), Term(target.id)),
        (Term(excited_ion.id), Term(target.id)),
        "ion",
    )
    generated = CandidateSet({state.id: state for state in (ion, excited_ion, target)}, {})
    assert assess_consistency(reaction, generated).verdict == "fail"
