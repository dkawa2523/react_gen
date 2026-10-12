"""Identity-dependent energy conclusions must ignore unrelated declarations.

The energies and structures below are synthetic boundary inputs, not measured
values. They test correspondence and evidence precedence without changing the
ionization, affinity, or charge-transfer formulas.
"""

from dataclasses import replace

import pytest

from reactgen.assessment import (
    assess_consistency,
    assess_kinetics,
    assess_reaction_evidence,
    assess_state,
    assess_state_thermochemistry,
    assess_thermochemistry,
    evaluate,
)
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state, electron_state
from reactgen.evidence import EvidenceCatalog, ReactionEvidence, StateEvidence
from reactgen.model import Assessment, CandidateSet, ReactionCandidate, StateCandidate, Term
from reactgen.records import NumericDataset, Property, ReactionRecord, StateRecord, Thermo, Validity
from reactgen.selection import DataSelection, QuantitySelection


def _energy_record(state: StateCandidate, value: float) -> StateRecord:
    return StateRecord(
        state.id,
        state,
        properties={
            name: Property(
                value, "eV", source=f"energy:{state.id}", tier="reviewed", definition="adiabatic"
            )
            for name in ("ionization_energy_eV", "electron_affinity_eV")
        },
    )


def _transfer(
    ion: StateCandidate,
    target: StateCandidate,
    donor_product: StateCandidate,
    acceptor_product: StateCandidate,
) -> ReactionCandidate:
    return ReactionCandidate(
        "transfer",
        (Term(ion.id), Term(target.id)),
        (Term(donor_product.id), Term(acceptor_product.id)),
        "ion",
        "charge_exchange",
        "test",
        "test",
        0,
    )


def _energy_result(
    reaction: ReactionCandidate,
    states: tuple[StateCandidate, ...],
    records: tuple[StateRecord, ...] = (),
) -> tuple[Assessment, dict[str, float]]:
    candidates = CandidateSet(states={state.id: state for state in states})
    catalog = EvidenceCatalog(state_records=records)
    evidence = {state.id: catalog.state(state) for state in states}
    return assess_thermochemistry(reaction, candidates, evidence, ReactionEvidence(), Conditions())


@pytest.mark.parametrize("charge", [-1, 1])
@pytest.mark.parametrize(
    "unrelated",
    [
        candidate_state({"Ar": 1}, 0, phase="solid"),
        candidate_state({"Ar": 1}, 0, structure="another structure"),
        candidate_state({"Ar": 1}, 0, "electronic"),
        candidate_state({"Ar": 1}, 2),
    ],
)
def test_charge_transfer_ignores_unrelated_ground_parent_candidates_in_either_order(
    charge: int, unrelated: StateCandidate
) -> None:
    donor = candidate_state({"Ar": 1}, 0)
    ion = candidate_state({"Ar": 1}, charge)
    target = candidate_state({"O": 2}, 0)
    product = candidate_state({"O": 2}, charge)
    states = (donor, ion, target, product)
    records = (_energy_record(donor, 15.0), _energy_record(target, 12.0))
    reaction = _transfer(ion, target, donor, product)
    baseline = _energy_result(reaction, states, records)
    assert baseline[1]["charge_transfer_energy_defect_eV"] == -3.0 * charge

    for ordered in ((unrelated, *states), (*reversed(states), unrelated)):
        actual = _energy_result(reaction, ordered, (*records, _energy_record(unrelated, 5.0)))
        assert actual == baseline


@pytest.mark.parametrize("phase_or_structure", [{"phase": "solid"}, {"structure": "other"}])
def test_only_an_unrelated_parent_record_cannot_supply_charge_transfer_energy(
    phase_or_structure: dict,
) -> None:
    donor = candidate_state({"Ar": 1}, 0)
    ion = candidate_state({"Ar": 1}, 1)
    target = candidate_state({"O": 2}, 0)
    product = candidate_state({"O": 2}, 1)
    unrelated = candidate_state({"Ar": 1}, 0, **phase_or_structure)
    states = (unrelated, donor, ion, target, product)
    records = (_energy_record(unrelated, 5.0), _energy_record(target, 12.0))
    reaction = _transfer(ion, target, donor, product)
    for ordered in (states, tuple(reversed(states))):
        judgment, values = _energy_result(reaction, ordered, records)
        assert judgment.verdict == "unknown"
        assert "charge_transfer_energy_defect_eV" not in values


def test_multiple_corresponding_ground_representations_remain_unresolved() -> None:
    donor = candidate_state({"Ar": 1}, 0)
    alternative = candidate_state({"Ar": 1}, 0, label="another ground representation")
    ion = candidate_state({"Ar": 1}, 1)
    target = candidate_state({"O": 2}, 0)
    product = candidate_state({"O": 2}, 1)
    reaction = _transfer(ion, target, donor, product)
    states = (donor, alternative, ion, target, product)
    records = tuple(_energy_record(state, 12.0) for state in (donor, alternative, target))
    for ordered in (states, tuple(reversed(states))):
        judgment, values = _energy_result(reaction, ordered, records)
        assert judgment.verdict == "unknown"
        assert "charge_transfer_energy_defect_eV" not in values


def test_same_composition_in_different_structures_is_not_resonant_identity() -> None:
    donor = candidate_state({"C": 1, "H": 2}, 0, structure="structure A")
    ion = candidate_state(donor.composition, 1, structure=donor.structure)
    target = candidate_state(donor.composition, 0, structure="structure B")
    product = candidate_state(target.composition, 1, structure=target.structure)
    reaction = _transfer(ion, target, donor, product)
    records = (_energy_record(donor, 15.0), _energy_record(target, 12.0))
    candidates = CandidateSet(states={s.id: s for s in (donor, ion, target, product)})
    assert assess_consistency(reaction, candidates).verdict == "pass"
    result = _energy_result(reaction, (donor, ion, target, product), records)
    assert result[1]["charge_transfer_energy_defect_eV"] == -3.0


def test_charge_transfer_energy_requires_the_corresponding_actual_products() -> None:
    donor = candidate_state({"Ar": 1}, 0)
    ion = candidate_state({"Ar": 1}, 1)
    target = candidate_state({"O": 2}, 0)
    product = candidate_state({"O": 2}, 1)
    changed_product = candidate_state(donor.composition, 0, phase="solid")
    reaction = _transfer(ion, target, changed_product, product)
    states = (donor, ion, target, product, changed_product)
    records = tuple(_energy_record(state, 12.0) for state in (donor, target, changed_product))
    judgment, values = _energy_result(reaction, states, records)
    assert judgment.verdict == "unknown"
    assert "charge_transfer_energy_defect_eV" not in values


def test_resonant_identity_needs_no_invented_ionization_energy() -> None:
    donor = candidate_state({"Ar": 1}, 0)
    ion = candidate_state({"Ar": 1}, 1)
    reaction = replace(_transfer(ion, donor, donor, ion), process="resonant_charge_exchange")
    _, values = _energy_result(reaction, (donor, ion))
    assert values["charge_transfer_energy_defect_eV"] == 0.0


def test_elastic_energy_identity_is_checked_without_requiring_energy_data() -> None:
    molecule, atom, electron = (
        candidate_state({"F": 2}, 0),
        candidate_state({"F": 1}, 0),
        electron_state(),
    )
    states = (molecule, atom, electron)
    reaction = ReactionCandidate(
        "elastic",
        (Term(electron.id), Term(molecule.id)),
        (Term(molecule.id), Term(electron.id)),
        "electron",
        "elastic",
        "test",
        "test",
        0,
    )
    valid, values = _energy_result(reaction, states)
    assert valid.verdict == "pass"
    assert valid.proposition == "elastic_internal_energy_identity"
    assert values == {}
    assert "translational energy transfer is undetermined" in valid.message

    dissociation = replace(reaction, products=(Term(electron.id), Term(atom.id, 2)))
    assert assess_consistency(
        dissociation, CandidateSet(states={s.id: s for s in states})
    ).verdict == ("fail")
    invalid, values = _energy_result(dissociation, states)
    assert invalid.verdict == "fail"
    assert invalid.basis == ("elastic equation identity",)
    assert "unchanged participant states" in invalid.message
    assert values == {}


def _binding_result(
    affinity: float, declarations: tuple[StateRecord, ...] = ()
) -> tuple[Assessment, StateEvidence]:
    parent = candidate_state({"O": 2}, 0)
    anion = candidate_state({"O": 2}, -1)
    candidates = CandidateSet(states={state.id: state for state in (parent, anion)})
    catalog = EvidenceCatalog(state_records=(_energy_record(parent, affinity), *declarations))
    evidence = {state.id: catalog.state(state) for state in (parent, anion)}
    return assess_state(anion, evidence[anion.id], candidates, evidence), evidence[anion.id]


@pytest.mark.parametrize("affinity", [-1.0, 1.0])
@pytest.mark.parametrize("tier", ["imported", "reviewed"])
def test_unknown_placeholder_retains_the_existing_affinity_binding_conclusion(
    affinity: float, tier: str
) -> None:
    anion = candidate_state({"O": 2}, -1)
    placeholder = StateRecord("placeholder", anion, existence="unknown", tier=tier)
    baseline, _ = _binding_result(affinity)
    actual, evidence = _binding_result(affinity, (placeholder,))
    assert actual == baseline
    assert actual.verdict == ("pass" if affinity > 0 else "fail")
    assert actual.proposition == "ground_anion_electron_binding"
    assert evidence.match == "exact"
    assert evidence.records == (placeholder,)


@pytest.mark.parametrize(
    ("existence", "affinity", "expected"),
    [("confirmed", -1.0, "pass"), ("unbound", 1.0, "fail")],
)
def test_reviewed_existence_assertions_keep_precedence_over_affinity_inference(
    existence: str, affinity: float, expected: str
) -> None:
    anion = candidate_state({"O": 2}, -1)
    declared = StateRecord(
        "explicit",
        anion,
        existence=existence,
        existence_source="explicit existence source",
        tier="reviewed",
    )
    judgment, _ = _binding_result(affinity, (declared,))
    assert judgment.verdict == expected
    assert judgment.proposition == "state_existence_support"
    assert judgment.basis == ("snapshot:explicit",)


@pytest.mark.parametrize("existence", ["unbound", "hypothetical"])
def test_unreviewed_assertions_are_not_overridden_by_positive_affinity(existence: str) -> None:
    anion = candidate_state({"O": 2}, -1)
    declared = StateRecord(
        "unreviewed",
        anion,
        existence=existence,
        existence_source="unreviewed existence source",
    )
    judgment, evidence = _binding_result(1.0, (declared,))
    assert judgment.verdict == "unknown"
    assert "unreviewed" in judgment.basis[0]
    assert evidence.records == (declared,)


def test_competing_reviewed_existence_assertions_remain_unknown_with_affinity() -> None:
    anion = candidate_state({"O": 2}, -1)
    confirmed = StateRecord(
        "confirmed",
        anion,
        existence="confirmed",
        existence_source="positive existence source",
        tier="reviewed",
    )
    unbound = replace(confirmed, id="unbound", existence="unbound", existence_source="negative")
    for declarations in ((confirmed, unbound), (unbound, confirmed)):
        judgment, evidence = _binding_result(1.0, declarations)
        assert judgment.verdict == "unknown"
        assert evidence.match == "exact"
        assert "existence assertions conflict" in judgment.message
        assert {record.existence for record in evidence.records} == {"confirmed", "unbound"}


def _thermal_inputs() -> tuple[ReactionCandidate, tuple[StateRecord, StateRecord]]:
    """An analytical NASA model whose F2 -> 2F standard Gibbs change is zero."""
    atom = candidate_state({"F": 1}, 0)
    molecule = candidate_state({"F": 2}, 0)
    atomic = Thermo(
        (3.5, 0, 0, 0, 0, 0, 0),
        (3.5, 0, 0, 0, 0, 0, 0),
        200,
        1000,
        6000,
        source="fit A",
        tier="reviewed",
        phase="gas",
        standard_pressure_Pa=100000,
    )
    diatomic = replace(
        atomic,
        low=tuple(2 * value for value in atomic.low),
        high=tuple(2 * value for value in atomic.high),
    )
    records = (
        StateRecord("atom", atom, thermo=atomic),
        StateRecord("molecule A", molecule, thermo=diatomic),
    )
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
    return reaction, records


def _thermal_result(
    reaction: ReactionCandidate, records: tuple[StateRecord, ...]
) -> tuple[Assessment, Assessment, dict[str, float]]:
    catalog = EvidenceCatalog(state_records=records)
    states = {record.candidate.id: record.candidate for record in records}
    evidence = {state.id: catalog.state(state) for state in states.values()}
    molecule = states[reaction.reactants[0].species]
    availability = assess_state_thermochemistry(molecule, evidence[molecule.id])
    relationship, values = assess_thermochemistry(
        reaction,
        CandidateSet(states=states),
        evidence,
        ReactionEvidence(),
        Conditions(gas_temperature_K=300),
    )
    return availability, relationship, values


def test_duplicate_nasa_citations_preserve_scientific_values_and_original_records() -> None:
    reaction, (atom, molecule) = _thermal_inputs()
    assert molecule.thermo is not None
    another = replace(
        molecule,
        id="molecule B",
        thermo=replace(molecule.thermo, source="fit B", tier="curated"),
    )
    baseline = _thermal_result(reaction, (atom, molecule))
    for records in ((atom, molecule, another), (another, molecule, atom), (atom, another)):
        availability, relation, values = _thermal_result(reaction, records)
        assert availability.verdict == baseline[0].verdict == "pass"
        assert availability.proposition == "thermochemical_representation_availability"
        assert relation.verdict == baseline[1].verdict == "unknown"
        assert relation.proposition == "reaction_energy_relation"
        assert values == baseline[2]
        assert values["delta_g_eV"] == pytest.approx(0, abs=1e-12)
        assert len(EvidenceCatalog(state_records=records).state_records) == len(records)


@pytest.mark.parametrize(
    "change",
    [
        {"low": (7.1, 0, 0, 0, 0, 0, 0)},
        {"high": (7.1, 0, 0, 0, 0, 0, 0)},
        {"t_min": 250},
        {"t_mid": 1200},
        {"t_max": 5000},
        {"phase": "solid"},
        {"standard_pressure_Pa": 101325},
    ],
)
def test_incompatible_nasa_model_domains_remain_conflicts(change: dict) -> None:
    reaction, (atom, molecule) = _thermal_inputs()
    assert molecule.thermo is not None
    another = replace(molecule, id="other fit", thermo=replace(molecule.thermo, **change))
    for records in ((atom, molecule, another), (another, molecule, atom)):
        availability, relation, values = _thermal_result(reaction, records)
        assert availability.verdict == relation.verdict == "unknown"
        assert "conflict" in availability.message
        assert "NASA7" in availability.message
        assert "conflicting declarations" in relation.message
        assert "delta_g_eV" not in values
        assert "equilibrium_constant_number_density" not in values


@pytest.mark.parametrize("keep_nasa", [False, True])
def test_formation_conflict_does_not_hide_an_independent_nasa_model(keep_nasa: bool) -> None:
    reaction, (atom, molecule) = _thermal_inputs()
    molecule = replace(
        molecule,
        thermo=molecule.thermo if keep_nasa else None,
        properties={"enthalpy_formation_eV": Property(1, "eV", tier="reviewed")},
    )
    another = replace(
        molecule,
        id="other formation value",
        properties={"enthalpy_formation_eV": Property(2, "eV", tier="reviewed")},
    )
    for records in ((atom, molecule, another), (another, molecule, atom)):
        availability, relation, values = _thermal_result(reaction, records)
        assert availability.verdict == ("pass" if keep_nasa else "unknown")
        assert "conflict" in availability.message
        assert "enthalpy_formation_eV" in availability.message
        assert "conflicting declarations" in relation.message
        assert "delta_h_eV" not in values
        assert ("delta_g_eV" in values) == keep_nasa


def test_unqualified_null_does_not_hide_a_reviewed_formation_value() -> None:
    from reactgen.records import FormationReference

    reference = FormationReference(0, "standard_elements", 100000)
    reaction, (atom, molecule) = _thermal_inputs()
    atom = replace(
        atom,
        properties={
            "enthalpy_formation_eV": Property(
                0, "eV", tier="reviewed", formation_reference=reference
            )
        },
    )
    molecule = replace(
        molecule,
        thermo=None,
        properties={
            "enthalpy_formation_eV": Property(
                1, "eV", tier="reviewed", formation_reference=reference
            )
        },
    )
    null = replace(
        molecule,
        id="unqualified null",
        properties={"enthalpy_formation_eV": Property(None, "eV", tier="curated")},
    )
    baseline = _thermal_result(reaction, (atom, molecule))
    for records in ((atom, molecule, null), (null, molecule, atom)):
        actual = _thermal_result(reaction, records)
        assert actual == baseline
        assert actual[0].verdict == "pass"
        assert actual[2]["delta_h_eV"] == -1


def _elastic_rate() -> tuple[ReactionCandidate, NumericDataset]:
    electron, atom = electron_state(), candidate_state({"Ar": 1}, 0)
    reaction = ReactionCandidate(
        "elastic rate",
        (Term(electron.id), Term(atom.id)),
        (Term(electron.id), Term(atom.id)),
        "electron",
        "elastic",
        "test",
        "test",
        0,
    )
    dataset = NumericDataset(
        "reviewed numerical value",
        "rate_coefficient",
        "constant",
        unit="m3/s",
        independent_variable="gas_temperature",
        observable="reaction_rate",
        params={"value": 1e-15},
        validity=Validity("gas_temperature", 300, 300, "K"),
        tier="reviewed",
    )
    return reaction, dataset


@pytest.mark.parametrize("unit", ["m3/s", "s-1"])
def test_reviewed_numerical_data_does_not_establish_a_channel_assertion(unit: str) -> None:
    reaction, dataset = _elastic_rate()
    evidence = ReactionEvidence(overlay_datasets=(replace(dataset, unit=unit),))
    channel = assess_reaction_evidence(reaction, evidence)
    numerical, _ = assess_kinetics(reaction, evidence, Conditions(gas_temperature_K=300))
    assert channel.verdict == "unknown"
    assert "channel assertion" in channel.message
    assert numerical.verdict == ("pass" if unit == "m3/s" else "fail")


def test_invalid_numerical_data_does_not_deny_an_explicit_reviewed_channel() -> None:
    reaction, dataset = _elastic_rate()
    record = ReactionRecord(
        "channel assertion",
        reaction.equation_key,
        reaction.family,
        reaction.process,
        (),
        tier="reviewed",
    )
    evidence = ReactionEvidence((record,), overlay_datasets=(replace(dataset, unit="s-1"),))
    assert assess_reaction_evidence(reaction, evidence).verdict == "pass"
    assert (
        assess_kinetics(reaction, evidence, Conditions(gas_temperature_K=300))[0].verdict == "fail"
    )


def test_evaluation_forwards_numeric_selection_without_qualifying_channel_or_state() -> None:
    reaction, first = _elastic_rate()
    second = replace(first, id="requested value", params={"value": 2e-15})
    states = (electron_state(), candidate_state({"Ar": 1}, 0))
    candidates = CandidateSet(
        states={state.id: state for state in states}, reactions={reaction.id: reaction}
    )
    catalog = EvidenceCatalog(overlay_datasets={reaction.id: (first, second)})
    selection = DataSelection({"rate_coefficient": QuantitySelection(record=second.id)})
    result = evaluate(candidates, catalog, Conditions(gas_temperature_K=300), selection)
    assert result.data_use[reaction.id].dataset_id == second.id
    assert result.data_use[reaction.id].value == 2e-15
    assert result.reaction_assessments[reaction.id]["reaction_evidence"].verdict == "unknown"
    assert result.state_assessments["Ar@ground"]["state"].verdict == "unknown"
