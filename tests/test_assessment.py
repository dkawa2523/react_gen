"""General proposition boundaries and order-independent numerical use."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from reactgen.assessment import (
    assess_consistency,
    assess_kinetics,
    assess_reaction_evidence,
    assess_state,
    assess_thermochemistry,
    evaluate,
)
from reactgen.case import Case, Conditions, Limits, RequestedReaction
from reactgen.chemistry import candidate_state, electron_state
from reactgen.evidence import EvidenceCatalog, ReactionEvidence, StateEvidence
from reactgen.generate import candidates
from reactgen.model import CandidateSet, ReactionCandidate, Term, reaction_id
from reactgen.pipeline import analyze
from reactgen.records import (
    NumericDataset,
    Property,
    ReactionRecord,
    StateRecord,
    Uncertainty,
    normalized_dataset,
)
from reactgen.units import EV_PER_K, JOULE_PER_EV


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


def test_mapped_cid_requires_the_declared_collider_to_remain_unchanged() -> None:
    atom = candidate_state({"O": 1}, 0)
    excited = candidate_state({"O": 1}, 0, "electronic")
    molecule = candidate_state({"O": 2}, 0)
    states = CandidateSet(states={state.id: state for state in (atom, excited, molecule)})
    reaction = _reaction(
        "collision_induced_dissociation",
        (Term(excited.id), Term(molecule.id)),
        (Term(excited.id), Term(atom.id, 2)),
        "neutral",
        transformation={
            "kind": "collision_partition",
            "parent": molecule.id,
            "collider": excited.id,
            "fragments": [excited.id, atom.id],
            "collider_product": atom.id,
        },
    )
    # The equation permits a CID interpretation but the declared map changes
    # the collider. That map belongs to the level-transfer interpretation.
    assert assess_consistency(replace(reaction, transformation={}), states).verdict == "pass"
    assert assess_consistency(reaction, states).verdict == "fail"
    changed = replace(reaction, process="dissociation_with_level_transfer")
    assert assess_consistency(changed, states).verdict == "pass"


@pytest.mark.parametrize(
    ("charge", "structure", "process", "wrong"),
    [
        (-1, "smiles:[F-]", "collisional_detachment", "collision_ionization"),
        (0, "smiles:[F]", "collision_ionization", "collisional_detachment"),
    ],
)
def test_heavy_electron_release_checks_charge_and_inventory(
    charge: int, structure: str, process: str, wrong: str
) -> None:
    parent = candidate_state({"F": 1}, charge, structure=structure)
    product = candidate_state({"F": 1}, charge + 1)
    collider = candidate_state({"Ar": 1}, 1)
    electron = electron_state()
    states = CandidateSet(states={s.id: s for s in (parent, product, collider, electron)})
    reaction = _reaction(
        process,
        (Term(parent.id), Term(collider.id)),
        (Term(product.id), Term(collider.id), Term(electron.id)),
        "ion",
    )
    assert assess_consistency(reaction, states).verdict == "pass"
    assert assess_consistency(replace(reaction, process=wrong), states).verdict == "fail"


@pytest.mark.parametrize(
    ("supplies", "equation", "generated_process", "requested_process"),
    [
        ("e", "e + F2 -> e + F+ + F-", "ion_pair_formation", "dissociation"),
        ("F2-", "F2- + Ar -> 2 F + Ar + e", "dissociative_detachment", "collisional_detachment"),
    ],
)
def test_distinct_fragment_exit_classes_share_equation_accounting(
    supplies, equation, generated_process, requested_process
) -> None:
    hypothesis = RequestedReaction(equation, requested_process)
    result = analyze(
        Case(
            "fragment class",
            ("Ar", "F2"),
            supplies=(supplies,),
            limits=Limits(max_depth=1),
            reactions=(hypothesis,),
        ),
        EvidenceCatalog(),
    )
    claims = {
        reaction.process: result.evaluation.reaction_assessments[reaction.id]
        for reaction in result.candidates.reactions.values()
        if reaction.equation_key == hypothesis.candidate.equation_key
    }
    assert claims[generated_process]["consistency"].verdict == "pass"
    assert claims[requested_process]["consistency"].verdict == "fail"
    assert all(assessments["conservation"].verdict == "pass" for assessments in claims.values())


def test_explicit_atomic_structure_preserves_electron_charge_change_candidates() -> None:
    result = analyze(
        Case(
            "charge change",
            ("F",),
            supplies=("e",),
            structures={"F": "[F]"},
            limits=Limits(max_depth=1),
        ),
        EvidenceCatalog(),
    )
    processes = {
        reaction.process: result.evaluation.reaction_assessments[reaction.id]
        for reaction in result.candidates.reactions.values()
        if reaction.family == "electron" and reaction.process in {"ionization", "attachment"}
    }
    assert set(processes) == {"ionization", "attachment"}
    assert all(row["consistency"].verdict == "pass" for row in processes.values())
    assert all(row["energy"].verdict == "unknown" for row in processes.values())


def test_charge_change_compares_nuclear_connectivity_across_electronic_structures() -> None:
    pytest.importorskip("rdkit.Chem")
    composition = {"C": 2, "H": 6, "O": 1}
    parent = candidate_state(composition, 0, structure="smiles:CCO")
    ion = candidate_state(composition, 1, structure="smiles:CC[OH+]")
    isomer = candidate_state(composition, 1, structure="smiles:C[O+]C")
    states = CandidateSet(states={s.id: s for s in (parent, ion, isomer, electron_state())})
    reaction = _reaction("ionization", (Term("e"), Term(parent.id)), (Term("e", 2), Term(ion.id)))
    assert assess_consistency(reaction, states).verdict == "pass"
    changed = replace(reaction, products=(Term("e", 2), Term(isomer.id)))
    assert assess_consistency(changed, states).verdict == "fail"


def test_charge_exchange_preserves_formula_candidates_from_explicit_structures() -> None:
    case = Case(
        "charge exchange",
        ("Ne",),
        supplies=("Ar+",),
        structures={"Ar+": "[Ar+]", "Ne": "[Ne]"},
        limits=Limits(max_depth=1, max_reactions=60),
    )
    result = analyze(case, EvidenceCatalog())
    reaction = next(
        reaction
        for reaction in result.candidates.reactions.values()
        if reaction.process == "charge_exchange"
        and {term.species for term in reaction.products} == {"Ar@ground", "Ne+@ground"}
    )
    assert all(result.candidates.states[term.species].structure for term in reaction.reactants)
    assert result.evaluation.reaction_assessments[reaction.id]["consistency"].verdict == "pass"


def test_charge_exchange_checks_isotope_identity_per_partner() -> None:
    start_a = candidate_state({"C": 1}, 1, structure="smiles:[13C+]")
    start_b = candidate_state({"C": 1}, 0, structure="smiles:[12C]")
    wrong_a = candidate_state({"C": 1}, 0, "electronic", structure="smiles:[12C]")
    wrong_b = candidate_state({"C": 1}, 1, "electronic", structure="smiles:[13C+]")
    final_a = candidate_state({"C": 1}, 0, structure="smiles:[13C]")
    final_b = candidate_state({"C": 1}, 1, structure="smiles:[12C+]")
    states = CandidateSet(
        states={s.id: s for s in (start_a, start_b, wrong_a, wrong_b, final_a, final_b)}
    )
    for products, expected in (((wrong_a, wrong_b), "fail"), ((final_a, final_b), "pass")):
        reaction = _reaction(
            "charge_exchange",
            (Term(start_a.id), Term(start_b.id)),
            tuple(Term(state.id) for state in products),
            "ion",
            transformation={
                "kind": "charge_transfer",
                "partners": [start_a.id, start_b.id],
                "partner_products": [state.id for state in products],
                "charge_change": -1,
            },
        )
        assert assess_consistency(reaction, states).verdict == expected


def test_unbalanced_explicit_electron_relation_cannot_supply_a_state_gap() -> None:
    ground = candidate_state({"Ar": 1}, 0)
    upper = candidate_state({"Ar": 1}, 0, "resolved", label="upper", resolution="resolved")
    reaction = _reaction(
        "excitation",
        (Term("e"), Term(ground.id)),
        (Term("e"), Term(upper.id)),
    )
    record = ReactionRecord(
        "balanced",
        reaction.equation_key,
        "electron",
        "excitation",
        (ground, upper),
        channel_scope="energy_relation",
        energy_properties={
            "delta_e_eV": Property(2, "eV", tier="reviewed", definition="products_minus_reactants")
        },
    )
    malformed = replace(
        record,
        id="missing-outgoing-electron",
        equation_key=replace(reaction, products=(Term(upper.id),)).equation_key,
        energy_properties={
            "delta_e_eV": Property(3, "eV", tier="reviewed", definition="products_minus_reactants")
        },
    )
    states = {state.id: state for state in (ground, upper, electron_state())}
    generated = CandidateSet(states, {reaction.id: reaction})
    result = evaluate(
        generated, EvidenceCatalog(reaction_records=(record, malformed)), Conditions()
    )
    difference = result.thermochemical_calculations[reaction.id]["state_energy_difference_eV"]
    assert difference.value == 2
    assert [term["record_id"] for term in difference.inputs] == [record.id]


def test_only_a_pure_energy_relation_can_omit_the_zero_reference_electron() -> None:
    neutral, ion = (candidate_state({"Ar": 1}, charge) for charge in (0, 1))
    reaction = _reaction("ionization", (Term("e"), Term(neutral.id)), (Term("e", 2), Term(ion.id)))
    relation = ReactionRecord(
        "reference",
        replace(reaction, reactants=(Term(neutral.id),), products=(Term(ion.id),)).equation_key,
        "electron",
        "ionization",
        (neutral, ion),
        channel_scope="energy_relation",
        energy_properties={
            "delta_e_eV": Property(2, "eV", tier="reviewed", definition="products_minus_reactants")
        },
    )
    generated = CandidateSet(
        {state.id: state for state in (neutral, ion, electron_state())}, {reaction.id: reaction}
    )
    for record, expected in (
        (relation, 2),
        (replace(relation, channel_scope="product_resolved"), None),
    ):
        evaluation = evaluate(generated, EvidenceCatalog(reaction_records=(record,)), Conditions())
        difference = evaluation.thermochemical_calculations[reaction.id][
            "state_energy_difference_eV"
        ]
        assert difference.value == expected


def test_element_imbalance_cannot_cancel_between_source_relations() -> None:
    hydrogen, chlorine, bromine, fluorine = (
        candidate_state({symbol: 1}, 0) for symbol in ("H", "Cl", "Br", "F")
    )
    hcl, hbr = (candidate_state({"H": 1, halogen: 1}, 0) for halogen in ("Cl", "Br"))
    transfer = _reaction(
        "net_group_transfer",
        (Term(hcl.id), Term(bromine.id)),
        (Term(hbr.id), Term(chlorine.id)),
        "neutral",
    )
    states = (hydrogen, chlorine, bromine, fluorine, hcl, hbr)
    generated = CandidateSet({state.id: state for state in states}, {transfer.id: transfer})
    for fragment, expected in ((fluorine, None), (hydrogen, -2)):
        records = []
        for parent, halogen, value in ((hcl, chlorine, 3), (hbr, bromine, 5)):
            cut = _reaction(
                "dissociation", (Term(parent.id),), (Term(halogen.id), Term(fragment.id)), "neutral"
            )
            records.append(
                ReactionRecord(
                    cut.id,
                    cut.equation_key,
                    "neutral",
                    "dissociation",
                    (parent, halogen, fragment),
                    channel_scope="energy_relation",
                    energy_properties={
                        "delta_e_eV": Property(
                            value, "eV", tier="reviewed", definition="products_minus_reactants"
                        )
                    },
                )
            )
        evaluation = evaluate(
            generated,
            EvidenceCatalog(reaction_records=tuple(records)),
            Conditions(collision_energy_eV=0, collision_energy_frame="com"),
        )
        difference = evaluation.thermochemical_calculations[transfer.id][
            "state_energy_difference_eV"
        ]
        assert difference.value == expected
        assert evaluation.reaction_assessments[transfer.id]["energy"].verdict == (
            "unknown" if expected is None else "pass"
        )


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


def test_reviewed_mass_does_not_establish_anion_existence() -> None:
    anion = candidate_state({"C": 1, "F": 4}, -1)
    record = StateRecord(
        anion.id, anion, properties={"mass_amu": Property(88, "amu", tier="reviewed")}
    )
    catalog = EvidenceCatalog(state_records=(record,))
    result = evaluate(CandidateSet({anion.id: anion}), catalog, Conditions())
    assert result.state_evidence[anion.id].match == "exact"
    assert result.state_assessments[anion.id]["state"].verdict == "unknown"


def test_self_collision_quenching_preserves_classification() -> None:
    ground, metastable = (candidate_state({"Ar": 1}, 0, kind) for kind in ("ground", "metastable"))
    states = CandidateSet({state.id: state for state in (ground, metastable)})
    reaction = _reaction(
        "quenching",
        (Term(metastable.id, 2),),
        (Term(ground.id), Term(metastable.id)),
        "neutral",
    )
    assert assess_consistency(reaction, states).verdict == "pass"


def test_surface_charge_reservoir_is_explicit_in_the_conclusion() -> None:
    ground, ion = (candidate_state({"Ar": 1}, charge) for charge in (0, 1))
    states = CandidateSet({state.id: state for state in (ground, ion)})
    reaction = _reaction(
        "surface_neutralization",
        (Term(ion.id),),
        (Term(ground.id),),
        "surface",
        surface="wall",
    )
    result = assess_consistency(reaction, states)
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


@pytest.mark.parametrize(
    ("equation", "process", "verdict"),
    [
        ("SiH3+ + SiH- -> SiH3 + SiH", "mutual_neutralization", "pass"),
        ("SiH3+ + SiH- -> 2 SiH2", "mutual_neutralization", "fail"),
        ("O2+ + O- -> 3 O", "mutual_neutralization", "fail"),
        ("O2+ + O- -> 3 O", "dissociative_charge_transfer", "pass"),
        ("NF2 + HCl -> NFCl + HF", "net_group_exchange", "pass"),
        ("H + NF2 -> HF + NF", "net_group_exchange", "fail"),
        ("0.5 Ar + 1.5 He -> 0.5 Ar + 1.5 He", "elastic", "fail"),
    ],
)
def test_named_binary_process_requires_its_participant_pattern(equation, process, verdict):
    requested = RequestedReaction(equation, process)
    states = CandidateSet({state.id: state for state in requested.states})
    assert assess_consistency(requested.candidate, states).verdict == verdict


@pytest.mark.parametrize("process", ["radical_recombination", "substitution", "net_group_transfer"])
def test_group_role_map_cannot_approve_an_unrelated_or_empty_transformation(process):
    requested = RequestedReaction("Ar@1s5 + He -> Ar + He", process)
    states = CandidateSet({state.id: state for state in requested.states})
    mapped = replace(
        requested.candidate,
        transformation={
            "kind": "group_transfer",
            "donor": "Ar@1s5",
            "acceptor": "He@ground",
            "donor_product": "Ar@ground",
            "acceptor_product": "He@ground",
            "group_charge": 0,
        },
    )
    assert assess_consistency(mapped, states).verdict == "fail"


@pytest.mark.parametrize(
    ("fluoro_silicon", "chloro_silicon", "verdict"),
    [("28", "29", "pass"), ("29", "28", "fail"), ("", "29", "unknown")],
)
def test_group_transfer_preserves_the_retained_nuclides(fluoro_silicon, chloro_silicon, verdict):
    requested = RequestedReaction(
        "SiH3F@ground;structure=smiles:[28SiH3]F + SiHCl@ground;structure=smiles:[29SiH]Cl"
        f" -> SiH2F@ground;structure=smiles:[{fluoro_silicon}SiH2]F"
        f" + SiH2Cl@ground;structure=smiles:[{chloro_silicon}SiH2]Cl",
        "net_group_transfer",
    )
    states = CandidateSet({state.id: state for state in requested.states})
    assert assess_consistency(requested.candidate, states).verdict == verdict


@pytest.mark.parametrize(
    ("first_silicon", "second_silicon", "verdict"),
    [("28", "29", "pass"), ("29", "28", "fail"), ("", "29", "unknown")],
)
def test_group_exchange_preserves_nuclides_outside_the_declared_groups(
    first_silicon, second_silicon, verdict
):
    requested = RequestedReaction(
        "SiH3F@ground;structure=smiles:[28SiH3]F + SiH2Cl2@ground;structure=smiles:[29SiH2](Cl)Cl"
        f" -> SiH3Cl@ground;structure=smiles:[{first_silicon}SiH3]Cl"
        f" + SiH2ClF@ground;structure=smiles:[{second_silicon}SiH2](Cl)F",
        "net_group_exchange",
    )
    states = CandidateSet({state.id: state for state in requested.states})
    left, right = (states.states[term.species] for term in requested.candidate.reactants)
    first, second = sorted(
        (states.states[term.species] for term in requested.candidate.products),
        key=lambda state: state.composition["H"],
    )
    # The two-H parent loses Cl and the three-H parent loses F.
    partners = sorted((left, right), key=lambda state: state.composition["H"])
    role_map = {
        "kind": "group_exchange",
        "partners": [state.id for state in partners],
        "groups": [{"Cl": 1}, {"F": 1}],
    }
    for declared in (role_map, role_map | {"partner_products": [first.id, second.id]}):
        reaction = replace(requested.candidate, transformation=declared)
        assert assess_consistency(reaction, states).verdict == verdict
