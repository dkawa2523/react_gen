"""Formation differences require one physical reference, not just matching units.

The synthetic values isolate temperature/basis and electron-convention rules.
NIST explains the convention and finite-T electron contribution at
https://webbook.nist.gov/chemistry/ion/ .
"""

from dataclasses import asdict, replace
from pathlib import Path

import pytest

from reactgen import adopt, derive, export, ingest, yamlio
from reactgen.assessment import assess_thermochemistry
from reactgen.case import Case, Conditions
from reactgen.chemistry import candidate_state
from reactgen.evidence import EvidenceCatalog, ReactionEvidence, StateEvidence
from reactgen.model import CandidateSet, ReactionCandidate, Term
from reactgen.pipeline import analyze
from reactgen.records import (
    FormationReference,
    Property,
    StateRecord,
    Thermo,
    normalized_property,
    state_record_payload,
)
from reactgen.registry import Registry
from reactgen.thermo import formation_delta, formation_reference


def record(count: int, value: float, reference: FormationReference | None, charge: int = 0):
    state = candidate_state({"F": count}, charge)
    return StateRecord(
        state.id,
        state,
        properties={
            "enthalpy_formation_eV": Property(
                value, "eV", tier="reviewed", formation_reference=reference
            )
        },
    )


def reaction(left, right):
    return ReactionCandidate("reference", left, right, "neutral", "dissociation", "test", "test", 0)


COMMON_REFERENCE = FormationReference(298.15, "standard_elements", 100000)


def split(reference=COMMON_REFERENCE):
    atom, molecule = record(1, 1.0, reference), record(2, 3.0, reference)
    return reaction((Term(molecule.id),), (Term(atom.id, 2),)), {
        item.id: item for item in (atom, molecule)
    }


def test_common_reference_units_direction_and_stoichiometry():
    channel, species = split()
    assert formation_delta(channel, species) == -1.0
    backward = replace(channel, reactants=channel.products, products=channel.reactants)
    assert formation_delta(backward, species) == 1.0
    atom = species["F@ground"]
    prop = atom.properties["enthalpy_formation_eV"]
    species[atom.id] = replace(
        atom,
        properties={"enthalpy_formation_eV": replace(prop, value=96.4853321233, unit="kJ/mol")},
    )
    assert formation_delta(channel, species) == pytest.approx(-1.0)
    assert formation_reference(channel, species).temperature_K == 298.15


@pytest.mark.parametrize(
    "reference",
    [
        None,
        FormationReference(basis="standard_elements", standard_pressure_Pa=100000),
        FormationReference(0, "standard_elements", 100000),
        FormationReference(298.15, None, 100000),
        FormationReference(298.15, "standard_elements"),
        FormationReference(298.15, "standard_elements", 101325),
    ],
)
def test_missing_or_incompatible_reference_cannot_be_a_difference(reference):
    channel, species = split()
    species["F@ground"] = record(1, 1, reference)
    assert formation_delta(channel, species) is None


@pytest.mark.parametrize("convention", ["ion", "electron"])
def test_zero_kelvin_conventions_agree_without_an_assumed_finite_t_electron_model(convention):
    reference = FormationReference(0, "standard_elements", 100000, convention)
    neutral, ion = record(1, 1, reference), record(1, 2, reference, 1)
    channel = reaction((Term(neutral.id),), (Term(ion.id), Term("e")))
    assert formation_delta(channel, {item.id: item for item in (neutral, ion)}) == 1.0


def test_finite_t_ion_convention_needs_electron_enthalpy_only_when_its_term_does_not_cancel():
    reference = FormationReference(298.15, "standard_elements", 100000, "ion")
    neutral, ion = record(1, 1, reference), record(1, 2, reference, 1)
    species = {item.id: item for item in (neutral, ion)}
    channel = reaction((Term(neutral.id),), (Term(ion.id), Term("e")))
    assert formation_delta(channel, species) is None
    supplied = replace(reference, electron_enthalpy_eV=0.0326)
    species[ion.id] = record(1, 2, supplied, 1)
    assert formation_delta(channel, species) == pytest.approx(1.0326)
    spectator = reaction((Term(ion.id), Term("e")), (Term(ion.id), Term("e")))
    assert formation_delta(spectator, {ion.id: ion}) == 0.0


def test_finite_t_electron_convention_sets_electron_formation_zero_and_does_not_mix_ion_data():
    electron = FormationReference(298.15, "standard_elements", 100000, "electron")
    neutral, cation = record(1, 1, electron), record(1, 2, electron, 1)
    channel = reaction((Term(neutral.id),), (Term(cation.id), Term("e")))
    assert formation_delta(channel, {item.id: item for item in (neutral, cation)}) == 1.0
    anion = record(1, 0, replace(electron, electron_convention="ion"), -1)
    paired = reaction((Term(neutral.id, 2),), (Term(cation.id), Term(anion.id)))
    assert formation_delta(paired, {item.id: item for item in (neutral, cation, anion)}) is None


def test_roundoff_of_cancelled_spectator_electrons_does_not_require_new_physical_information():
    reference = FormationReference(298.15, "standard_elements", 100000, "ion")
    ion = record(1, 2, reference, 1)
    channel = reaction(
        (Term(ion.id), Term("e", 0.1), Term("e", 0.2)),
        (Term(ion.id), Term("e", 0.3)),
    )
    assert formation_delta(channel, {ion.id: ion}) == 0
    reverse_order = replace(channel, reactants=tuple(reversed(channel.reactants)))
    assert formation_reference(channel, {ion.id: ion}) == formation_reference(
        reverse_order, {ion.id: ion}
    )


def test_missing_formation_reference_preserves_independent_nasa_and_source_energy():
    channel, species = split(None)
    coefficients = (2.5, 0, 0, 0, 0, 0, 0)
    thermo = Thermo(
        coefficients,
        coefficients,
        200,
        1000,
        2000,
        tier="reviewed",
        phase="gas",
        standard_pressure_Pa=100000,
    )
    states = {
        key: StateEvidence("exact", (replace(item, thermo=thermo),))
        for key, item in species.items()
    }
    candidates = CandidateSet(states={key: item.candidate for key, item in species.items()})
    decision, values = assess_thermochemistry(
        channel, candidates, states, ReactionEvidence(), Conditions(gas_temperature_K=300)
    )
    assert "delta_h_eV" not in values
    assert {"delta_g_eV", "equilibrium_constant_number_density"} <= values.keys()
    assert "compatible reference temperature" in decision.message
    channel, species = split()
    states = {key: StateEvidence("exact", (item,)) for key, item in species.items()}
    _, values = assess_thermochemistry(
        channel, candidates, states, ReactionEvidence(), Conditions(gas_temperature_K=500)
    )
    assert values["delta_h_reference_temperature_K"] == 298.15
    assert values["delta_h_standard_pressure_Pa"] == 100000


def test_referenced_quantity_is_not_overridden_by_an_unreferenced_quantity_or_input_order():
    channel, species = split()
    candidates = CandidateSet(states={key: item.candidate for key, item in species.items()})
    original = species["F@ground"]
    unreferenced = record(1, 999, None)
    molecule = species["F2@ground"]
    for ordered in ((original, unreferenced), (unreferenced, original)):
        states = {
            original.id: StateEvidence("exact", ordered),
            molecule.id: StateEvidence("exact", (molecule,)),
        }
        _, values = assess_thermochemistry(
            channel, candidates, states, ReactionEvidence(), Conditions()
        )
        assert values["delta_h_eV"] == -1


def test_equal_values_at_different_references_are_not_silently_selected():
    channel, species = split()
    original = species["F@ground"]
    another = record(1, 1, replace(COMMON_REFERENCE, temperature_K=0))
    molecule = species["F2@ground"]
    states = {
        original.id: StateEvidence("exact", (original, another)),
        molecule.id: StateEvidence("exact", (molecule,)),
    }
    candidates = CandidateSet(states={key: item.candidate for key, item in species.items()})
    _, values = assess_thermochemistry(
        channel, candidates, states, ReactionEvidence(), Conditions()
    )
    assert "delta_h_eV" not in values


def test_neutral_formation_comparison_does_not_depend_on_electron_metadata():
    channel, species = split()
    molecule = species["F2@ground"]
    atom = species["F@ground"]
    first = record(
        2, 3, replace(COMMON_REFERENCE, electron_convention="ion", electron_enthalpy_eV=0.0326)
    )
    second = record(2, 3, replace(COMMON_REFERENCE, electron_convention="electron"))
    original_declarations = [state_record_payload(item) for item in (first, second)]
    candidates = CandidateSet(states={key: item.candidate for key, item in species.items()})
    for ordered in ((first,), (second,), (first, second), (second, first)):
        states = {
            atom.id: StateEvidence("exact", (atom,)),
            molecule.id: StateEvidence("exact", ordered),
        }
        _, values = assess_thermochemistry(
            channel, candidates, states, ReactionEvidence(), Conditions()
        )
        assert values["delta_h_eV"] == -1
    assert [state_record_payload(item) for item in (first, second)] == original_declarations


@pytest.mark.parametrize("convention", ["electron", "ion"])
def test_missing_ion_convention_does_not_deny_an_independent_complete_reference(convention):
    reference = replace(COMMON_REFERENCE, electron_convention=convention, electron_enthalpy_eV=0)
    neutral, ion = record(1, 1, COMMON_REFERENCE), record(1, 2, reference, 1)
    incomplete = record(1, 2, COMMON_REFERENCE, 1)
    declarations = [state_record_payload(item) for item in (ion, incomplete)]
    channel = reaction((Term(neutral.id),), (Term(ion.id), Term("e")))
    candidates = CandidateSet(states={item.id: item.candidate for item in (neutral, ion)})
    for ordered in ((ion,), (ion, incomplete), (incomplete, ion)):
        states = {
            neutral.id: StateEvidence("exact", (neutral,)),
            ion.id: StateEvidence("exact", ordered),
        }
        _, values = assess_thermochemistry(
            channel, candidates, states, ReactionEvidence(), Conditions()
        )
        assert values["delta_h_eV"] == 1
    assert [state_record_payload(item) for item in (ion, incomplete)] == declarations
    states[ion.id] = StateEvidence("exact", (incomplete,))
    _, values = assess_thermochemistry(
        channel, candidates, states, ReactionEvidence(), Conditions()
    )
    assert "delta_h_eV" not in values


def test_distinct_declared_ion_conventions_remain_unresolved_for_one_quantity():
    neutral = record(1, 1, COMMON_REFERENCE)
    first = record(1, 2, replace(COMMON_REFERENCE, electron_convention="electron"), 1)
    second = record(
        1, 2, replace(COMMON_REFERENCE, electron_convention="ion", electron_enthalpy_eV=0), 1
    )
    channel = reaction((Term(neutral.id),), (Term(first.id), Term("e")))
    candidates = CandidateSet(states={item.id: item.candidate for item in (neutral, first)})
    for ordered in ((first, second), (second, first)):
        states = {
            neutral.id: StateEvidence("exact", (neutral,)),
            first.id: StateEvidence("exact", ordered),
        }
        _, values = assess_thermochemistry(
            channel, candidates, states, ReactionEvidence(), Conditions()
        )
        assert "delta_h_eV" not in values


@pytest.mark.parametrize(("convention", "electron_enthalpy"), [("ion", 0.0326), ("electron", 0.0)])
def test_missing_optional_electron_term_does_not_hide_a_complete_independent_reference(
    convention, electron_enthalpy
):
    complete = replace(
        COMMON_REFERENCE,
        electron_convention=convention,
        electron_enthalpy_eV=electron_enthalpy,
    )
    incomplete = replace(complete, electron_enthalpy_eV=None)
    neutral = record(1, 1, COMMON_REFERENCE)
    ion, missing = record(1, 2, complete, 1), record(1, 2, incomplete, 1)
    originals = [state_record_payload(item) for item in (ion, missing)]
    channel = reaction((Term(neutral.id),), (Term(ion.id), Term("e")))
    candidates = CandidateSet(states={item.id: item.candidate for item in (neutral, ion)})
    for ordered in ((ion,), (ion, missing), (missing, ion)):
        states = {
            neutral.id: StateEvidence("exact", (neutral,)),
            ion.id: StateEvidence("exact", ordered),
        }
        _, values = assess_thermochemistry(
            channel, candidates, states, ReactionEvidence(), Conditions()
        )
        assert values["delta_h_eV"] == pytest.approx(1 + electron_enthalpy)
    assert [state_record_payload(item) for item in (ion, missing)] == originals


@pytest.mark.parametrize("electron_changes", [False, True])
def test_distinct_explicit_electron_terms_affect_only_a_reaction_that_consumes_the_term(
    electron_changes,
):
    first = replace(COMMON_REFERENCE, electron_convention="ion", electron_enthalpy_eV=0.0326)
    second = replace(first, electron_enthalpy_eV=0.064)
    neutral, ion, another = (
        record(1, 1, COMMON_REFERENCE),
        record(1, 2, first, 1),
        record(1, 2, second, 1),
    )
    if electron_changes:
        channel = reaction((Term(neutral.id),), (Term(ion.id), Term("e")))
    else:
        channel = reaction((Term(ion.id),), (Term(ion.id),))
    candidates = CandidateSet(states={item.id: item.candidate for item in (neutral, ion)})
    from reactgen.assessment import assess_state_thermochemistry

    for ordered in ((ion, another), (another, ion)):
        states = {
            neutral.id: StateEvidence("exact", (neutral,)),
            ion.id: StateEvidence("exact", ordered),
        }
        decision, values = assess_thermochemistry(
            channel, candidates, states, ReactionEvidence(), Conditions()
        )
        availability = assess_state_thermochemistry(ion.candidate, states[ion.id])
        assert availability.verdict == "pass"
        if electron_changes:
            assert "delta_h_eV" not in values
            assert "formation_reference.electron_enthalpy_eV" in decision.message
        else:
            assert values["delta_h_eV"] == 0
            assert "electron_enthalpy_eV" not in decision.message


@pytest.mark.parametrize(
    ("complete_tier", "partial_tier"),
    [("reviewed", "reviewed"), ("curated", "reviewed"), ("reviewed", "curated")],
)
def test_missing_electron_term_does_not_hide_a_contradictory_qualified_formation_value(
    complete_tier, partial_tier
):
    complete_reference = replace(
        COMMON_REFERENCE, electron_convention="ion", electron_enthalpy_eV=0.0326
    )
    partial_reference = replace(complete_reference, electron_enthalpy_eV=None)
    neutral = record(1, 1, COMMON_REFERENCE)
    complete, partial = record(1, 2, complete_reference, 1), record(1, 99, partial_reference, 1)
    complete = replace(
        complete,
        properties={
            name: replace(prop, tier=complete_tier) for name, prop in complete.properties.items()
        },
    )
    partial = replace(
        partial,
        properties={
            name: replace(prop, tier=partial_tier) for name, prop in partial.properties.items()
        },
    )
    originals = [state_record_payload(item) for item in (complete, partial)]
    channel = reaction((Term(neutral.id),), (Term(complete.id), Term("e")))
    candidates = CandidateSet(states={item.id: item.candidate for item in (neutral, complete)})
    for ordered in ((complete, partial), (partial, complete)):
        states = {
            neutral.id: StateEvidence("exact", (neutral,)),
            complete.id: StateEvidence("exact", ordered),
        }
        decision, values = assess_thermochemistry(
            channel, candidates, states, ReactionEvidence(), Conditions()
        )
        assert "delta_h_eV" not in values
        assert "enthalpy_formation_eV" in decision.message
    assert [state_record_payload(item) for item in (complete, partial)] == originals


@pytest.mark.parametrize(
    "change",
    [
        {"temperature_K": True},
        {"temperature_K": -1},
        {"temperature_K": float("nan")},
        {"standard_pressure_Pa": 0},
        {"standard_pressure_Pa": float("inf")},
        {"basis": "unknown basis"},
        {"electron_convention": "unknown convention"},
        {"electron_convention": "electron", "electron_enthalpy_eV": 1},
        {"electron_convention": "ion", "electron_enthalpy_eV": -1},
    ],
)
def test_malformed_reference_rejected_at_both_python_and_input_boundaries(change):
    reference = {
        "temperature_K": 298.15,
        "basis": "standard_elements",
        "standard_pressure_Pa": 100000,
    } | change
    with pytest.raises(ValueError, match="formation_reference"):
        FormationReference(**reference)
    with pytest.raises(ValueError, match="formation_reference"):
        normalized_property({"value": 1, "unit": "eV", "formation_reference": reference})


def test_reference_survives_normalization_ingest_adopt_and_reload(tmp_path: Path):
    root = tmp_path / "registry"
    (root / "species").mkdir(parents=True)
    (root / "species" / "F.yaml").write_text(
        yamlio.dump({"id": "F", "composition": {"F": 1}, "phase": "gas"}), encoding="utf-8"
    )
    reference = FormationReference(0, "standard_elements", 100000, "ion", 0)
    original = record(1, 1, reference)
    prop = original.properties["enthalpy_formation_eV"]
    assert normalized_property(asdict(prop)) == prop
    snapshot = tmp_path / "snapshot.yaml"
    snapshot.write_text(
        yamlio.dump({"records": [state_record_payload(original)]}), encoding="utf-8"
    )
    overlay = tmp_path / "overlay.yaml"
    bundle = tmp_path / "result"
    export.write(
        bundle, analyze(Case("reference", ("F",), Conditions()), EvidenceCatalog.load(root))
    )
    ingest.ingest(snapshot, bundle, overlay)
    actual = EvidenceCatalog.load(root, overlay=overlay).state(original.candidate)
    assert actual.preferred.properties["enthalpy_formation_eV"].formation_reference == reference
    adopt.adopt(overlay, root)
    saved = EvidenceCatalog.load(root).state(original.candidate)
    assert [
        item.properties["enthalpy_formation_eV"].formation_reference
        for item in saved.records
        if "enthalpy_formation_eV" in item.properties
    ] == [reference]


def test_resolved_formation_offset_preserves_zero_k_and_does_not_invent_thermal_correction():
    parent = Registry.load(Path(__file__).parent / "fixtures" / "mini").species["Ar"]
    zero = FormationReference(0, "standard_elements", 100000)
    prop = Property(1, "eV", tier="reviewed", formation_reference=zero)
    parent = replace(parent, properties={"enthalpy_formation_eV": prop})
    derived = derive.carried_from(parent, 2)["enthalpy_formation_eV"]
    assert derived.value == 3
    assert derived.formation_reference == zero
    assert derived.source_declaration["parent_formation_enthalpy"] == asdict(prop)
    assert derived.source_declaration["level_energy_eV"] == 2
    finite = replace(prop, formation_reference=replace(zero, temperature_K=298.15))
    parent = replace(parent, properties={"enthalpy_formation_eV": finite})
    assert "enthalpy_formation_eV" not in derive.carried_from(parent, 2)
