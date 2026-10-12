"""Named scientific claims use only the quantities and conditions they consume.

Synthetic energies exercise logical boundaries. Observable definitions follow
NIST's gas-phase ion thermochemistry: https://webbook.nist.gov/chemistry/ion/ .
"""

from dataclasses import replace

import pytest

from reactgen.assessment import (
    assess_reaction_evidence,
    assess_thermochemistry,
    evaluate,
)
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state, electron_state
from reactgen.evidence import EvidenceCatalog, ReactionEvidence, StateEvidence
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.records import FormationReference, Property, ReactionRecord, StateRecord, Uncertainty
from reactgen.units import JOULE_PER_EV


def _ionization(
    properties: tuple[Property, ...],
    threshold: Property,
    *,
    molecular: bool = False,
    channel_tier: str = "imported",
    extra_threshold: Property | None = None,
    record_status: str = "imported",
    product_changes: dict | None = None,
):
    parent, ion = (
        candidate_state({"N": 2} if molecular else {"Ar": 1}, charge) for charge in (0, 1)
    )
    if product_changes:
        ion = candidate_state(ion.composition, ion.charge, **product_changes)
    electron = electron_state()
    candidates = CandidateSet(states={state.id: state for state in (parent, ion, electron)})
    reaction = ReactionCandidate(
        "ionization",
        (Term(parent.id), Term(electron.id)),
        (Term(ion.id), Term(electron.id, 2)),
        "electron",
        "ionization",
        "test",
        "test",
        0,
    )
    states = {
        parent.id: StateEvidence(
            "exact",
            tuple(
                StateRecord(
                    str(index),
                    parent,
                    status=record_status,
                    properties={"ionization_energy_eV": prop},
                )
                for index, prop in enumerate(properties)
            ),
        ),
    }
    record = ReactionRecord(
        "channel",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (),
        energy_properties={"threshold_eV": threshold},
        tier=channel_tier,
    )
    records = (
        (record,)
        if extra_threshold is None
        else (
            record,
            replace(record, energy_properties={"threshold_eV": extra_threshold}),
        )
    )
    evidence = ReactionEvidence(records)
    result, values = assess_thermochemistry(reaction, candidates, states, evidence, Conditions())
    return result, values, assess_reaction_evidence(reaction, evidence)


@pytest.mark.parametrize("definition", [None, "vertical"])
def test_unspecified_or_vertical_molecular_ie_does_not_supply_the_adiabatic_lower_bound(
    definition: str | None,
) -> None:
    result, values, _ = _ionization(
        (Property(10, "eV", tier="reviewed", definition=definition),),
        Property(11, "eV", tier="reviewed", definition="channel_threshold"),
        molecular=True,
    )
    assert result.verdict == "unknown"
    assert "ionization_energy_eV" not in values
    assert values["threshold_eV"] == 11
    assert any(item.quantity == "ionization_energy_eV.definition" for item in result.requirements)
    assert all(item.responsibility != "user_inputs" for item in result.requirements)


def test_vertical_ie_is_an_independent_observable_and_not_an_adiabatic_conflict() -> None:
    adiabatic = Property(10, "eV", source="adiabatic", tier="reviewed", definition="adiabatic")
    vertical = replace(adiabatic, value=14, source="vertical", definition="vertical")
    threshold = Property(11, "eV", tier="reviewed", definition="channel_threshold")
    baseline = _ionization((adiabatic,), threshold, molecular=True)
    assert baseline[0].verdict == "pass"
    assert _ionization((adiabatic, vertical), threshold, molecular=True) == baseline
    assert _ionization((vertical, adiabatic), threshold, molecular=True) == baseline


@pytest.mark.parametrize(("unit", "scale"), [("eV", 1), ("J", JOULE_PER_EV)])
@pytest.mark.parametrize(
    ("center", "error", "verdict"), [(11, 2, "unknown"), (10.5, 0.1, "pass"), (9.5, 0.1, "fail")]
)
def test_ionization_compares_both_declared_uncertainty_ranges(
    unit: str,
    scale: float,
    center: float,
    error: float,
    verdict: str,
) -> None:
    result, _, _ = _ionization(
        (Property(10, "eV", tier="reviewed", uncertainty=Uncertainty(absolute=0.2)),),
        Property(
            center * scale,
            unit,
            tier="reviewed",
            definition="channel_threshold",
            uncertainty=Uncertainty(absolute=error * scale),
        ),
    )
    assert result.verdict == verdict
    assert "both declared uncertainty ranges" in result.scope
    assert "occurrence" in result.scope
    assert "threshold declaration range" in result.message


def test_channel_review_and_energy_review_cannot_promote_each_other() -> None:
    ie = Property(10, "eV", tier="reviewed")
    threshold = Property(11, "eV", tier="reviewed", definition="channel_threshold")
    result, _, channel = _ionization((ie,), threshold)
    assert result.verdict == "pass"
    assert channel.verdict == "unknown"
    assert "Nominal" in result.scope
    result, values, channel = _ionization(
        (ie,), replace(threshold, tier="imported"), channel_tier="reviewed"
    )
    assert result.verdict == "unknown"
    assert "threshold_eV" not in values
    assert channel.verdict == "pass"
    assert any(
        item.responsibility == "source_review" and item.quantity == "threshold_eV"
        for item in result.requirements
    )


def test_an_appearance_quantity_does_not_conflict_with_the_actual_channel_threshold() -> None:
    threshold = Property(11, "eV", tier="reviewed", definition="channel_threshold")
    ie = (Property(10, "eV", tier="reviewed"),)
    baseline = _ionization(ie, threshold)
    assert (
        _ionization(
            ie,
            threshold,
            extra_threshold=replace(threshold, value=9, definition="appearance_energy"),
        )
        == baseline
    )


def test_participant_aggregate_references_distinct_existence_and_binding_claims() -> None:
    neutral, anion = (candidate_state({"F": 1}, charge) for charge in (0, -1))
    electron = electron_state()
    reaction = ReactionCandidate(
        "attachment",
        (Term(electron.id), Term(neutral.id)),
        (Term(anion.id),),
        "electron",
        "attachment",
        "test",
        "test",
        0,
    )
    candidates = CandidateSet(
        states={state.id: state for state in (neutral, anion, electron)},
        reactions={reaction.id: reaction},
    )
    record = StateRecord(
        "neutral",
        neutral,
        existence="confirmed",
        existence_source="observed identity",
        tier="reviewed",
        properties={"electron_affinity_eV": Property(1, "eV", tier="reviewed")},
    )
    result = evaluate(candidates, EvidenceCatalog(state_records=(record,)), Conditions())
    assert result.state_assessments[neutral.id]["state"].proposition == "state_existence_support"
    assert (
        result.state_assessments[anion.id]["state"].proposition == "ground_anion_electron_binding"
    )
    aggregate = result.reaction_assessments[reaction.id]["state"]
    assert aggregate.proposition == "participant_state_support"
    assert aggregate.verdict == "pass"
    assert set(aggregate.dependencies) == {(neutral.id, "state"), (anion.id, "state")}
    assert aggregate.requirements == ()
    binding = result.reaction_assessments[reaction.id]["thermochemistry"]
    assert binding.verdict == "pass"
    assert "stabilization" in binding.scope
    assert all(
        assessment.proposition and assessment.scope
        for findings in (*result.state_assessments.values(), *result.reaction_assessments.values())
        for assessment in findings.values()
    )


def test_calculable_delta_h_does_not_supply_an_unimplemented_occurrence_judgment() -> None:
    molecule, atom = candidate_state({"H": 2}, 0), candidate_state({"H": 1}, 0)
    reaction = ReactionCandidate(
        "split",
        (Term(molecule.id),),
        (Term(atom.id, 2),),
        "neutral",
        "dissociation",
        "test",
        "test",
        0,
    )
    states = {
        state.id: StateEvidence(
            "exact",
            (
                StateRecord(
                    state.id,
                    state,
                    properties={
                        "enthalpy_formation_eV": Property(
                            value,
                            "eV",
                            tier="reviewed",
                            formation_reference=FormationReference(0, "standard_elements", 100000),
                        ),
                    },
                ),
            ),
        )
        for state, value in ((molecule, 0), (atom, 1))
    }
    result, values = assess_thermochemistry(
        reaction,
        CandidateSet(states={state.id: state for state in (molecule, atom)}),
        states,
        ReactionEvidence(),
        Conditions(),
    )
    assert values["delta_h_eV"] == 2
    assert result.verdict == "unknown"
    assert result.proposition == "reaction_energy_relation"
    assert {item.responsibility for item in result.requirements} == {"external_models"}
    assert "No implemented energy relation" in result.scope
    assert "no implemented energy relation for process 'dissociation'" in result.message
    assert "available calculated or declared values are retained independently" in result.message
    assert "evidence or required conditions are missing" not in result.message


@pytest.mark.parametrize(
    ("source_center", "uncertainty", "verdict"),
    [(-2.5, 0.4, "pass"), (-2, 0.4, "fail"), (-2.9999, None, "pass")],
)
def test_charge_transfer_compares_declared_defect_ranges_without_a_fixed_energy_tolerance(
    source_center: float,
    uncertainty: float | None,
    verdict: str,
) -> None:
    donor, ion, target, product = (
        candidate_state({"Ar": 1}, 0),
        candidate_state({"Ar": 1}, 1),
        candidate_state({"He": 1}, 0),
        candidate_state({"He": 1}, 1),
    )
    reaction = ReactionCandidate(
        "transfer",
        (Term(ion.id), Term(target.id)),
        (Term(donor.id), Term(product.id)),
        "ion",
        "charge_exchange",
        "test",
        "test",
        0,
    )
    states = {
        state.id: StateEvidence(
            "exact",
            (
                StateRecord(
                    state.id,
                    state,
                    properties={
                        "ionization_energy_eV": Property(
                            value, "eV", tier="reviewed", uncertainty=Uncertainty(absolute=error)
                        ),
                    },
                ),
            ),
        )
        for state, value, error in ((donor, 10, 0.3), (target, 7, 0.2))
    }
    defect = Property(
        source_center,
        "eV",
        tier="reviewed",
        definition="products_minus_reactants",
        uncertainty=None if uncertainty is None else Uncertainty(absolute=uncertainty),
    )
    record = ReactionRecord(
        "defect",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (),
        energy_properties={"delta_e_eV": defect},
    )
    result, _ = assess_thermochemistry(
        reaction,
        CandidateSet(states={state.id: state for state in (donor, ion, target, product)}),
        states,
        ReactionEvidence((record,)),
        Conditions(),
    )
    assert result.verdict == verdict
    assert "overlap does not establish equal true values" in result.scope
    if uncertainty is None:
        assert "nominal" in result.scope


@pytest.mark.parametrize(
    ("value", "unit", "record_status", "field", "responsibility"),
    [
        (None, "eV", "imported", "value", "source_information"),
        (10, "unsupported unit", "imported", "unit", "source_information"),
        (10, "eV", "rejected", "record_status", "source_review"),
    ],
)
def test_energy_missing_work_identifies_the_actual_unusable_field(
    value: float | None,
    unit: str,
    record_status: str,
    field: str,
    responsibility: str,
) -> None:
    result, _, _ = _ionization(
        (Property(value, unit, tier="reviewed"),),
        Property(11, "eV", tier="reviewed", definition="channel_threshold"),
        record_status=record_status,
    )
    assert result.verdict == "unknown"
    assert {(item.responsibility, item.quantity) for item in result.requirements} == {
        (responsibility, f"ionization_energy_eV.{field}"),
    }


@pytest.mark.parametrize(
    ("threshold", "field"),
    [
        (Property(None, "eV", tier="reviewed", definition="channel_threshold"), "value"),
        (Property(11, "unsupported unit", tier="reviewed", definition="channel_threshold"), "unit"),
        (
            Property(
                11, "eV", tier="reviewed", definition="channel_threshold", qualifier="upper limit"
            ),
            "qualifier",
        ),
    ],
)
def test_channel_energy_work_does_not_request_an_already_known_definition(
    threshold: Property,
    field: str,
) -> None:
    result, _, _ = _ionization((Property(10, "eV", tier="reviewed"),), threshold)
    assert result.verdict == "unknown"
    assert any(item.quantity == f"threshold_eV.{field}" for item in result.requirements)
    assert all(item.quantity != "threshold_eV.definition" for item in result.requirements)
    if field == "value":
        assert "supply a numerical value" in result.message
    if field == "unit":
        assert "state a supported energy unit" in result.message


@pytest.mark.parametrize("changes", [{"phase": "solid"}, {"structure": "different structure"}])
def test_parent_ie_does_not_supply_an_ionization_bound_for_another_phase_or_structure(
    changes: dict,
) -> None:
    result, values, _ = _ionization(
        (Property(10, "eV", tier="reviewed"),),
        Property(11, "eV", tier="reviewed", definition="channel_threshold"),
        product_changes=changes,
    )
    assert result.verdict == "unknown"
    assert "ionization_energy_eV" not in values
    assert {item.responsibility for item in result.requirements} == {"external_models"}


def test_ground_parent_ie_is_only_a_lower_bound_for_the_corresponding_excited_ion() -> None:
    result, values, _ = _ionization(
        (Property(10, "eV", tier="reviewed"),),
        Property(11, "eV", tier="reviewed", definition="channel_threshold"),
        product_changes={"kind": "electronic", "label": "resolved level", "resolution": "resolved"},
    )
    assert result.verdict == "pass"
    assert result.proposition == "ionization_threshold_lower_bound"
    assert values == {"ionization_energy_eV": 10, "threshold_eV": 11}


def test_solid_affinity_requires_a_phase_model_instead_of_a_repeated_definition() -> None:
    parent, anion = (candidate_state({"O": 2}, charge, phase="solid") for charge in (0, -1))
    electron = electron_state()
    reaction = ReactionCandidate(
        "attach",
        (Term(electron.id), Term(parent.id)),
        (Term(anion.id),),
        "electron",
        "attachment",
        "test",
        "test",
        0,
    )
    candidates = CandidateSet(states={state.id: state for state in (parent, anion, electron)})
    states = {
        parent.id: StateEvidence(
            "exact",
            (
                StateRecord(
                    "solid",
                    parent,
                    properties={
                        "electron_affinity_eV": Property(
                            1, "eV", tier="reviewed", definition="adiabatic"
                        )
                    },
                ),
            ),
        )
    }
    result, _ = assess_thermochemistry(
        reaction, candidates, states, ReactionEvidence(), Conditions()
    )
    assert result.verdict == "unknown"
    assert {(item.responsibility, item.quantity) for item in result.requirements} == {
        ("external_models", "electron_affinity_eV.model")
    }


def test_same_source_energy_in_another_unit_retains_its_common_scientific_meaning() -> None:
    threshold = Property(
        11,
        "eV",
        tier="reviewed",
        definition="channel_threshold",
        uncertainty=Uncertainty(absolute=0.1),
    )
    alternate = replace(
        threshold,
        value=11 * JOULE_PER_EV,
        unit="J",
        uncertainty=Uncertainty(absolute=0.1 * JOULE_PER_EV),
    )
    ie = (Property(10, "eV", tier="reviewed", uncertainty=Uncertainty(absolute=0.2)),)
    first = _ionization(ie, threshold, extra_threshold=alternate)
    second = _ionization(ie, alternate, extra_threshold=threshold)
    assert first == second
    assert first[0].verdict == "pass"
    assert threshold.value == 11
    assert alternate.unit == "J"


def test_nearby_same_unit_source_values_are_not_rounded_into_one_declaration() -> None:
    threshold = Property(11, "eV", tier="reviewed", definition="channel_threshold")
    result, values, _ = _ionization(
        (Property(10, "eV", tier="reviewed"),),
        threshold,
        extra_threshold=replace(threshold, value=11 + 1e-13),
    )
    assert result.verdict == "unknown"
    assert "threshold_eV" not in values


@pytest.mark.parametrize("qualifier", ["upper limit", "lower limit", "approximate"])
def test_a_qualified_state_ie_is_not_a_nominal_lower_bound_point(qualifier: str) -> None:
    prop = Property(10, "eV", tier="reviewed", qualifier=qualifier)
    result, values, _ = _ionization(
        (prop,),
        Property(9, "eV", tier="reviewed", definition="channel_threshold"),
    )
    assert result.verdict == "unknown"
    assert "ionization_energy_eV" not in values
    assert {(item.responsibility, item.quantity) for item in result.requirements} == {
        ("source_review", "ionization_energy_eV.qualifier"),
    }
    assert prop.qualifier == qualifier
