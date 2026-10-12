"""Source review qualifies its named claim and never a neighbouring claim.

These are synthetic declarations. The tests concern qualification boundaries,
not the physical values or existence of the example chemical targets.
"""

from dataclasses import replace

import pytest

from reactgen.assessment import (
    _preferred_state,
    assess_state,
    assess_state_thermochemistry,
    assess_thermochemistry,
)
from reactgen.case import Conditions
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog, ReactionEvidence
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.records import (
    Property,
    RegistryState,
    Species,
    StateRecord,
    Thermo,
    normalized_property,
    normalized_state_record,
    normalized_thermo,
    state_record_payload,
)


@pytest.mark.parametrize(
    ("scopes", "verdict"),
    [
        ((), "pass"),
        (("state_existence",), "pass"),
        (("rate_coefficient",), "unknown"),
        (("ionization_energy_eV",), "unknown"),
        (("thermochemical_model",), "unknown"),
    ],
)
def test_existence_review_is_scoped_to_its_assertion(scopes, verdict) -> None:
    state = candidate_state({"F": 2}, 0)
    record = StateRecord(
        "declaration",
        state,
        existence="confirmed",
        existence_source="existence evidence",
        tier="reviewed",
        review_scope=scopes,
    )
    candidates = CandidateSet(states={state.id: state})
    judgment = assess_state(
        state, EvidenceCatalog(state_records=(record,)).state(state), candidates
    )
    assert judgment.verdict == verdict
    assert judgment.proposition == "state_existence_support"


def test_an_out_of_scope_existence_assertion_neither_wins_nor_creates_a_conflict() -> None:
    state = candidate_state({"F": 2}, 0)
    supported = StateRecord(
        "supported",
        state,
        existence="confirmed",
        existence_source="existence evidence",
        tier="reviewed",
        review_scope=("state_existence",),
    )
    unrelated = replace(
        supported,
        id="another claim",
        tier="curated",
        existence="unbound",
        review_scope=("rate_coefficient",),
    )
    for records in ((supported, unrelated), (unrelated, supported)):
        evidence = EvidenceCatalog(state_records=records).state(state)
        assert evidence.match == "exact"
        assert (
            assess_state(state, evidence, CandidateSet(states={state.id: state})).verdict == "pass"
        )
        assert len(evidence.records) == 2


def test_anion_binding_can_use_affinity_without_promoting_an_out_of_scope_existence_claim() -> None:
    neutral, anion = (candidate_state({"F": 1}, charge) for charge in (0, -1))
    affinity = StateRecord(
        "affinity",
        neutral,
        properties={
            "electron_affinity_eV": Property(
                1.0, "eV", tier="reviewed", review_scope=("electron_affinity_eV",)
            )
        },
    )
    unrelated = StateRecord(
        "unqualified existence",
        anion,
        existence="unbound",
        existence_source="another claim",
        tier="reviewed",
        review_scope=("rate_coefficient",),
    )
    catalog = EvidenceCatalog(state_records=(unrelated, affinity))
    states = CandidateSet(states={state.id: state for state in (neutral, anion)})
    evidence = {state.id: catalog.state(state) for state in (neutral, anion)}
    judgment = assess_state(anion, evidence[anion.id], states, evidence)
    assert judgment.verdict == "pass"
    assert judgment.proposition == "ground_anion_electron_binding"


@pytest.mark.parametrize("quantity", ["ionization_energy_eV", "electron_affinity_eV"])
def test_property_scope_is_its_quantity_name_and_does_not_qualify_another_property(
    quantity,
) -> None:
    state = candidate_state({"F": 1}, 0)
    prop = Property(1.0, "eV", tier="reviewed", review_scope=(quantity,))
    record = StateRecord(
        "properties",
        state,
        properties=dict.fromkeys(("ionization_energy_eV", "electron_affinity_eV"), prop),
    )
    matched = EvidenceCatalog(state_records=(record,)).state(state)
    selected = _preferred_state(state.id, {state.id: matched})
    assert selected is not None
    assert set(selected.properties) == {quantity}
    assert set(matched.records[0].properties) == {"ionization_energy_eV", "electron_affinity_eV"}


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_rejected_property_is_preserved_but_cannot_conflict_with_a_qualified_value(status) -> None:
    state = candidate_state({"F": 1}, 0)
    qualified = StateRecord(
        "qualified",
        state,
        properties={"ionization_energy_eV": Property(1.0, "eV", tier="reviewed")},
    )
    invalid = replace(
        qualified,
        id="not qualified",
        properties={
            "ionization_energy_eV": normalized_property(
                {"value": 2.0, "unit": "eV", "tier": "curated", "status": status}
            )
        },
    )
    for records in ((qualified, invalid), (invalid, qualified)):
        matched = EvidenceCatalog(state_records=records).state(state)
        selected = _preferred_state(state.id, {state.id: matched})
        assert selected is not None
        assert selected.value("ionization_energy_eV") == 1.0
        assert len(matched.records) == 2
    reread = normalized_state_record(state_record_payload(invalid), state)
    assert reread.properties["ionization_energy_eV"].status == status


def test_scoped_property_conflict_only_excludes_its_qualified_quantity() -> None:
    state = candidate_state({"F": 1}, 0)
    first = StateRecord(
        "first",
        state,
        properties={
            "ionization_energy_eV": Property(1.0, "eV", tier="reviewed"),
            "electron_affinity_eV": Property(2.0, "eV", tier="reviewed"),
        },
    )
    another = replace(
        first,
        id="another",
        properties={
            "ionization_energy_eV": Property(3.0, "eV", tier="reviewed"),
            "electron_affinity_eV": Property(
                4.0, "eV", tier="curated", review_scope=("rate_coefficient",)
            ),
        },
    )
    for records in ((first, another), (another, first)):
        evidence = EvidenceCatalog(state_records=records).state(state)
        selected = _preferred_state(state.id, {state.id: evidence})
        assert selected is not None
        assert "ionization_energy_eV" not in selected.properties
        assert selected.value("electron_affinity_eV") == 2.0


def thermal_records() -> tuple[ReactionCandidate, tuple[StateRecord, StateRecord]]:
    atom, molecule = (candidate_state({"F": count}, 0) for count in (1, 2))
    thermo = Thermo(
        (3.5, 0, 0, 0, 0, 0, 0),
        (3.5, 0, 0, 0, 0, 0, 0),
        200,
        1000,
        6000,
        tier="reviewed",
        phase="gas",
        standard_pressure_Pa=100000,
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
    return reaction, (
        StateRecord("atom", atom, thermo=thermo),
        StateRecord("molecule", molecule, thermo=thermo),
    )


def thermal_values(reaction: ReactionCandidate, records: tuple[StateRecord, ...]):
    catalog = EvidenceCatalog(state_records=records)
    states = {record.candidate.id: record.candidate for record in records}
    evidence = {state.id: catalog.state(state) for state in states.values()}
    availability = assess_state_thermochemistry(
        states[reaction.reactants[0].species], evidence[reaction.reactants[0].species]
    )
    _, values = assess_thermochemistry(
        reaction,
        CandidateSet(states=states),
        evidence,
        ReactionEvidence(),
        Conditions(gas_temperature_K=300),
    )
    return availability, values


@pytest.mark.parametrize(
    ("scopes", "usable"),
    [
        ((), True),
        (("thermochemical_model",), True),
        (("rate_coefficient",), False),
        (("state_existence",), False),
    ],
)
def test_nasa_availability_and_all_calculated_outputs_share_model_qualification(
    scopes, usable
) -> None:
    reaction, (atom, molecule) = thermal_records()
    assert molecule.thermo is not None
    molecule = replace(molecule, thermo=replace(molecule.thermo, review_scope=scopes))
    availability, values = thermal_values(reaction, (atom, molecule))
    assert (availability.verdict == "pass") is usable
    assert ("delta_g_eV" in values) is usable
    assert ("equilibrium_constant_number_density" in values) is usable
    assert ("standard_pressure_Pa" in values) is usable


@pytest.mark.parametrize("status", ["rejected", "conflicting"])
def test_rejected_nasa_does_not_qualify_or_mask_an_independent_model(status) -> None:
    reaction, (atom, molecule) = thermal_records()
    assert molecule.thermo is not None
    baseline = thermal_values(reaction, (atom, molecule))
    wrong = replace(
        molecule,
        id="wrong",
        thermo=replace(molecule.thermo, status=status, low=(4.0, 0, 0, 0, 0, 0, 0)),
    )
    assert thermal_values(reaction, (atom, wrong))[0].verdict == "unknown"
    for records in ((atom, wrong, molecule), (molecule, atom, wrong)):
        assert thermal_values(reaction, records) == baseline
    reread = normalized_thermo(state_record_payload(wrong)["thermo"])
    assert reread is not None
    assert reread.status == status


@pytest.mark.parametrize("registry", [False, True])
@pytest.mark.parametrize(
    ("scopes", "usable"),
    [((), True), (("excitation_energy_eV",), True), (("state_existence",), False)],
)
def test_legacy_excitation_scalar_inherits_its_parent_scope_in_both_adapters(
    registry, scopes, usable
) -> None:
    state = candidate_state({"F": 1}, 0, "electronic", label="level", resolution="resolved")
    if registry:
        species = Species(
            "F_level",
            state.composition,
            0,
            frozenset(),
            state=RegistryState(
                kind="electronic", label="level", energy_eV=1.0, review_scope=scopes
            ),
            status="reviewed",
            phase="gas",
        )
        record = StateRecord(
            "legacy",
            state,
            properties=species.properties,
            energy_eV=1.0,
            tier="reviewed",
            review_scope=scopes,
        )
    else:
        record = StateRecord("legacy", state, energy_eV=1.0, tier="reviewed", review_scope=scopes)
    prop = record.properties["excitation_energy_eV"]
    assert prop.review_scope == scopes
    assert prop.reviewed_for("excitation_energy_eV") is usable
    assert (
        normalized_state_record(state_record_payload(record), state).properties[
            "excitation_energy_eV"
        ]
        == prop
    )


def test_explicit_energy_property_has_its_own_review_despite_parent_existence_scope() -> None:
    state = candidate_state({"F": 1}, 0, "electronic", label="level", resolution="resolved")
    record = StateRecord(
        "independent quantity",
        state,
        energy_eV=1.0,
        tier="reviewed",
        review_scope=("state_existence",),
        properties={
            "excitation_energy_eV": Property(
                1.0, "eV", tier="reviewed", review_scope=("excitation_energy_eV",)
            )
        },
    )
    assert record.properties["excitation_energy_eV"].reviewed_for("excitation_energy_eV")
