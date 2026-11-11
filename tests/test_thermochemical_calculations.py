"""Calculation inputs remain separate from reaction-energy propositions.

The synthetic NASA7 polynomials assign twice the atomic H/RT and S/R to
the molecule. Thus F2 -> 2 F has zero standard Gibbs change and a known
number-density equilibrium dimension, independent of the chosen Hf values.
The standard concentration relation is described by Cantera:
https://www.cantera.org/stable/cxx/d7/dfa/classCantera_1_1IdealGasPhase.html .
"""

from dataclasses import replace

import pytest

from reactgen import export
from reactgen.assessment import assess_state_thermochemistry, evaluate
from reactgen.case import Case, Conditions
from reactgen.chemistry import candidate_state, electron_state
from reactgen.evidence import EvidenceCatalog, StateEvidence
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.pipeline import analyze
from reactgen.records import (
    FormationReference,
    Property,
    ReactionRecord,
    StateRecord,
    Thermo,
    normalized_dataset,
)
from reactgen.thermo import AVOGADRO, GAS_CONSTANT, formation_delta, net_stoichiometry


def inputs():
    atom, molecule = (candidate_state({"F": count}, 0) for count in (1, 2))
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
    reference = FormationReference(298.15, "standard_elements", 100000)
    records = tuple(
        StateRecord(
            state.id,
            state,
            properties={
                "enthalpy_formation_eV": Property(
                    value,
                    "eV",
                    tier="reviewed",
                    formation_reference=reference,
                )
            },
            thermo=nasa
            if state == atom
            else replace(
                nasa,
                low=tuple(2 * coefficient for coefficient in nasa.low),
                high=tuple(2 * coefficient for coefficient in nasa.high),
            ),
        )
        for state, value in ((atom, 1.0), (molecule, 3.0))
    )
    reaction = ReactionCandidate(
        "thermal",
        (Term(molecule.id),),
        (Term(atom.id, 2),),
        "neutral",
        "dissociation",
        "test",
        "test",
        0,
    )
    return reaction, records


def result(reaction, records, temperature=300):
    states = {record.candidate.id: record.candidate for record in records}
    if any(term.species == "e" for term in (*reaction.reactants, *reaction.products)):
        states["e"] = electron_state()
    evaluation = evaluate(
        CandidateSet(states=states, reactions={reaction.id: reaction}),
        EvidenceCatalog(state_records=records),
        Conditions(gas_temperature_K=temperature),
    )
    return (
        evaluation.thermochemical_calculations[reaction.id],
        evaluation.thermochemistry.get(reaction.id, {}),
        evaluation.reaction_assessments[reaction.id]["thermochemistry"],
    )


def test_three_calculations_project_the_same_values_and_keep_reaction_claim_separate():
    reaction, records = inputs()
    calculations, flat, energy = result(reaction, records)
    thermal = {
        name: calculations[name]
        for name in ("delta_h_eV", "delta_g_eV", "equilibrium_constant_number_density")
    }
    assert all(calculation.status == "computed" for calculation in thermal.values())
    # Finite-temperature H/G are independent results, not zero-K state differences.
    assert calculations["state_energy_difference_eV"].status == "unavailable"
    for name, calculation in thermal.items():
        assert flat[name] == calculation.value
        assert all(flat[key] == value for key, value in calculation.conditions.items())
        assert calculation.requirements == ()
    assert calculations["delta_h_eV"].value == -1.0
    assert calculations["delta_h_eV"].conditions["delta_h_reference_temperature_K"] == 298.15
    assert calculations["delta_g_eV"].value == pytest.approx(0, abs=1e-12)
    constant = calculations["equilibrium_constant_number_density"]
    assert constant.value == pytest.approx(100000 / (GAS_CONSTANT * 300) * AVOGADRO)
    assert constant.unit == "m-3"
    assert energy.verdict == "not_applicable"
    assert not energy.requirements


def test_nonconserved_equation_cannot_supply_reaction_quantities_after_save(tmp_path):
    _, records = inputs()
    case = Case.from_document(
        {
            "gases": ["F2"],
            "conditions": {"gas_temperature_K": 300},
            "limits": {"max_atoms": 2, "max_depth": 1},
            "reactions": [{"equation": "F2 -> F", "process": "dissociation"}],
        }
    )
    target = case.reactions[0].candidate.id
    source = normalized_dataset(
        {
            "id": "test-rate",
            "kind": "rate_coefficient",
            "form": "constant",
            "unit": "s-1",
            "status": "reviewed",
            "parameters": {"value": 1e5},
            "validity": {"quantity": "gas_temperature", "unit": "K", "minimum": 250},
        }
    )
    catalog = EvidenceCatalog(state_records=records, overlay_datasets={target: (source,)})
    export.write(tmp_path, analyze(case, catalog))
    saved = export.read(tmp_path, verify_views=True)
    reaction = next(item for item in saved["reactions"] if item["id"] == target)
    assert reaction["assessments"]["conservation"]["verdict"] == "fail"
    assert reaction["assessments"]["kinetics"]["verdict"] == "not_applicable"
    assert reaction["thermochemistry"] == {}
    assert {
        (calc["status"], calc["value"]) for calc in reaction["thermochemical_calculations"].values()
    } == {("not_applicable", None)}
    assert reaction["data_use"]["status"] == "not_applicable"
    assert reaction["data_use"]["value"] is None
    assert reaction["data_use"]["datasets"][0]["value"] == 1e5


def test_legacy_flat_access_is_a_read_view_of_the_calculation_values():
    reaction, records = inputs()
    evaluation = evaluate(
        CandidateSet(
            states={record.candidate.id: record.candidate for record in records},
            reactions={reaction.id: reaction},
        ),
        EvidenceCatalog(state_records=records),
        Conditions(gas_temperature_K=300),
    )
    view = evaluation.thermochemistry
    detached = view[reaction.id]
    detached["delta_h_eV"] = 999
    assert view[reaction.id]["delta_h_eV"] == -1
    assert evaluation.thermochemical_calculations[reaction.id]["delta_h_eV"].value == -1


@pytest.mark.parametrize("temperature", [None, 150, 7000])
def test_temperature_input_and_domain_limits_do_not_change_reference_formation_delta(temperature):
    reaction, records = inputs()
    calculations, flat, energy = result(reaction, records, temperature)
    assert calculations["delta_h_eV"].status == "computed"
    assert flat["delta_h_eV"] == -1.0
    expected = "needs_input" if temperature is None else "out_of_range"
    for quantity in ("delta_g_eV", "equilibrium_constant_number_density"):
        calculation = calculations[quantity]
        assert calculation.status == expected
        assert calculation.value is None
        assert quantity not in flat
        if temperature is None:
            assert all(item.responsibility == "user_inputs" for item in calculation.requirements)
            assert {item.quantity for item in calculation.requirements} == {"gas_temperature_K"}
        else:
            assert calculation.conditions["temperature_K"] == temperature
            assert all(
                item.responsibility == "source_information" for item in calculation.requirements
            )
            assert all("extrapolating" in item.reason for item in calculation.requirements)
    assert energy.verdict == "not_applicable"
    assert not energy.requirements
    assert "gas_temperature_K" not in energy.message


@pytest.mark.parametrize("qualifier", ["upper limit", "lower limit", "approximately", "unknown"])
def test_formation_qualifier_is_not_consumed_as_a_point_and_preserves_independent_nasa(qualifier):
    reaction, (atom, molecule) = inputs()
    original = atom.properties["enthalpy_formation_eV"]
    atom = replace(
        atom,
        properties={"enthalpy_formation_eV": replace(original, qualifier=qualifier)},
    )
    calculations, flat, energy = result(reaction, (atom, molecule))
    enthalpy = calculations["delta_h_eV"]
    assert enthalpy.status == "unavailable"
    assert any(item.quantity == "enthalpy_formation_eV.qualifier" for item in enthalpy.requirements)
    assert "delta_h_eV" not in flat
    assert calculations["delta_g_eV"].status == "computed"
    assert calculations["equilibrium_constant_number_density"].status == "computed"
    assert "enthalpy_formation_eV" not in energy.message
    assert formation_delta(reaction, {item.id: item for item in (atom, molecule)}) is None
    assert atom.properties["enthalpy_formation_eV"].qualifier == qualifier


def test_missing_reference_is_a_calculation_prerequisite_and_not_an_energy_model_prerequisite():
    reaction, (atom, molecule) = inputs()
    atom = replace(
        atom,
        properties={
            "enthalpy_formation_eV": replace(
                atom.properties["enthalpy_formation_eV"], formation_reference=None
            )
        },
    )
    calculations, flat, energy = result(reaction, (atom, molecule))
    enthalpy = calculations["delta_h_eV"]
    assert enthalpy.status == "unavailable"
    assert {(item.target, item.quantity) for item in enthalpy.requirements} == {
        (atom.id, "enthalpy_formation_eV.formation_reference")
    }
    assert "delta_h_eV" not in flat
    assert "delta_g_eV" in flat
    assert "formation reference" not in energy.message


@pytest.mark.parametrize("reverse_order", [False, True])
def test_same_state_spectator_does_not_require_its_enthalpy_or_nasa(reverse_order):
    reaction, records = inputs()
    baseline = result(reaction, records)
    spectator = candidate_state({"Ar": 1}, 0)
    reaction = replace(
        reaction,
        reactants=(*reaction.reactants, Term(spectator.id, 0.1), Term(spectator.id, 0.2)),
        products=(*reaction.products, Term(spectator.id, 0.3)),
    )
    records = (*records, StateRecord("spectator", spectator))
    if reverse_order:
        reaction = replace(
            reaction,
            reactants=tuple(reversed(reaction.reactants)),
            products=tuple(reversed(reaction.products)),
        )
        records = tuple(reversed(records))
    calculations, flat, _ = result(reaction, records)
    assert calculations == baseline[0]
    assert flat == baseline[1]
    assert spectator.id not in net_stoichiometry(reaction)
    assert spectator.id in {term.species for term in reaction.reactants}


def test_distinct_state_identity_is_not_cancelled_as_a_spectator():
    reaction, records = inputs()
    gas = candidate_state({"Ar": 1}, 0)
    solid = candidate_state({"Ar": 1}, 0, phase="solid")
    reaction = replace(
        reaction,
        reactants=(*reaction.reactants, Term(gas.id)),
        products=(*reaction.products, Term(solid.id)),
    )
    calculations, flat, _ = result(
        reaction,
        (*records, StateRecord("gas spectator", gas), StateRecord("solid product", solid)),
    )
    assert {gas.id, solid.id} <= net_stoichiometry(reaction).keys()
    assert calculations["delta_h_eV"].status == "unavailable"
    assert "delta_h_eV" not in flat
    assert any(
        item.responsibility == "external_models" and item.target == solid.id
        for item in calculations["delta_g_eV"].requirements
    )


def test_electron_spectator_remains_outside_the_nasa_channel_contract():
    reaction, records = inputs()
    reaction = replace(
        reaction,
        reactants=(Term("e"), *reaction.reactants),
        products=(Term("e"), *reaction.products),
        family="electron",
    )
    calculations, flat, _ = result(reaction, records)
    assert calculations["delta_h_eV"].status == "computed"
    assert "delta_g_eV" not in flat
    assert calculations["delta_g_eV"].status == "unavailable"
    assert not calculations["delta_g_eV"].requirements
    assert "exclude electron channels" in calculations["delta_g_eV"].reason


def test_nasa_qualification_and_temperature_input_are_not_the_same_missing_information():
    reaction, (atom, molecule) = inputs()
    atom = replace(atom, thermo=replace(atom.thermo, tier="imported"))
    calculations, flat, _ = result(reaction, (atom, molecule), None)
    assert calculations["delta_g_eV"].status == "unavailable"
    assert {item.responsibility for item in calculations["delta_g_eV"].requirements} == {
        "source_review"
    }
    assert flat["delta_h_eV"] == -1.0


def test_equilibrium_numerical_underflow_does_not_discard_a_finite_gibbs_value():
    reaction, (atom, molecule) = inputs()
    extreme = (3.5, 0, 0, 0, 0, 1e10, 0)
    atom = replace(atom, thermo=replace(atom.thermo, low=extreme, high=extreme))
    calculations, flat, _ = result(reaction, (atom, molecule))
    assert calculations["delta_g_eV"].status == "computed"
    assert flat["delta_g_eV"] > 0.0
    constant = calculations["equilibrium_constant_number_density"]
    assert constant.status == "unavailable"
    assert "numerical_range" in constant.requirements[0].quantity
    assert "equilibrium_constant_number_density" not in flat


def test_surface_reservoir_is_not_silently_omitted_from_reaction_thermochemistry():
    reaction, records = inputs()
    calculations, flat, _ = result(replace(reaction, family="surface", surface="wall"), records)
    assert all(calculation.status == "unavailable" for calculation in calculations.values())
    assert all(
        item.quantity == "surface_thermochemical_balance"
        for calculation in calculations.values()
        for item in calculation.requirements
    )
    assert flat == {}


@pytest.mark.parametrize("phase", ["solid", "unknown"])
def test_model_representation_does_not_borrow_a_different_target_phase(phase):
    _, (atom, _) = inputs()
    state = candidate_state({"F": 1}, 0, phase=phase)
    record = replace(atom, id=state.id, candidate=state, properties={})
    availability = assess_state_thermochemistry(state, StateEvidence("exact", (record,)))
    assert availability.verdict == "unknown"
    assert availability.requirements[0].responsibility == (
        "identity" if phase == "unknown" else "source_review"
    )
    assert availability.requirements[0].quantity == (
        "phase" if phase == "unknown" else "thermochemical_model.phase"
    )


def _identity_evaluation(state, temperature, *, electron=False, surface=None, evidence=None):
    collider = candidate_state({"He": 1}, 0)
    terms = (Term(state.id), Term(collider.id))
    states = {item.id: item for item in (state, collider)}
    if electron:
        terms = (*terms, Term("e"))
        states["e"] = electron_state()
    reaction = ReactionCandidate(
        "identity",
        terms,
        tuple(reversed(terms)),
        "surface" if surface else "electron" if electron else "neutral",
        "elastic",
        "test",
        "test",
        0,
        surface=surface,
    )
    return evaluate(
        CandidateSet(states=states, reactions={reaction.id: reaction}),
        evidence or EvidenceCatalog(),
        Conditions(gas_temperature_K=temperature),
    ), reaction


@pytest.mark.parametrize("temperature", [None, 150, 300, 7000])
def test_thermal_identity_does_not_require_or_consume_temperature_pressure_or_polynomials(
    temperature,
):
    state = candidate_state({"Ar": 1}, 0)
    evaluation, reaction = _identity_evaluation(state, temperature)
    calculations = evaluation.thermochemical_calculations[reaction.id]
    for quantity, value in (("delta_g_eV", 0.0), ("equilibrium_constant_number_density", 1.0)):
        result = calculations[quantity]
        assert result.status == "computed"
        assert result.value == value
        assert result.requirements == ()
        assert "temperature_K" not in result.conditions
        assert "standard_pressure_Pa" not in result.conditions
    assert calculations["delta_g_eV"].conditions == {}
    assert calculations["equilibrium_constant_number_density"].conditions == {
        "equilibrium_constant_density_power": 0.0
    }
    assert evaluation.thermochemistry[reaction.id] == {
        "delta_h_eV": 0.0,
        "delta_g_eV": 0.0,
        "equilibrium_constant_number_density": 1.0,
        "equilibrium_constant_density_power": 0.0,
        "state_energy_difference_eV": 0.0,
    }
    assert evaluation.state_assessments[state.id]["state"].verdict == "unknown"
    assert evaluation.state_assessments[state.id]["thermochemistry"].verdict == "unknown"
    claims = evaluation.reaction_assessments[reaction.id]
    assert claims["state"].verdict == "unknown"
    assert claims["thermochemistry"].verdict == "pass"
    assert claims["reaction_evidence"].verdict == claims["kinetics"].verdict == "unknown"


@pytest.mark.parametrize("temperature", [None, 300])
@pytest.mark.parametrize(
    "state_changes",
    [
        {"phase": "unknown"},
        {"phase": "solid"},
        {"kind": "electronic", "label": "4s", "resolution": "resolved"},
    ],
)
def test_thermal_identity_stays_inside_the_identified_gas_ground_scope(state_changes, temperature):
    state = candidate_state({"Ar": 1}, 0, **state_changes)
    evaluation, reaction = _identity_evaluation(state, temperature)
    calculations = evaluation.thermochemical_calculations[reaction.id]
    for quantity in ("delta_g_eV", "equilibrium_constant_number_density"):
        result = calculations[quantity]
        assert result.status == "unavailable"
        assert result.value is None
        assert quantity not in evaluation.thermochemistry[reaction.id]
        assert {item.responsibility for item in result.requirements} == (
            {"identity"} if state.phase == "unknown" else {"external_models"}
        )
        assert all(item.target == state.id for item in result.requirements)
    assert evaluation.reaction_assessments[reaction.id]["kinetics"].verdict == "unknown"


@pytest.mark.parametrize("temperature", [None, 300])
@pytest.mark.parametrize("excluded_channel", ["electron", "surface"])
def test_thermal_identity_does_not_bypass_electron_or_surface_model_exclusions(
    excluded_channel, temperature
):
    state = candidate_state({"Ar": 1}, 0)
    evaluation, reaction = _identity_evaluation(
        state,
        temperature,
        electron=excluded_channel == "electron",
        surface="wall" if excluded_channel == "surface" else None,
    )
    calculations = evaluation.thermochemical_calculations[reaction.id]
    for quantity in ("delta_g_eV", "equilibrium_constant_number_density"):
        result = calculations[quantity]
        assert result.status == "unavailable"
        assert result.value is None
        assert quantity not in evaluation.thermochemistry.get(reaction.id, {})
        if excluded_channel == "electron":
            assert not result.requirements
            assert "exclude electron channels" in result.reason
        else:
            assert {item.quantity for item in result.requirements} == {
                "surface_thermochemical_balance"
            }


def test_thermal_identity_does_not_resolve_a_conflicting_energy_declaration():
    state = candidate_state({"Ar": 1}, 0)
    _, reaction = _identity_evaluation(state, None)
    record = ReactionRecord(
        "inconsistent elastic threshold",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (),
        energy_properties={
            "threshold_eV": Property(1.0, "eV", tier="reviewed", definition="channel_threshold")
        },
    )
    evaluation, reaction = _identity_evaluation(
        state, None, evidence=EvidenceCatalog(reaction_records=(record,))
    )
    calculations = evaluation.thermochemical_calculations[reaction.id]
    assert calculations["delta_g_eV"].value == 0.0
    assert calculations["equilibrium_constant_number_density"].value == 1.0
    claims = evaluation.reaction_assessments[reaction.id]
    assert claims["thermochemistry"].verdict == "fail"
    assert claims["kinetics"].verdict == claims["state"].verdict == "unknown"
